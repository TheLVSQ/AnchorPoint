import json
import logging
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from core.models import OrganizationSettings
from core.permissions import checkin_admin_required, staff_required
from households.models import Household
from people.models import Person, normalize_phone

from .forms import (
    CheckInConfigurationForm, CheckInWindowFormSet, CheckInSessionForm,
    FamilyMemberSelectForm, KioskLookupForm, KioskPinForm,
    QuickRegistrationForm, QuickRegistrationChildForm,
    RoomForm, PrinterConfigForm, SecurityCodeLookupForm,
)
from .models import (
    CheckIn, CheckInConfiguration, CheckInSession, CheckInWindow,
    Room, PrinterConfiguration, PrintAgent, generate_unique_security_code,
)
from .services import PrintService
from .services.checkin_sms import send_security_code_sms
from .services.eligibility import get_eligible_members
from .services.session_manager import get_or_create_session
from .services.quick_registration import register_new_family
from .services.print_queue import enqueue_checkin_labels, enqueue_test_label, get_active_agent

logger = logging.getLogger(__name__)


KIOSK_SESSION_KEY = "kiosk_authenticated"
KIOSK_SESSION_ID_KEY = "kiosk_session_id"


# =============================================================================
# KIOSK HELPER FUNCTIONS
# =============================================================================


def _ensure_kiosk(request):
    """Redirect to unlock if kiosk not authenticated."""
    if not request.session.get(KIOSK_SESSION_KEY):
        return redirect("checkin:kiosk_unlock")
    return None


def _get_active_session(request):
    """Get the active CheckInSession from the kiosk session.

    Scoped to *today* so a session id left over from a previous day (the kiosk
    browser keeps the cookie indefinitely) is never reused — that would check
    families into a closed/stale session.
    """
    session_id = request.session.get(KIOSK_SESSION_ID_KEY)
    if session_id:
        return CheckInSession.objects.filter(
            pk=session_id, is_active=True, date=timezone.localdate()
        ).first()
    return None


def _next_upcoming_window():
    """Find the next check-in window that will open."""
    now = timezone.localtime()
    windows = CheckInWindow.objects.filter(
        is_active=True, configuration__is_active=True
    )
    for w in windows:
        if w.schedule_type == CheckInWindow.TYPE_SPECIFIC_DATE:
            if w.specific_date and w.specific_date >= now.date():
                return w
        else:
            return w
    return None


# =============================================================================
# KIOSK VIEWS (Public-facing, PIN-gated)
# =============================================================================


def kiosk_unlock(request):
    org = OrganizationSettings.load()
    if request.method == "POST":
        form = KioskPinForm(request.POST, expected_pin=org.kiosk_pin)
        if form.is_valid():
            request.session[KIOSK_SESSION_KEY] = True
            return redirect("checkin:kiosk_lookup")
    else:
        form = KioskPinForm()
    return render(request, "checkin/kiosk/unlock.html", {"form": form, "org": org})


def kiosk_lookup(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    org = OrganizationSettings.load()

    # Find open configurations (schedule-driven sessions)
    now = timezone.localtime()
    open_configs = []
    for config in CheckInConfiguration.objects.filter(is_active=True):
        windows = config.open_windows(now)
        if windows:
            open_configs.append((config, windows[0]))

    if open_configs:
        if len(open_configs) == 1:
            config, window = open_configs[0]
            session = get_or_create_session(config, window)
            request.session[KIOSK_SESSION_ID_KEY] = session.pk
        elif len(open_configs) > 1:
            # Multiple configs open — show the picker unless the kiosk already
            # holds a session for one of the *currently open* configs today.
            # (A leftover id from another day/config must not skip the picker.)
            current = _get_active_session(request)
            open_config_ids = {config.pk for config, _ in open_configs}
            if not (current and current.configuration_id in open_config_ids and current.is_open):
                request.session.pop(KIOSK_SESSION_ID_KEY, None)
                return render(request, "checkin/kiosk/config_picker.html", {
                    "open_configs": open_configs,
                    "org": org,
                })
    else:
        # No config windows open — fall back to any active standalone session today
        today = timezone.localdate()
        standalone_session = (
            CheckInSession.objects
            .filter(date=today, is_active=True)
            .order_by("-checkin_opens")
            .first()
        )
        if standalone_session:
            request.session[KIOSK_SESSION_ID_KEY] = standalone_session.pk
        else:
            next_window = _next_upcoming_window()
            return render(request, "checkin/kiosk/no_sessions.html", {
                "org": org, "next_window": next_window,
            })

    session = _get_active_session(request)
    if not session:
        return redirect("checkin:kiosk_unlock")

    MAX_RESULTS = 25
    households = []
    results_capped = False
    query = ""
    if request.method == "GET" and "query" in request.GET:
        form = KioskLookupForm(request.GET)
        if form.is_valid():
            query = form.cleaned_data["query"]
            digits = normalize_phone(query)
            if len(digits) >= 7:
                matches = Household.objects.filter(
                    members__normalized_phone__endswith=digits[-10:]
                ).distinct()
            else:
                matches = (
                    Household.objects.filter(name__icontains=query)
                    | Household.objects.filter(members__last_name__icontains=query)
                ).distinct()
            households = list(matches.order_by("name")[: MAX_RESULTS + 1])
            results_capped = len(households) > MAX_RESULTS
            households = households[:MAX_RESULTS]
        else:
            query = request.GET.get("query", "")
    else:
        form = KioskLookupForm()

    return render(request, "checkin/kiosk/lookup_new.html", {
        "form": form,
        "households": households,
        "query": query,
        "results_capped": results_capped,
        "session": session,
        "org": org,
    })


def kiosk_family_select(request, household_id):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    session = _get_active_session(request)
    if not session:
        return redirect("checkin:kiosk_lookup")

    household = get_object_or_404(Household, pk=household_id)
    config = session.configuration
    if config:
        members_with_eligibility = get_eligible_members(household, config)
    else:
        # Standalone session (no config) — everyone is eligible
        members = household.members.all().select_related()
        members_with_eligibility = [(person, True) for person in members]
    rooms = list(session.rooms.all())

    if request.method == "POST":
        form = FamilyMemberSelectForm(
            request.POST,
            members_with_eligibility=members_with_eligibility,
            rooms=rooms,
        )
        if form.is_valid():
            selected = form.get_selected()
            if not selected:
                form.add_error(None, "Please select at least one person.")
            else:
                security_code = generate_unique_security_code(session)
                checkin_ids = []
                for person_id, room_id in selected:
                    person = Person.objects.get(pk=person_id)
                    room = Room.objects.get(pk=room_id) if room_id else None
                    # Reuse an existing *active* check-in (re-print/move room);
                    # otherwise create one. A previously checked-out person gets
                    # a fresh record. Either way the pk is included so the person
                    # always appears on the confirmation page and labels.
                    checkin = CheckIn.objects.filter(
                        session=session,
                        person=person,
                        checked_out_at__isnull=True,
                    ).first()
                    if checkin:
                        checkin.room = room
                        checkin.security_code = security_code
                        checkin.save(update_fields=["room", "security_code"])
                    else:
                        checkin = CheckIn.objects.create(
                            session=session,
                            person=person,
                            room=room,
                            security_code=security_code,
                        )
                    checkin_ids.append(checkin.pk)

                request.session["kiosk_checkin_ids"] = checkin_ids
                request.session["kiosk_security_code"] = security_code
                # Queue labels for the local print agent. No-op if none is
                # paired (the confirmation page still offers browser printing),
                # and never block check-in on a printing problem.
                queued = 0
                try:
                    ordered = sorted(
                        CheckIn.objects.filter(pk__in=checkin_ids)
                        .select_related("person", "room"),
                        key=lambda c: checkin_ids.index(c.pk),
                    )
                    queued = enqueue_checkin_labels(ordered, session)
                except Exception:
                    logger.exception("Failed to queue print jobs for check-in")
                # Tell the confirmation page labels are already on their way via
                # the agent, so it must not also direct-print (duplicate labels).
                request.session["kiosk_labels_queued"] = queued > 0

                # Text the pickup code to opted-in household adults. Best-effort:
                # a Twilio problem must never block the check-in line.
                sms_sent = 0
                try:
                    ordered_checkins = CheckIn.objects.filter(
                        pk__in=checkin_ids
                    ).select_related("person")
                    sms_sent = send_security_code_sms(
                        household, ordered_checkins, security_code, session
                    )
                except Exception:
                    logger.exception("Failed to send check-in code SMS")
                request.session["kiosk_sms_sent"] = sms_sent > 0
                return redirect("checkin:kiosk_confirmation")
    else:
        form = FamilyMemberSelectForm(
            members_with_eligibility=members_with_eligibility,
            rooms=rooms,
        )

    return render(request, "checkin/kiosk/family_select.html", {
        "household": household,
        "form": form,
        "members_with_eligibility": members_with_eligibility,
        "rooms": rooms,
        "session": session,
        "config": config,
    })


def kiosk_confirmation(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    checkin_ids = request.session.pop("kiosk_checkin_ids", [])
    security_code = request.session.pop("kiosk_security_code", "")
    labels_queued = request.session.pop("kiosk_labels_queued", False)
    sms_sent = request.session.pop("kiosk_sms_sent", False)
    checkins = CheckIn.objects.filter(pk__in=checkin_ids).select_related("person", "room")
    org = OrganizationSettings.load()
    session = _get_active_session(request)

    if labels_queued:
        # The print agent already has these labels — direct-printing too would
        # produce duplicates when both an agent and a printer are configured.
        printer_ok = True
    else:
        printer_ok = PrintService().print_checkins(checkins, session)

    return render(request, "checkin/kiosk/confirmation.html", {
        "checkins": checkins,
        "security_code": security_code,
        "session": session,
        "org": org,
        "printer_ok": printer_ok,
        "sms_sent": sms_sent,
    })


def kiosk_quick_register(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    org = OrganizationSettings.load()

    if request.method == "POST":
        parent_form = QuickRegistrationForm(request.POST)
        # child_count is a high-water mark of indices ever added on the page.
        # Removing a child leaves a gap in the prefixes (child_0, child_2, ...),
        # so only bind forms for indices actually present in the POST.
        try:
            child_count = min(int(request.POST.get("child_count", "1")), 12)
        except (TypeError, ValueError):
            child_count = 1
        child_forms = []
        children_valid = True
        for i in range(child_count):
            prefix = f"child_{i}"
            if f"{prefix}-first_name" not in request.POST:
                continue
            cf = QuickRegistrationChildForm(request.POST, prefix=prefix)
            child_forms.append(cf)
            if not cf.is_valid():
                children_valid = False
        if not child_forms:
            children_valid = False
            parent_form.add_error(None, "Add at least one child to register.")

        if parent_form.is_valid() and children_valid:
            children_data = []
            for cf in child_forms:
                child_data = {
                    "first_name": cf.cleaned_data["first_name"],
                    "last_name": cf.cleaned_data.get("last_name") or parent_form.cleaned_data["parent_last_name"],
                    "birthdate": cf.cleaned_data["birthdate"],
                    "allergies": cf.cleaned_data.get("allergies", ""),
                    "custody_flag": cf.cleaned_data.get("custody_flag", False),
                    "custody_notes": cf.cleaned_data.get("custody_notes", ""),
                    "unauthorized_pickup": cf.cleaned_data.get("unauthorized_pickup", ""),
                }
                children_data.append(child_data)

            result = register_new_family(
                parent_first=parent_form.cleaned_data["parent_first_name"],
                parent_last=parent_form.cleaned_data["parent_last_name"],
                parent_phone=parent_form.cleaned_data["parent_phone"],
                parent_email=parent_form.cleaned_data.get("parent_email", ""),
                phone_opt_in=parent_form.cleaned_data.get("phone_opt_in", False),
                children=children_data,
            )
            return redirect("checkin:kiosk_family_select", household_id=result["household"].pk)
    else:
        parent_form = QuickRegistrationForm()
        child_forms = [QuickRegistrationChildForm(prefix="child_0")]
        children_valid = True

    return render(request, "checkin/kiosk/quick_register.html", {
        "parent_form": parent_form,
        "child_forms": child_forms,
        "invalid_children": not children_valid,
        "org": org,
    })


def kiosk_select_config(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir
    if request.method == "POST":
        config_pk = request.POST.get("config_pk")
        window_pk = request.POST.get("window_pk")
        if config_pk and window_pk:
            try:
                config = CheckInConfiguration.objects.get(pk=config_pk, is_active=True)
                window = CheckInWindow.objects.get(pk=window_pk, configuration=config, is_active=True)
                # Only honor a window that is actually open right now — guards
                # against a stale POST selecting a window that has since closed.
                if window.is_checkin_open(timezone.localtime()):
                    session = get_or_create_session(config, window)
                    request.session[KIOSK_SESSION_ID_KEY] = session.pk
            except (CheckInConfiguration.DoesNotExist, CheckInWindow.DoesNotExist):
                pass
    return redirect("checkin:kiosk_lookup")


def kiosk_lock(request):
    request.session.pop(KIOSK_SESSION_KEY, None)
    request.session.pop(KIOSK_SESSION_ID_KEY, None)
    return redirect("checkin:kiosk_unlock")


# =============================================================================
# CHECKOUT VIEWS (Volunteer-facing)
# =============================================================================


@login_required
def checkout_lookup(request, session_id):
    """Look up check-ins by security code for checkout."""
    session = get_object_or_404(CheckInSession, pk=session_id)

    checkins = None
    if request.method == "POST":
        form = SecurityCodeLookupForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["security_code"]
            checkins = CheckIn.objects.filter(
                session=session,
                security_code=code,
                checked_out_at__isnull=True,
            ).select_related("person", "room")

            if not checkins.exists():
                form.add_error("security_code", "No active check-ins found with this code.")
    else:
        form = SecurityCodeLookupForm()

    return render(
        request,
        "checkin/checkout/lookup.html",
        {
            "session": session,
            "form": form,
            "checkins": checkins,
        },
    )


@login_required
@require_POST
def checkout_confirm(request, session_id):
    """Confirm checkout for selected check-ins."""
    session = get_object_or_404(CheckInSession, pk=session_id)

    checkin_ids = request.POST.getlist("checkin_ids")
    checkins = CheckIn.objects.filter(
        id__in=checkin_ids,
        session=session,
        checked_out_at__isnull=True,
    )

    count = 0
    for checkin in checkins:
        checkin.checkout(user=request.user)
        count += 1

    messages.success(request, f"Successfully checked out {count} {'person' if count == 1 else 'people'}.")
    return redirect("checkin:checkout_lookup", session_id=session_id)


# =============================================================================
# CONFIGURATION ADMIN VIEWS (checkin_admin_required)
# =============================================================================


@checkin_admin_required
def configuration_list(request):
    configs = CheckInConfiguration.objects.prefetch_related("windows", "rooms", "groups")
    return render(request, "checkin/config_list.html", {"configurations": configs})


@checkin_admin_required
def configuration_create(request):
    return _config_form(request, instance=None)


@checkin_admin_required
def configuration_edit(request, pk):
    config = get_object_or_404(CheckInConfiguration, pk=pk)
    return _config_form(request, instance=config)


@checkin_admin_required
def configuration_delete(request, pk):
    config = get_object_or_404(CheckInConfiguration, pk=pk)
    if request.method == "POST":
        config.delete()
        return redirect("checkin:configuration_list")
    return render(request, "checkin/config_confirm_delete.html", {"config": config})


def _config_form(request, instance):
    if request.method == "POST":
        form = CheckInConfigurationForm(request.POST, instance=instance)
        formset = CheckInWindowFormSet(request.POST, instance=instance or CheckInConfiguration())
        if form.is_valid() and formset.is_valid():
            config = form.save()
            formset.instance = config
            formset.save()
            return redirect("checkin:configuration_list")
    else:
        form = CheckInConfigurationForm(instance=instance)
        formset = CheckInWindowFormSet(instance=instance or CheckInConfiguration())
    return render(request, "checkin/config_form.html", {
        "form": form,
        "formset": formset,
        "editing": instance is not None,
    })


# =============================================================================
# ADMIN/DASHBOARD VIEWS (Staff-facing)
# =============================================================================


@staff_required
def dashboard(request):
    """Check-in dashboard showing current sessions."""
    today = timezone.localdate()
    sessions = (
        CheckInSession.objects
        .filter(date=today)
        .prefetch_related("checkins")
        .order_by("checkin_opens")
    )
    agent = get_active_agent()

    return render(
        request,
        "checkin/dashboard.html",
        {
            "sessions": sessions,
            "today": today,
            "agent": agent,
        },
    )


@staff_required
def session_detail(request, session_id):
    """Detailed view of a check-in session."""
    session = get_object_or_404(CheckInSession, pk=session_id)

    checkins = session.checkins.select_related("person", "room").order_by(
        "room__sort_order", "person__last_name"
    )

    # Group by room
    rooms_data = {}
    for checkin in checkins:
        room_name = checkin.room.name if checkin.room else "Unassigned"
        if room_name not in rooms_data:
            rooms_data[room_name] = []
        rooms_data[room_name].append(checkin)

    return render(
        request,
        "checkin/session_detail.html",
        {
            "session": session,
            "checkins": checkins,
            "rooms_data": rooms_data,
            "stats": _session_stats(session),
            "agent": get_active_agent(),
        },
    )


@staff_required
def session_list(request):
    """List all check-in sessions."""
    sessions = (
        CheckInSession.objects
        .all()
        .prefetch_related("checkins")
        .order_by("-date", "-checkin_opens")
    )

    return render(
        request,
        "checkin/session_list.html",
        {
            "sessions": sessions,
        },
    )


@staff_required
def session_create(request):
    """Create a new check-in session."""
    if request.method == "POST":
        form = CheckInSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.created_by = request.user
            session.save()
            form.save_m2m()
            messages.success(request, "Check-in session created.")
            return redirect("checkin:session_detail", session_id=session.pk)
    else:
        form = CheckInSessionForm(initial={"date": timezone.localdate()})

    return render(
        request,
        "checkin/session_form.html",
        {
            "form": form,
            "title": "Create Check-In Session",
        },
    )


@staff_required
def session_edit(request, session_id):
    """Edit a check-in session."""
    session = get_object_or_404(CheckInSession, pk=session_id)

    if request.method == "POST":
        form = CheckInSessionForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            messages.success(request, "Check-in session updated.")
            return redirect("checkin:session_detail", session_id=session.pk)
    else:
        form = CheckInSessionForm(instance=session)

    return render(
        request,
        "checkin/session_form.html",
        {
            "form": form,
            "session": session,
            "title": "Edit Check-In Session",
        },
    )


@staff_required
def room_list(request):
    """List all rooms."""
    rooms = Room.objects.all().order_by("sort_order", "name")

    return render(
        request,
        "checkin/room_list.html",
        {
            "rooms": rooms,
        },
    )


@staff_required
def room_create(request):
    """Create a new room."""
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Room created.")
            return redirect("checkin:room_list")
    else:
        form = RoomForm()

    return render(
        request,
        "checkin/room_form.html",
        {
            "form": form,
            "title": "Create Room",
        },
    )


@staff_required
def room_edit(request, room_id):
    """Edit a room."""
    room = get_object_or_404(Room, pk=room_id)

    if request.method == "POST":
        form = RoomForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, "Room updated.")
            return redirect("checkin:room_list")
    else:
        form = RoomForm(instance=room)

    return render(
        request,
        "checkin/room_form.html",
        {
            "form": form,
            "room": room,
            "title": "Edit Room",
        },
    )


@staff_required
def printer_list(request):
    """List configured printers."""
    printers = PrinterConfiguration.objects.all()

    return render(
        request,
        "checkin/printer_list.html",
        {
            "printers": printers,
        },
    )


@staff_required
def printer_create(request):
    """Configure a new printer."""
    if request.method == "POST":
        form = PrinterConfigForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Printer configured.")
            return redirect("checkin:printer_list")
    else:
        form = PrinterConfigForm()

    return render(
        request,
        "checkin/printer_form.html",
        {
            "form": form,
            "title": "Configure Printer",
        },
    )


@staff_required
def printer_edit(request, printer_id):
    """Edit printer configuration."""
    printer = get_object_or_404(PrinterConfiguration, pk=printer_id)

    if request.method == "POST":
        form = PrinterConfigForm(request.POST, instance=printer)
        if form.is_valid():
            form.save()
            messages.success(request, "Printer configuration updated.")
            return redirect("checkin:printer_list")
    else:
        form = PrinterConfigForm(instance=printer)

    return render(
        request,
        "checkin/printer_form.html",
        {
            "form": form,
            "printer": printer,
            "title": "Edit Printer",
        },
    )


@staff_required
@require_POST
def printer_test(request, printer_id):
    """Test print to a configured printer."""
    printer = get_object_or_404(PrinterConfiguration, pk=printer_id)

    try:
        service = PrintService(printer)
        if service.test_printer():
            messages.success(request, f"Test print sent to {printer.name}.")
        else:
            messages.error(request, f"Failed to print to {printer.name}.")
    except Exception as e:
        messages.error(request, f"Printer error: {e}")

    return redirect("checkin:printer_list")


# =============================================================================
# API VIEWS (For HTMX/JavaScript)
# =============================================================================


def _session_stats(session):
    """Live counts for a session: totals plus per-room occupancy (one query)."""
    checked_in = session.checkins.filter(checked_out_at__isnull=True).count()
    checked_out = session.checkins.filter(checked_out_at__isnull=False).count()

    room_counts = {
        row["room"]: row["count"]
        for row in session.checkins.filter(checked_out_at__isnull=True)
        .values("room")
        .annotate(count=Count("id"))
    }
    rooms = []
    for room in session.rooms.all().order_by("sort_order", "name"):
        count = room_counts.get(room.pk, 0)
        percent = (
            min(100, round(count / room.capacity * 100)) if room.capacity else None
        )
        rooms.append(
            {
                "name": room.name,
                "count": count,
                "capacity": room.capacity,
                "percent": percent,
                "full": room.capacity and count >= room.capacity,
            }
        )

    return {
        "checked_in": checked_in,
        "checked_out": checked_out,
        "total": checked_in + checked_out,
        "unassigned": room_counts.get(None, 0),
        "rooms": rooms,
    }


@staff_required
def session_stats(request, session_id):
    """HTMX partial: live stats block for a session. Polls while check-in is open."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    agent = get_active_agent()
    return render(request, "checkin/session_stats.html", {
        "session": session,
        "stats": _session_stats(session),
        "agent": agent,
    })


@staff_required
def api_session_stats(request, session_id):
    """Get real-time stats for a session (AJAX). Staff-only — exposes
    attendance counts and per-room occupancy."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    stats = _session_stats(session)
    return JsonResponse({
        "checked_in": stats["checked_in"],
        "checked_out": stats["checked_out"],
        "total": stats["total"],
        "rooms": [
            {"name": r["name"], "count": r["count"], "capacity": r["capacity"]}
            for r in stats["rooms"]
        ],
    })


# =============================================================================
# PRINT AGENT MANAGEMENT (surfaced in Settings)
# =============================================================================


@staff_required
def print_agent_list(request):
    agents = PrintAgent.objects.all()
    return render(request, "checkin/agents/list.html", {"agents": agents})


@staff_required
@require_POST
def print_agent_create(request):
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Give the print agent a name.")
        return redirect("checkin:print_agents")
    agent = PrintAgent.objects.create(name=name)
    agent.issue_pairing_code()
    messages.success(
        request,
        f"Created '{name}'. Enter its pairing code (shown below) into the agent.",
    )
    return redirect("checkin:print_agents")


@staff_required
@require_POST
def print_agent_repair(request, agent_id):
    agent = get_object_or_404(PrintAgent, pk=agent_id)
    agent.issue_pairing_code()
    messages.success(request, f"New pairing code issued for '{agent.name}'.")
    return redirect("checkin:print_agents")


@staff_required
@require_POST
def print_agent_delete(request, agent_id):
    agent = get_object_or_404(PrintAgent, pk=agent_id)
    name = agent.name
    agent.delete()
    messages.success(request, f"Removed '{name}'.")
    return redirect("checkin:print_agents")


@staff_required
@require_POST
def print_agent_test(request, agent_id):
    agent = get_object_or_404(PrintAgent, pk=agent_id)
    if not agent.is_paired:
        messages.error(request, "Pair the agent before sending a test print.")
    else:
        enqueue_test_label(agent)
        messages.success(request, f"Test label queued for '{agent.name}'.")
    return redirect("checkin:print_agents")

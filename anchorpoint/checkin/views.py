import json
import logging
import re
from pathlib import Path
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from core.models import OrganizationSettings
from core.permissions import (
    checkin_admin_required, checkin_team_required, is_staff_or_above, staff_required,
)
from groups.models import GroupMembership
from households.models import Household, HouseholdMember
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
from .services.eligibility import get_eligible_members, is_person_eligible, match_room
from .services.session_manager import get_or_create_session
from .services.quick_registration import register_new_family
from .services.print_queue import enqueue_checkin_labels, enqueue_test_label, get_active_agent

logger = logging.getLogger(__name__)


KIOSK_SESSION_KEY = "kiosk_authenticated"
KIOSK_SESSION_ID_KEY = "kiosk_session_id"
KIOSK_AGENT_ID_KEY = "kiosk_agent_id"  # this device's bound printer (optional)


# =============================================================================
# KIOSK HELPER FUNCTIONS
# =============================================================================


def _ensure_kiosk(request):
    """Redirect to unlock if kiosk not authenticated."""
    if not request.session.get(KIOSK_SESSION_KEY):
        return redirect("checkin:kiosk_unlock")
    return None


def _kiosk_agent(request):
    """The print agent bound to this kiosk device (active + paired), or None to
    fall back to the most-recently-active agent."""
    agent_id = request.session.get(KIOSK_AGENT_ID_KEY)
    if not agent_id:
        return None
    return (
        PrintAgent.objects.filter(pk=agent_id, is_active=True)
        .exclude(token_hash="").first()
    )


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
    pin_set = bool((org.kiosk_pin or "").strip())
    # SECURITY: with no PIN configured the kiosk would be wide open to any
    # passer-by (family lookup, rosters, self-check-in). Refuse to unlock for
    # the public until a PIN is set; let signed-in staff bootstrap/test.
    if not pin_set and not is_staff_or_above(request.user):
        return render(request, "checkin/kiosk/unlock.html", {"org": org, "needs_pin": True})
    if request.method == "POST":
        if not pin_set:
            request.session[KIOSK_SESSION_KEY] = True  # staff bootstrap, no PIN yet
            return redirect("checkin:kiosk_lookup")
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
            # Prefetch members — the results template lists each household's
            # members, which would otherwise be one query per result (N+1) on the
            # busiest public path (every parent searching at the kiosk).
            households = list(
                matches.prefetch_related("members").order_by("name")[: MAX_RESULTS + 1]
            )
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
        "kiosk_agent": _kiosk_agent(request),
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

    # Pre-staged check-ins for this family (label printed ahead, not yet here).
    prestaged = {
        c.person_id: c
        for c in session.checkins.filter(
            person__households=household,
            arrived_at__isnull=True,
            checked_out_at__isnull=True,
        ).select_related("room")
    }
    prestaged_ids = set(prestaged.keys())

    if request.method == "POST":
        form = FamilyMemberSelectForm(
            request.POST,
            members_with_eligibility=members_with_eligibility,
            rooms=rooms,
            prestaged_ids=prestaged_ids,
        )
        if form.is_valid():
            selected = form.get_selected()
            if not selected:
                form.add_error(None, "Please select at least one person.")
            else:
                # One code per family: reuse the pre-printed code if this
                # household already has one, so walk-in siblings share it.
                security_code = _family_code(session, household)
                checkin_ids = []
                to_print_ids = []  # only walk-ins / re-prints; pre-staged already printed
                for person_id, room_id in selected:
                    person = Person.objects.get(pk=person_id)
                    room = Room.objects.get(pk=room_id) if room_id else None
                    checkin = CheckIn.objects.filter(
                        session=session,
                        person=person,
                        checked_out_at__isnull=True,
                    ).first()
                    if checkin:
                        was_expected = checkin.arrived_at is None
                        if checkin.arrived_at is None:
                            checkin.arrived_at = timezone.now()
                        # A pre-staged no-show who actually shows up is here now —
                        # clear no_show so they count as present, not absent.
                        checkin.no_show = False
                        # Keep a pre-staged member's pre-assigned room; only a
                        # walk-in/re-print submits a room to apply.
                        if room is not None:
                            checkin.room = room
                        checkin.security_code = security_code
                        checkin.save(update_fields=["room", "security_code", "arrived_at", "no_show"])
                        # A pre-staged arrival is already printed — don't reprint.
                        if not was_expected:
                            to_print_ids.append(checkin.pk)
                    else:
                        try:
                            with transaction.atomic():
                                checkin = CheckIn.objects.create(
                                    session=session,
                                    person=person,
                                    room=room,
                                    security_code=security_code,
                                    arrived_at=timezone.now(),
                                )
                            to_print_ids.append(checkin.pk)
                        except IntegrityError:
                            # Raced a concurrent check-in for the same person — use
                            # the row that won, don't double-create or double-print.
                            checkin = CheckIn.objects.filter(
                                session=session, person=person,
                                checked_out_at__isnull=True,
                            ).first()
                            if checkin is None:
                                raise
                    checkin_ids.append(checkin.pk)

                # Auto-enroll: add everyone who checked in to the config's group
                # (e.g. VBS walk-ins land on the next day's pre-print roster).
                enroll_group = (
                    session.configuration.auto_enroll_group
                    if session.configuration else None
                )
                if enroll_group:
                    for person_id, _room_id in selected:
                        GroupMembership.objects.get_or_create(
                            group=enroll_group, person_id=person_id
                        )

                request.session["kiosk_checkin_ids"] = checkin_ids
                request.session["kiosk_security_code"] = security_code
                # Queue labels only for walk-ins / re-prints. No-op if no agent
                # is paired; never block check-in on a printing problem.
                queued = 0
                try:
                    ordered = sorted(
                        CheckIn.objects.filter(pk__in=to_print_ids)
                        .select_related("person", "room"),
                        key=lambda c: to_print_ids.index(c.pk),
                    )
                    if ordered:
                        queued = enqueue_checkin_labels(
                            ordered, session, agent=_kiosk_agent(request)
                        )
                except Exception:
                    logger.exception("Failed to queue print jobs for check-in")
                # Suppress the confirmation page's browser-print fallback when
                # labels were queued to the agent OR were already pre-printed
                # (pure arrival: nothing new to print).
                prestaged_arrivals = len(checkin_ids) - len(to_print_ids)
                request.session["kiosk_labels_queued"] = queued > 0 or prestaged_arrivals > 0

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
            prestaged_ids=prestaged_ids,
        )

    # (person, eligible, prestaged_checkin_or_None, routed_room_id) for the
    # template. routed_room_id pre-selects the room matching the child's
    # age/grade band (volunteer can still tap a different one).
    members_display = []
    for person, eligible in members_with_eligibility:
        routed = None
        if eligible and person.pk not in prestaged_ids:
            m = match_room(person, rooms)
            routed = m.pk if m else None
        members_display.append((person, eligible, prestaged.get(person.pk), routed))

    return render(request, "checkin/kiosk/family_select.html", {
        "household": household,
        "form": form,
        "members_with_eligibility": members_with_eligibility,
        "members_display": members_display,
        "rooms": rooms,
        "session": session,
        "config": config,
        "grade_choices": Person.GRADE_CHOICES,
    })


def _household_surname(household):
    """Best surname for a child being added to this family — the primary adult's,
    else the first adult member's, else the household name minus Family/Household."""
    adult = household.primary_adult
    if not (adult and adult.last_name):
        membership = (
            household.memberships.filter(
                relationship_type=HouseholdMember.RelationshipType.ADULT
            )
            .select_related("person")
            .first()
        )
        adult = membership.person if membership else None
    if adult and adult.last_name:
        return adult.last_name
    name = (household.name or "").replace("Family", "").replace("Household", "").strip()
    return name or "Guest"


@require_POST
def kiosk_family_add_child(request, household_id):
    """Add a not-yet-registered child to an EXISTING family at the kiosk — a
    walk-in who showed up with friends. Creates/links the child and enrolls them
    in the session config's group(s) so they appear eligible on the family
    screen, then returns there to be checked in."""
    redir = _ensure_kiosk(request)
    if redir:
        return redir
    session = _get_active_session(request)
    if not session:
        return redirect("checkin:kiosk_lookup")
    household = get_object_or_404(Household, pk=household_id)

    first = (request.POST.get("first_name") or "").strip()
    if not first:
        return redirect("checkin:kiosk_family_select", household_id=household.pk)
    last = (request.POST.get("last_name") or "").strip() or _household_surname(household)
    grade = (request.POST.get("grade") or "").strip()
    if grade not in {g for g, _ in Person.GRADE_CHOICES}:
        grade = ""
    # Birthdate is optional; <input type="date"> posts ISO (YYYY-MM-DD).
    birthdate = parse_date((request.POST.get("birthdate") or "").strip())

    # Reuse an existing same-name member instead of duplicating; else create.
    child = household.members.filter(
        first_name__iexact=first, last_name__iexact=last
    ).first()
    if child is None:
        child = Person.objects.create(
            first_name=first, last_name=last, grade=grade or None,
            birthdate=birthdate,
            allergies=(request.POST.get("allergies") or "").strip(),
            photo_consent="granted" if request.POST.get("photo_consent") else "unknown",
        )
        HouseholdMember.objects.get_or_create(
            household=household, person=child,
            defaults={"relationship_type": HouseholdMember.RelationshipType.CHILD},
        )

    # Enroll so the child is eligible on the family screen (and on the roster).
    config = session.configuration
    if config:
        for group in config.groups.all():
            GroupMembership.objects.get_or_create(group=group, person=child)
        if config.auto_enroll_group_id:
            GroupMembership.objects.get_or_create(
                group=config.auto_enroll_group, person=child
            )

    return redirect("checkin:kiosk_family_select", household_id=household.pk)


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
                    "grade": cf.cleaned_data.get("grade") or None,
                    "allergies": cf.cleaned_data.get("allergies", ""),
                    "custody_flag": cf.cleaned_data.get("custody_flag", False),
                    "custody_notes": cf.cleaned_data.get("custody_notes", ""),
                    "unauthorized_pickup": cf.cleaned_data.get("unauthorized_pickup", ""),
                    "photo_consent": "granted" if cf.cleaned_data.get("photo_consent") else "unknown",
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
        "grade_choices": Person.GRADE_CHOICES,
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


def kiosk_printer(request):
    """Bind this kiosk device to a specific printer (or Automatic). The choice
    lives in the device's session, so two stations can each print to their own."""
    redir = _ensure_kiosk(request)
    if redir:
        return redir
    agents = (
        PrintAgent.objects.filter(is_active=True).exclude(token_hash="").order_by("name")
    )
    if request.method == "POST":
        choice = request.POST.get("agent_id", "")
        if choice == "":
            request.session.pop(KIOSK_AGENT_ID_KEY, None)  # back to Automatic
        elif choice.isdigit() and agents.filter(pk=choice).exists():
            request.session[KIOSK_AGENT_ID_KEY] = int(choice)
        return redirect("checkin:kiosk_lookup")
    return render(request, "checkin/kiosk/printer.html", {
        "agents": agents,
        "current": request.session.get(KIOSK_AGENT_ID_KEY),
        "org": OrganizationSettings.load(),
    })


def kiosk_lock(request):
    request.session.pop(KIOSK_SESSION_KEY, None)
    request.session.pop(KIOSK_SESSION_ID_KEY, None)
    request.session.pop(KIOSK_AGENT_ID_KEY, None)
    # Also drop any staff login, so a shared tablet can never be left both
    # PIN-unlocked and authenticated into the full app.
    if request.user.is_authenticated:
        logout(request)
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
        # Throttle wrong-code guessing: security codes are short (4 chars), so
        # cap failed attempts per session+user before allowing more.
        fail_key = f"checkout-fail:{session_id}:{request.user.id}"
        if cache.get(fail_key, 0) >= 10:
            form.add_error("security_code", "Too many incorrect codes. Please wait a few minutes and try again.")
        elif form.is_valid():
            code = form.cleaned_data["security_code"]
            # Only people who actually arrived can be checked out — a pre-staged
            # (printed-but-not-arrived) record must not be checkout-able.
            checkins = CheckIn.objects.filter(
                session=session,
                security_code=code,
                arrived_at__isnull=False,
                checked_out_at__isnull=True,
            ).select_related("person", "room")

            if not checkins.exists():
                cache.set(fail_key, cache.get(fail_key, 0) + 1, 300)  # 10 fails / 5 min
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
        arrived_at__isnull=False,
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
        # "Check-ins" = people who actually arrived. Excludes no-shows and
        # pre-staged "expected" rows that never arrived (both have arrived_at NULL).
        .annotate(
            attended_count=Count(
                "checkins", filter=Q(checkins__arrived_at__isnull=False)
            )
        )
        .order_by("-date", "-checkin_opens")
    )

    return render(
        request,
        "checkin/session_list.html",
        {
            "sessions": sessions,
        },
    )


def _person_household(person):
    """The household to group a person under for pre-print (deterministic)."""
    return person.primary_household


def _family_code(session, household):
    """Reuse an active code already assigned to this household's members in the
    session, so a family keeps ONE pickup code; else mint a fresh unique one."""
    if household is not None:
        existing = (
            session.checkins.filter(
                person__households=household, checked_out_at__isnull=True
            )
            .exclude(security_code="")
            .first()
        )
        if existing:
            return existing.security_code
    return generate_unique_security_code(session)


@checkin_admin_required
def session_preprint(request, session_id):
    """Pre-print labels and pre-assign rooms before an event.

    Creates pre-staged check-ins (arrived_at=None) and queues their labels, so
    at the door arrival is a single tap on the kiosk (no reprint).
    """
    session = get_object_or_404(CheckInSession, pk=session_id)
    config = session.configuration
    rooms = list(session.rooms.all())

    # Candidate pool: people eligible for this session's configuration.
    if config and config.groups.exists():
        candidate_qs = Person.objects.filter(
            group_memberships__group__in=config.groups.all()
        ).distinct()
    else:
        candidate_qs = Person.objects.all()
    candidate_qs = candidate_qs.prefetch_related(
        "group_memberships", "households"
    ).order_by("last_name", "first_name")

    if config:
        config_group_ids = set(config.groups.values_list("id", flat=True))
        candidates = [
            p for p in candidate_qs if is_person_eligible(p, config, config_group_ids)
        ]
    else:
        candidates = list(candidate_qs)

    existing = {c.person_id: c for c in session.checkins.select_related("room").all()}

    if request.method == "POST":
        created, reprinted, fam_count = _preprint_generate(
            request, session, candidates, existing, rooms
        )
        total = created + reprinted
        if total:
            messages.success(
                request,
                f"Queued {total} label(s) across {fam_count} "
                f"famil{'y' if fam_count == 1 else 'ies'} "
                f"({created} new, {reprinted} reprinted).",
            )
        else:
            messages.info(request, "Select at least one person to print.")
        return redirect("checkin:session_preprint", session_id=session.pk)

    # Build household-grouped rows for display.
    groups = {}
    for person in candidates:
        household = _person_household(person)
        key = household.pk if household else f"solo-{person.pk}"
        label = household.name if household else f"{person.first_name} {person.last_name} (no family)"
        groups.setdefault(key, {
            "label": label,
            "household_id": household.pk if household else None,
            "rows": [],
            "has_staged": False,
        })
        c = existing.get(person.pk)
        if c and c.checked_out_at is None:
            status = "expected" if c.arrived_at is None else "present"
        elif c:
            status = "checked_out"
        else:
            status = None
        if status in ("expected", "present"):
            groups[key]["has_staged"] = True
        routed = match_room(person, rooms) if status is None else None
        groups[key]["rows"].append({
            "person": person,
            "existing": c,
            "status": status,
            "assigned_room": c.room if c else None,
            "routed_room_id": routed.pk if routed else None,
        })

    return render(request, "checkin/session_preprint.html", {
        "session": session,
        "rooms": rooms,
        "groups": sorted(groups.values(), key=lambda g: g["label"].lower()),
        "stats": _session_stats(session),
    })


def _preprint_generate(request, session, candidates, existing, rooms=None):
    """Queue labels for the selected people: pre-stage + print those not yet
    staged, and re-queue (reprint) the label for any selected person who is
    already staged/present. Grouped by household so a family keeps one pickup
    code. Returns (created, reprinted, households_touched). Rooms not chosen in
    the form fall back to the child's age/grade-matched room."""
    from collections import defaultdict

    rooms = rooms if rooms is not None else list(session.rooms.all())

    buckets = defaultdict(lambda: {"new": [], "reprint": []})
    for person in candidates:
        if not request.POST.get(f"select_{person.pk}"):
            continue
        household = _person_household(person)
        key = household.pk if household else f"solo-{person.pk}"
        current = existing.get(person.pk)
        if current and current.checked_out_at is None:
            buckets[key]["reprint"].append(current)  # already staged → reprint
        else:
            room_id = request.POST.get(f"room_{person.pk}") or None
            buckets[key]["new"].append((person, household, room_id))

    created = reprinted = fam_count = 0
    for _, bucket in buckets.items():
        if bucket["new"]:
            household = bucket["new"][0][1]
        else:
            household = _person_household(bucket["reprint"][0].person)
        code = _family_code(session, household)
        labels = []
        for person, _hh, room_id in bucket["new"]:
            room = Room.objects.filter(pk=room_id).first() if room_id else None
            if room is None:
                room = match_room(person, rooms)  # auto-route by age/grade
            checkin = CheckIn.objects.create(
                session=session, person=person, room=room,
                security_code=code, arrived_at=None,
            )
            labels.append(checkin)
            created += 1
        for checkin in bucket["reprint"]:
            labels.append(checkin)
            reprinted += 1
        if labels:
            fam_count += 1
            try:
                enqueue_checkin_labels(labels, session)
            except Exception:
                logger.exception("Failed to queue pre-print labels")
    return created, reprinted, fam_count


@checkin_admin_required
@require_POST
def session_preprint_reprint(request, session_id, household_id):
    """Re-queue labels for one household's pre-staged (still-here) check-ins."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    checkins = list(
        session.checkins.filter(
            person__households__pk=household_id, checked_out_at__isnull=True
        )
        .select_related("person", "room")
        .distinct()
    )
    if checkins:
        try:
            enqueue_checkin_labels(checkins, session)
            messages.success(request, f"Re-queued {len(checkins)} label(s).")
        except Exception:
            logger.exception("Failed to re-queue pre-print labels")
            messages.error(request, "Could not queue labels — check the print agent.")
    else:
        messages.info(request, "No active pre-staged check-ins for that family.")
    return redirect("checkin:session_preprint", session_id=session.pk)


def _matching_window(config, date):
    """The active schedule window a session on `date` belongs to. Linking it
    means a manually-created session is the SAME (config, window, date) the
    kiosk auto-opens via get_or_create_session — preventing a windowless twin
    session for the day."""
    if not config:
        return None
    sunday_dow = (date.weekday() + 1) % 7  # window day_of_week is Sunday-first
    for w in config.windows.filter(is_active=True):
        if w.schedule_type == CheckInWindow.TYPE_SPECIFIC_DATE:
            if w.specific_date == date:
                return w
        elif w.day_of_week == sunday_dow:
            return w
    return None


@staff_required
def session_create(request):
    """Create a new check-in session."""
    if request.method == "POST":
        form = CheckInSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            # Link the day's schedule window (and reuse an existing one) so this
            # session and the kiosk's auto-opened session are one and the same.
            window = _matching_window(session.configuration, session.date)
            if window:
                existing = CheckInSession.objects.filter(
                    configuration=session.configuration, window=window, date=session.date
                ).first()
                if existing:
                    messages.info(
                        request, "A session for that day already exists — opening it."
                    )
                    return redirect("checkin:session_detail", session_id=existing.pk)
                session.window = window
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
    """Live counts for a session: totals plus per-room occupancy.

    "Present" = arrived and not checked out. "Expected" = pre-staged (label
    printed ahead, not arrived yet). Room occupancy counts present people only.
    """
    present_q = session.checkins.filter(
        arrived_at__isnull=False, checked_out_at__isnull=True
    )
    checked_in = present_q.count()
    checked_out = session.checkins.filter(checked_out_at__isnull=False).count()
    expected = session.checkins.filter(
        arrived_at__isnull=True, checked_out_at__isnull=True, no_show=False
    ).count()
    no_show = session.checkins.filter(
        arrived_at__isnull=True, checked_out_at__isnull=True, no_show=True
    ).count()

    room_counts = {
        row["room"]: row["count"]
        for row in present_q.values("room").annotate(count=Count("id"))
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
        "expected": expected,
        "no_show": no_show,
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


def _present_checkins(session):
    """Children currently present (arrived, not checked out), room then name."""
    return (
        session.checkins
        .filter(arrived_at__isnull=False, checked_out_at__isnull=True)
        .select_related("person", "room")
        .order_by("room__sort_order", "person__last_name", "person__first_name")
    )


def _expected_checkins(session):
    """Pre-staged kids who haven't arrived and aren't yet marked no-show."""
    return (
        session.checkins
        .filter(arrived_at__isnull=True, checked_out_at__isnull=True, no_show=False)
        .select_related("person")
        .order_by("person__last_name", "person__first_name")
    )


def _manager_context(session):
    return {
        "session": session,
        "stats": _session_stats(session),
        "present": _present_checkins(session),
        "expected": _expected_checkins(session),
        "agent": get_active_agent(),
    }


@checkin_team_required
def checkin_manager(request, session_id):
    """Live check-in manager for volunteers: who's currently checked in (name +
    grade + room), with per-child reprint and a link to each child's detail."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    return render(request, "checkin/manager.html", _manager_context(session))


@checkin_team_required
def checkin_manager_roster(request, session_id):
    """HTMX partial: present-roster + counts, polled live by the manager page."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    return render(request, "checkin/_manager_roster.html", _manager_context(session))


@checkin_team_required
@require_POST
def checkin_mark_noshow(request, session_id, checkin_id):
    """Mark one pre-staged (not-arrived) check-in as a no-show."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    checkin = get_object_or_404(
        session.checkins.select_related("person"),
        pk=checkin_id, arrived_at__isnull=True, checked_out_at__isnull=True,
    )
    checkin.no_show = True
    checkin.save(update_fields=["no_show"])
    messages.success(request, f"{checkin.person.first_name} marked as a no-show.")
    return redirect("checkin:checkin_manager", session_id=session_id)


@checkin_team_required
@require_POST
def checkin_clear_expected(request, session_id):
    """End-of-session cleanup: mark every still-expected child as a no-show."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    n = session.checkins.filter(
        arrived_at__isnull=True, checked_out_at__isnull=True, no_show=False
    ).update(no_show=True)
    messages.success(request, f"Marked {n} remaining expected child{'ren' if n != 1 else ''} as no-shows.")
    return redirect("checkin:checkin_manager", session_id=session_id)


@checkin_team_required
@require_POST
def checkin_bulk_action(request, session_id):
    """Bulk-update the check-ins selected via the roster checkboxes: either mark
    them arrived (confirmed present) or as no-shows. Scoped to the session and to
    not-checked-out kids, so a stale roster can't corrupt anyone."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    action = request.POST.get("action")
    ids = request.POST.getlist("checkin_ids")
    if not ids:
        messages.info(request, "No children selected.")
        return redirect("checkin:checkin_manager", session_id=session_id)

    selected = session.checkins.filter(pk__in=ids, checked_out_at__isnull=True)
    if action == "arrive":
        # Confirm attendance: stamp arrival on those not yet arrived and clear any
        # no-show flag (also flips a mistaken no-show back to present).
        n = selected.filter(arrived_at__isnull=True).update(
            arrived_at=timezone.now(), no_show=False
        )
        selected.filter(arrived_at__isnull=False, no_show=True).update(no_show=False)
        messages.success(request, f"Marked {n} child{'ren' if n != 1 else ''} as arrived.")
    elif action == "noshow":
        # Only not-yet-arrived kids can be no-shows (never undo a real arrival).
        n = selected.filter(arrived_at__isnull=True).update(no_show=True)
        messages.success(request, f"Marked {n} child{'ren' if n != 1 else ''} as a no-show.")
    else:
        messages.error(request, "Unknown action.")
    return redirect("checkin:checkin_manager", session_id=session_id)


@checkin_team_required
@require_POST
def checkin_reprint(request, session_id, checkin_id):
    """Re-queue a single child's label (+ pickup tag) to the active print agent."""
    session = get_object_or_404(CheckInSession, pk=session_id)
    checkin = get_object_or_404(
        session.checkins.select_related("person"), pk=checkin_id
    )
    if enqueue_checkin_labels([checkin], session):
        messages.success(request, f"Reprinting {checkin.person.first_name}'s label.")
    else:
        messages.error(request, "No print agent is online — can't reprint right now.")
    return redirect("checkin:checkin_manager", session_id=session_id)


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
def print_agent_update(request, agent_id):
    agent = get_object_or_404(PrintAgent, pk=agent_id)
    try:
        width = int(request.POST.get("label_width_mm", ""))
    except (TypeError, ValueError):
        messages.error(request, "Label width must be a number of millimetres.")
        return redirect("checkin:print_agents")
    if not 20 <= width <= 120:
        messages.error(request, "Label width must be between 20 and 120 mm.")
        return redirect("checkin:print_agents")
    try:
        rotation = int(request.POST.get("label_rotation", agent.label_rotation))
    except (TypeError, ValueError):
        rotation = agent.label_rotation
    if rotation not in dict(PrintAgent.ROTATION_CHOICES):
        rotation = 0
    agent.label_width_mm = width
    agent.label_rotation = rotation
    agent.save(update_fields=["label_width_mm", "label_rotation"])
    messages.success(
        request,
        f"'{agent.name}' set to {width}mm labels"
        + (f", rotated {rotation}°." if rotation else "."),
    )
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


def _serve_agent_file(filename, content_type="text/plain"):
    """Serve a file from the repo's agent/ directory (installer + agent script).

    Public on purpose: these contain no secrets — pairing codes are the secret
    and are typed in by the person running the installer.
    """
    from django.conf import settings as django_settings
    from django.http import Http404

    path = Path(django_settings.BASE_DIR).parent / "agent" / filename
    try:
        content = path.read_text()
    except OSError:
        raise Http404(filename)
    return HttpResponse(content, content_type=content_type)


def agent_install_script(request):
    """`curl -fsSL https://<host>/checkin/agent/install.sh | sudo bash -s -- ...`"""
    return _serve_agent_file("install.sh", "text/x-shellscript")


def agent_script(request):
    """The print agent itself; downloaded by install.sh onto the Pi."""
    return _serve_agent_file("anchorpoint_agent.py", "text/x-python")

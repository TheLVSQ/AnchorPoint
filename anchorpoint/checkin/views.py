import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q

from people.models import Person
from people.utils import normalize_phone
from households.models import HouseholdMembership
from core.permissions import staff_required

from .models import (
    Room,
    CheckInSession,
    CheckIn,
    PrinterConfiguration,
    generate_security_code,
)
from .forms import (
    PhoneLookupForm,
    CheckInSessionForm,
    RoomForm,
    PrinterConfigForm,
    SecurityCodeLookupForm,
)
from .services import PrintService


# =============================================================================
# KIOSK VIEWS (Public-facing, no login required)
# =============================================================================


def kiosk_home(request):
    """Kiosk home screen - entry point for check-in."""
    # Get active sessions
    today = timezone.localdate()
    sessions = CheckInSession.objects.filter(
        date=today,
        is_active=True,
    ).order_by("start_time")

    return render(
        request,
        "checkin/kiosk/home.html",
        {
            "sessions": sessions,
        },
    )


def kiosk_lookup(request, session_id):
    """Phone number lookup screen."""
    session = get_object_or_404(CheckInSession, pk=session_id, is_active=True)

    if request.method == "POST":
        form = PhoneLookupForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data["phone"]
            normalized = normalize_phone(phone)

            # Find people by phone number
            people = Person.objects.filter(
                Q(normalized_phone=normalized) | Q(phone__icontains=phone[-7:])
            ).distinct()

            if people.exists():
                # Also get household members
                person_ids = set(people.values_list("id", flat=True))

                # Find all people in the same households
                for person in people:
                    memberships = HouseholdMembership.objects.filter(person=person)
                    for membership in memberships:
                        household_members = HouseholdMembership.objects.filter(
                            household=membership.household
                        ).values_list("person_id", flat=True)
                        person_ids.update(household_members)

                # Store in session for next step
                request.session["checkin_person_ids"] = list(person_ids)
                request.session["checkin_session_id"] = session_id

                return redirect("checkin:kiosk_select", session_id=session_id)
            else:
                form.add_error("phone", "No family found with this phone number.")
    else:
        form = PhoneLookupForm()

    return render(
        request,
        "checkin/kiosk/lookup.html",
        {
            "session": session,
            "form": form,
        },
    )


def kiosk_select(request, session_id):
    """Select family members to check in."""
    session = get_object_or_404(CheckInSession, pk=session_id, is_active=True)

    person_ids = request.session.get("checkin_person_ids", [])
    if not person_ids:
        return redirect("checkin:kiosk_lookup", session_id=session_id)

    people = Person.objects.filter(id__in=person_ids).order_by("birthdate")

    # Check who's already checked in
    already_checked_in = CheckIn.objects.filter(
        session=session, person_id__in=person_ids
    ).values_list("person_id", flat=True)

    if request.method == "POST":
        selected_ids = request.POST.getlist("person_ids")
        if selected_ids:
            request.session["checkin_selected_ids"] = selected_ids
            return redirect("checkin:kiosk_rooms", session_id=session_id)

    return render(
        request,
        "checkin/kiosk/select.html",
        {
            "session": session,
            "people": people,
            "already_checked_in": list(already_checked_in),
        },
    )


def kiosk_rooms(request, session_id):
    """Select rooms for each person."""
    session = get_object_or_404(CheckInSession, pk=session_id, is_active=True)

    selected_ids = request.session.get("checkin_selected_ids", [])
    if not selected_ids:
        return redirect("checkin:kiosk_select", session_id=session_id)

    people = Person.objects.filter(id__in=selected_ids)
    rooms = session.rooms.filter(is_active=True).order_by("sort_order", "name")

    # Auto-assign rooms based on age/grade
    auto_assignments = {}
    for person in people:
        age = person.age
        grade = person.grade

        for room in rooms:
            # Check age range
            if room.min_age and age and age < room.min_age:
                continue
            if room.max_age and age and age > room.max_age:
                continue

            # Check grade range (simplified - could be enhanced)
            if room.min_grade and grade and grade < room.min_grade:
                continue
            if room.max_grade and grade and grade > room.max_grade:
                continue

            # This room is a match
            auto_assignments[person.id] = room.id
            break

    if request.method == "POST":
        # Process room assignments and create check-ins
        room_assignments = {}
        for person in people:
            room_id = request.POST.get(f"room_{person.id}")
            if room_id:
                room_assignments[person.id] = int(room_id)

        # Generate a single security code for the family
        security_code = generate_security_code()

        # Create check-ins
        checkins = []
        for person in people:
            room_id = room_assignments.get(person.id)
            room = Room.objects.get(pk=room_id) if room_id else None

            checkin = CheckIn.objects.create(
                session=session,
                person=person,
                room=room,
                security_code=security_code,
                notes=person.allergies or "",
            )
            checkins.append(checkin)

        # Store for confirmation screen
        request.session["checkin_completed_ids"] = [c.id for c in checkins]
        request.session["checkin_security_code"] = security_code

        return redirect("checkin:kiosk_complete", session_id=session_id)

    return render(
        request,
        "checkin/kiosk/rooms.html",
        {
            "session": session,
            "people": people,
            "rooms": rooms,
            "auto_assignments": auto_assignments,
        },
    )


def kiosk_complete(request, session_id):
    """Check-in complete - show security code and print labels."""
    session = get_object_or_404(CheckInSession, pk=session_id)

    checkin_ids = request.session.get("checkin_completed_ids", [])
    security_code = request.session.get("checkin_security_code", "")

    if not checkin_ids:
        return redirect("checkin:kiosk_home")

    checkins = CheckIn.objects.filter(id__in=checkin_ids).select_related(
        "person", "room"
    )

    # Attempt to print labels
    print_success = False
    try:
        print_service = PrintService()
        if print_service.is_printer_available():
            results = print_service.print_checkin_labels(list(checkins))
            print_success = all(results["child"]) and results["parent"]
    except Exception:
        pass  # Printing is optional

    # Clear session data
    for key in ["checkin_person_ids", "checkin_selected_ids", "checkin_completed_ids", "checkin_security_code"]:
        request.session.pop(key, None)

    return render(
        request,
        "checkin/kiosk/complete.html",
        {
            "session": session,
            "checkins": checkins,
            "security_code": security_code,
            "print_success": print_success,
        },
    )


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
# ADMIN/DASHBOARD VIEWS (Staff-facing)
# =============================================================================


@staff_required
def dashboard(request):
    """Check-in dashboard showing current sessions."""
    today = timezone.localdate()
    sessions = CheckInSession.objects.filter(date=today).order_by("start_time")

    return render(
        request,
        "checkin/dashboard.html",
        {
            "sessions": sessions,
            "today": today,
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
        },
    )


@staff_required
def session_list(request):
    """List all check-in sessions."""
    sessions = CheckInSession.objects.all().order_by("-date", "-start_time")

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


def api_session_stats(request, session_id):
    """Get real-time stats for a session (AJAX)."""
    session = get_object_or_404(CheckInSession, pk=session_id)

    checked_in = session.checkins.filter(checked_out_at__isnull=True).count()
    checked_out = session.checkins.filter(checked_out_at__isnull=False).count()

    # Room breakdown
    rooms = []
    for room in session.rooms.all():
        count = session.checkins.filter(room=room, checked_out_at__isnull=True).count()
        rooms.append({
            "name": room.name,
            "count": count,
            "capacity": room.capacity,
        })

    return JsonResponse({
        "checked_in": checked_in,
        "checked_out": checked_out,
        "total": checked_in + checked_out,
        "rooms": rooms,
    })

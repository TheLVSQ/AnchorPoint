from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Min
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.utils import timezone

import csv
import io
from people.models import Person

from .forms import (
    EventForm,
    EventOccurrenceFormSet,
    EventPhotoFormSet,
    EventRegistrationAttendeeFormSet,
    EventRegistrationContactForm,
    RegistrationMatchForm,
)
from .models import Event, EventRegistration, EventRegistrationAttendee
from .services import (
    create_person_from_attendee,
    ensure_event_group,
    link_guardian_household,
    manually_assign_attendee,
    match_registration_attendees,
)


def _has_valid_occurrence(formset):
    for subform in formset.forms:
        cleaned = getattr(subform, "cleaned_data", None)
        if not cleaned:
            continue
        if cleaned.get("DELETE"):
            continue
        if cleaned.get("starts_at"):
            return True
    return False


@login_required
def event_manage_list(request):
    events = (
        Event.objects.prefetch_related("occurrences", "registrations")
        .order_by("title")
    )
    upcoming_events = (
        Event.objects.upcoming()
        .annotate(next_start=Min("occurrences__starts_at"))
        .order_by("next_start")[:5]
    )
    recent_registrations = (
        EventRegistration.objects.select_related("event")
        .order_by("-created_at")[:5]
    )
    pending_match_count = 0
    show_match_queue = request.user.has_perm(
        "events.change_eventregistrationattendee"
    )
    if show_match_queue:
        pending_match_count = EventRegistrationAttendee.objects.filter(
            match_status=EventRegistrationAttendee.MATCH_STATUS_PENDING
        ).count()
    context = {
        "events": events,
        "upcoming_events": upcoming_events,
        "recent_registrations": recent_registrations,
        "show_match_queue": show_match_queue,
        "pending_match_count": pending_match_count,
    }
    return render(request, "events/manage/event_list.html", context)


@login_required
@transaction.atomic
def event_create(request):
    event = Event(created_by=request.user)
    if request.method == "POST":
        form = EventForm(request.POST, request.FILES, instance=event)
        occurrence_formset = EventOccurrenceFormSet(
            request.POST, prefix="occurrence", instance=event
        )
        photo_formset = EventPhotoFormSet(
            request.POST, request.FILES, prefix="photo", instance=event
        )
        form_valid = form.is_valid()
        occurrence_valid = occurrence_formset.is_valid()
        photo_valid = photo_formset.is_valid()
        if occurrence_valid and not _has_valid_occurrence(occurrence_formset):
            occurrence_valid = False
            occurrence_formset._non_form_errors = occurrence_formset.error_class(
                ["Add at least one schedule entry."]
            )
        if form_valid and occurrence_valid and photo_valid:
            event = form.save()
            occurrence_formset.instance = event
            photo_formset.instance = event
            occurrence_formset.save()
            photo_formset.save()
            messages.success(request, "Event created successfully.")
            return redirect("events:manage_list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = EventForm(instance=event)
        occurrence_formset = EventOccurrenceFormSet(
            prefix="occurrence", instance=event
        )
        photo_formset = EventPhotoFormSet(prefix="photo", instance=event)

    context = {
        "form": form,
        "occurrence_formset": occurrence_formset,
        "photo_formset": photo_formset,
        "event": None,
    }
    return render(request, "events/manage/event_form.html", context)


@login_required
@transaction.atomic
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if request.method == "POST":
        form = EventForm(request.POST, request.FILES, instance=event)
        occurrence_formset = EventOccurrenceFormSet(
            request.POST, prefix="occurrence", instance=event
        )
        photo_formset = EventPhotoFormSet(
            request.POST, request.FILES, prefix="photo", instance=event
        )
        form_valid = form.is_valid()
        occurrence_valid = occurrence_formset.is_valid()
        photo_valid = photo_formset.is_valid()
        if occurrence_valid and not _has_valid_occurrence(occurrence_formset):
            occurrence_valid = False
            occurrence_formset._non_form_errors = occurrence_formset.error_class(
                ["Add at least one schedule entry."]
            )
        if form_valid and occurrence_valid and photo_valid:
            form.save()
            occurrence_formset.save()
            photo_formset.save()
            messages.success(request, "Event updated successfully.")
            return redirect("events:manage_list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = EventForm(instance=event)
        occurrence_formset = EventOccurrenceFormSet(
            prefix="occurrence", instance=event
        )
        photo_formset = EventPhotoFormSet(prefix="photo", instance=event)

    context = {
        "form": form,
        "occurrence_formset": occurrence_formset,
        "photo_formset": photo_formset,
        "event": event,
    }
    return render(request, "events/manage/event_form.html", context)


@login_required
def event_registrations(request, pk):
    event = get_object_or_404(
        Event.objects.prefetch_related("registrations"), pk=pk
    )
    registrations = event.registrations.all()
    return render(
        request,
        "events/manage/event_registrations.html",
        {"event": event, "registrations": registrations},
    )


@login_required
def event_roster(request, pk):
    event = get_object_or_404(
        Event.objects.prefetch_related("registration_attendees__person"), pk=pk
    )
    group = ensure_event_group(event)
    attendees = event.registration_attendees.select_related("person").order_by(
        "last_name", "first_name"
    )
    return render(
        request,
        "events/manage/event_roster.html",
        {
            "event": event,
            "attendees": attendees,
            "group": group,
        },
    )


@login_required
def event_roster_export(request, pk):
    event = get_object_or_404(
        Event.objects.prefetch_related("registration_attendees__person"), pk=pk
    )
    attendees = event.registration_attendees.select_related("person").order_by(
        "last_name", "first_name"
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Event",
            "Full Name",
            "Email",
            "Phone",
            "Is Minor",
            "Guardian Name",
            "Guardian Email",
            "Emergency Contact",
            "Liability Signed",
            "Media Signed",
            "Match Status",
            "Matched Person ID",
        ]
    )
    for attendee in attendees:
        writer.writerow(
            [
                event.title,
                attendee.full_name,
                attendee.email or "",
                attendee.phone or "",
                "Yes" if attendee.is_minor else "No",
                attendee.parent_guardian_name or "",
                attendee.parent_guardian_email or "",
                attendee.emergency_contact_name or "",
                "Yes" if attendee.registration.liability_release_accepted_at else "No",
                "Yes" if attendee.registration.media_release_accepted_at else "No",
                attendee.get_match_status_display(),
                attendee.person_id or "",
            ]
        )
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="text/csv",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="event-roster-{event.pk}.csv"'
    )
    return response


def public_event_list(request):
    events = (
        Event.objects.upcoming()
        .annotate(next_start=Min("occurrences__starts_at"))
        .prefetch_related("occurrences", "photos")
        .order_by("next_start")
    )
    featured_event = events.first()
    context = {
        "events": events,
        "featured_event": featured_event,
    }
    return render(request, "events/public/event_list.html", context)


def public_event_detail(request, slug):
    event = get_object_or_404(
        Event.objects.published()
        .prefetch_related("occurrences", "photos"),
        slug=slug,
    )
    upcoming_occurrences = event.upcoming_occurrences()
    return render(
        request,
        "events/public/event_detail.html",
        {
            "event": event,
            "occurrences": upcoming_occurrences,
            "can_register": event.can_register(),
        },
    )


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _find_guardian_person(attendee):
    potential_emails = [
        attendee.parent_guardian_email,
        getattr(attendee.registration, "email", None),
    ]
    for email in potential_emails:
        if email:
            guardian = Person.objects.filter(email__iexact=email).first()
            if guardian:
                return guardian
    return None


@login_required
@permission_required(
    "events.change_eventregistrationattendee", raise_exception=True
)
def event_registration_queue(request):
    attendees = (
        EventRegistrationAttendee.objects.select_related("event", "registration")
        .filter(match_status=EventRegistrationAttendee.MATCH_STATUS_PENDING)
        .order_by("registration__created_at")
    )
    if request.method == "POST":
        attendee = get_object_or_404(
            EventRegistrationAttendee, pk=request.POST.get("attendee_id")
        )
        form = RegistrationMatchForm(attendee, request.POST)
        if form.is_valid():
            action = form.cleaned_data["action"]
            notes = form.cleaned_data.get("notes") or ""
            if action == RegistrationMatchForm.ACTION_ASSIGN:
                person = form.cleaned_data["person"]
                manually_assign_attendee(
                    attendee,
                    person,
                    matched_by=request.user,
                    notes=notes,
                )
                if attendee.is_minor:
                    guardian = _find_guardian_person(attendee)
                    if guardian:
                        link_guardian_household(guardian, person)
                messages.success(
                    request,
                    f"Linked {attendee.full_name} to {person}.",
                )
            elif action == RegistrationMatchForm.ACTION_CREATE:
                person = create_person_from_attendee(attendee)
                manually_assign_attendee(
                    attendee,
                    person,
                    matched_by=request.user,
                    notes=notes,
                )
                if attendee.is_minor:
                    guardian = _find_guardian_person(attendee)
                    if guardian:
                        link_guardian_household(guardian, person)
                messages.success(
                    request,
                    f"Created new person for {attendee.full_name}.",
                )
            else:
                attendee.match_status = (
                    EventRegistrationAttendee.MATCH_STATUS_DISMISSED
                )
                attendee.matched_by = request.user
                attendee.matched_at = timezone.now()
                attendee.match_notes = notes
                attendee.save(
                    update_fields=[
                        "match_status",
                        "matched_by",
                        "matched_at",
                        "match_notes",
                        "updated_at",
                    ]
                )
                messages.info(
                    request,
                    f"Dismissed {attendee.full_name} for now.",
                )
            return redirect("events:registration_queue")
        else:
            messages.error(request, "Please fix the errors below.")

    attendee_forms = [
        (attendee, RegistrationMatchForm(attendee))
        for attendee in attendees
    ]
    return render(
        request,
        "events/manage/registration_queue.html",
        {"attendee_forms": attendee_forms},
    )


@transaction.atomic
def public_event_register(request, registration_token):
    event = get_object_or_404(
        Event.objects.published()
        .prefetch_related("occurrences"),
        registration_token=registration_token,
    )
    liability_doc_url, liability_doc_name = event.liability_release_link()
    media_doc_url, media_doc_name = event.media_release_link()
    submitted = False
    registration_closed = False
    if not event.can_register():
        registration_closed = True
        return render(
            request,
            "events/public/event_register.html",
            {
                "event": event,
                "form": None,
                "submitted": submitted,
                "registration_closed": True,
            },
        )

    form = None
    attendee_formset = None
    if request.method == "POST" and not registration_closed:
        form = EventRegistrationContactForm(request.POST, prefix="contact")
        attendee_formset = EventRegistrationAttendeeFormSet(
            request.POST, prefix="attendee"
        )
        if form.is_valid() and attendee_formset.is_valid():
            registration = form.save(commit=False)
            registration.event = event
            attendee_count = 0
            attendees_to_save = []
            for attendee_form in attendee_formset:
                data = attendee_form.cleaned_data
                if not data:
                    continue
                attendee = attendee_form.save(commit=False)
                attendee_count += 1
                attendees_to_save.append(attendee)
            registration.number_of_attendees = attendee_count
            ip_address = _get_client_ip(request)
            user_agent = request.META.get("HTTP_USER_AGENT", "")
            form.apply_release_metadata(registration, ip_address, user_agent)
            registration.save()
            for attendee in attendees_to_save:
                attendee.registration = registration
                attendee.event = event
                attendee.save()
            match_registration_attendees(registration)
            submitted = True
            form = None
            attendee_formset = None
        else:
            messages.error(
                request,
                "Please fix the errors below before submitting.",
            )
    elif not registration_closed:
        form = EventRegistrationContactForm(prefix="contact")
        attendee_formset = EventRegistrationAttendeeFormSet(prefix="attendee")

    return render(
        request,
        "events/public/event_register.html",
        {
            "event": event,
            "form": form,
            "attendee_formset": attendee_formset,
            "submitted": submitted,
            "registration_closed": registration_closed,
            "liability_doc_url": liability_doc_url,
            "liability_doc_name": liability_doc_name,
            "media_doc_url": media_doc_url,
            "media_doc_name": media_doc_name,
        },
    )

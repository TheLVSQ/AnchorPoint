from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Min
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    EventForm,
    EventOccurrenceFormSet,
    EventPhotoFormSet,
    EventRegistrationForm,
)
from .models import Event, EventRegistration


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
    context = {
        "events": events,
        "upcoming_events": upcoming_events,
        "recent_registrations": recent_registrations,
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


def public_event_register(request, registration_token):
    event = get_object_or_404(
        Event.objects.published()
        .prefetch_related("occurrences"),
        registration_token=registration_token,
    )
    submitted = False
    if not event.can_register():
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

    if request.method == "POST":
        form = EventRegistrationForm(request.POST)
        if form.is_valid():
            registration = form.save(commit=False)
            registration.event = event
            registration.save()
            submitted = True
            form = EventRegistrationForm()
    else:
        form = EventRegistrationForm()

    return render(
        request,
        "events/public/event_register.html",
        {
            "event": event,
            "form": form,
            "submitted": submitted,
            "registration_closed": False,
        },
    )

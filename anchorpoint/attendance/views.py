from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.models import OrganizationSettings
from core.permissions import staff_required
from groups.models import GroupMembership
from households.models import Household, HouseholdMember

from .forms import (
    CheckInConfigurationForm,
    CheckInSelectionForm,
    CheckInWindowFormSet,
    KioskLookupForm,
    KioskPinForm,
)
from .models import AttendanceRecord, CheckInConfiguration, CheckInWindow


KIOSK_SESSION_KEY = "kiosk_authenticated"
KIOSK_CONFIRMATION_KEY = "kiosk_confirmation_records"


@staff_required
def configuration_list(request):
    configurations = (
        CheckInConfiguration.objects.prefetch_related("groups", "windows")
        .order_by("name")
    )
    total_configs = configurations.count()
    active_configs = configurations.filter(is_active=True).count()

    context = {
        "configurations": configurations,
        "total_configs": total_configs,
        "active_configs": active_configs,
    }
    return render(request, "attendance/checkin_config_list.html", context)


def _render_form(request, *, instance, success_message):
    if request.method == "POST":
        form = CheckInConfigurationForm(request.POST, instance=instance)
        formset = CheckInWindowFormSet(request.POST, instance=instance)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                configuration = form.save()
                formset.instance = configuration
                formset.save()
            messages.success(request, success_message)
            return redirect("attendance:configuration_list")
        messages.error(request, "Please review the highlighted errors.")
    else:
        form = CheckInConfigurationForm(instance=instance)
        formset = CheckInWindowFormSet(instance=instance)

    return render(
        request,
        "attendance/checkin_config_form.html",
        {
            "form": form,
            "formset": formset,
            "configuration": instance if instance.pk else None,
        },
    )


@staff_required
def configuration_create(request):
    instance = CheckInConfiguration()
    return _render_form(
        request,
        instance=instance,
        success_message="Check-In configuration created.",
    )


@staff_required
def configuration_edit(request, pk):
    instance = get_object_or_404(CheckInConfiguration, pk=pk)
    return _render_form(
        request,
        instance=instance,
        success_message="Check-In configuration updated.",
    )


def _phone_regex_pattern(digits):
    tokens = [digit + r"[^\d]*" for digit in digits]
    middle = "".join(tokens)
    return rf".*{middle}".rstrip(r"[^\d]*") + r".*"


def _format_phone_display(digits):
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return digits


def _ensure_kiosk_session(request):
    if request.session.get(KIOSK_SESSION_KEY):
        return None
    return redirect("attendance:kiosk_unlock")


def _build_open_checkin_context():
    now = timezone.localtime()
    configs = (
        CheckInConfiguration.objects.filter(is_active=True)
        .prefetch_related("groups", "windows")
        .order_by("name")
    )
    open_windows = []
    window_group_map = {}
    eligible_group_ids = set()

    for configuration in configs:
        groups = list(configuration.groups.all())
        group_ids = [group.id for group in groups]
        for window in configuration.open_windows(now):
            open_windows.append({"configuration": configuration, "window": window})
            window_group_map[window.id] = {
                "configuration": configuration,
                "group_ids": set(group_ids),
            }
            eligible_group_ids.update(group_ids)

    return {
        "open_windows": open_windows,
        "window_group_map": window_group_map,
        "eligible_group_ids": eligible_group_ids,
    }


def kiosk_unlock(request):
    settings_instance = OrganizationSettings.load()
    expected_pin = (settings_instance.kiosk_pin or "").strip()
    if not expected_pin:
        request.session[KIOSK_SESSION_KEY] = True
        return redirect("attendance:kiosk_lookup")

    form = KioskPinForm(request.POST or None, expected_pin=expected_pin)
    if request.method == "POST" and form.is_valid():
        request.session[KIOSK_SESSION_KEY] = True
        return redirect("attendance:kiosk_lookup")

    return render(
        request,
        "attendance/kiosk_unlock.html",
        {"form": form, "settings_instance": settings_instance},
    )


def kiosk_lock(request):
    request.session.pop(KIOSK_SESSION_KEY, None)
    request.session.pop(KIOSK_CONFIRMATION_KEY, None)
    return redirect("attendance:kiosk_unlock")


def kiosk_lookup(request):
    gate = _ensure_kiosk_session(request)
    if gate:
        return gate

    open_context = _build_open_checkin_context()
    form = KioskLookupForm(request.GET or None)
    households = []
    query_performed = False
    result_count = 0
    query_feedback = None
    selectable_households = set()

    if request.GET and form.is_valid():
        query_performed = True
        cleaned = form.cleaned_data
        last_name = cleaned.get("last_name")
        phone_digits = cleaned.get("phone_digits")
        queryset = (
            Household.objects.prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=HouseholdMember.objects.select_related("person").order_by(
                        "person__last_name", "person__first_name"
                    ),
                )
            )
            .order_by("name")
        )
        filters = Q()
        if last_name:
            filters &= Q(memberships__person__last_name__istartswith=last_name)
        if phone_digits:
            pattern = _phone_regex_pattern(phone_digits)
            filters &= Q(phone__regex=pattern) | Q(memberships__person__phone__regex=pattern)

        if filters:
            queryset = queryset.filter(filters).distinct()
        households = list(queryset[:15])
        result_count = len(households)
        feedback_parts = []
        if last_name:
            feedback_parts.append(f'last name "{last_name.title()}"')
        if phone_digits:
            feedback_parts.append(f"phone {_format_phone_display(phone_digits)}")
        if feedback_parts:
            query_feedback = " and ".join(feedback_parts)

        if households and open_context["eligible_group_ids"]:
            person_mapping = {}
            for household in households:
                person_mapping[household.id] = [
                    member.person for member in household.memberships.all()
                ]
            person_ids = [
                person.id for members in person_mapping.values() for person in members
            ]
            if person_ids:
                eligible_person_ids = set(
                    GroupMembership.objects.filter(
                        person_id__in=person_ids,
                        group_id__in=open_context["eligible_group_ids"],
                    ).values_list("person_id", flat=True)
                )
                for household_id, persons in person_mapping.items():
                    if any(person.id in eligible_person_ids for person in persons):
                        selectable_households.add(household_id)

    context = {
        "form": form,
        "households": households,
        "query_performed": query_performed,
        "result_count": result_count,
        "query_feedback": query_feedback,
        "selectable_households": selectable_households,
        "open_windows": open_context["open_windows"],
    }
    return render(request, "attendance/kiosk_lookup.html", context)


def kiosk_family_select(request, pk):
    gate = _ensure_kiosk_session(request)
    if gate:
        return gate

    open_context = _build_open_checkin_context()
    window_group_map = open_context["window_group_map"]
    open_windows = open_context["open_windows"]
    household = get_object_or_404(
        Household.objects.prefetch_related(
            Prefetch(
                "memberships",
                queryset=HouseholdMember.objects.select_related("person").order_by(
                    "person__last_name", "person__first_name"
                ),
            )
        ),
        pk=pk,
    )

    memberships = list(household.memberships.all())
    persons = [membership.person for membership in memberships]
    person_lookup = {person.id: person for person in persons}

    groups_by_person = {}
    if persons and open_context["eligible_group_ids"]:
        group_memberships = (
            GroupMembership.objects.filter(
                person_id__in=list(person_lookup.keys()),
                group_id__in=open_context["eligible_group_ids"],
            )
            .select_related("group")
            .order_by("group__name")
        )
        for membership in group_memberships:
            groups_by_person.setdefault(membership.person_id, []).append(membership.group)

    eligible_people = []
    unavailable_people = []
    person_choices = []
    person_group_map = {}

    for membership in memberships:
        person = membership.person
        groups = groups_by_person.get(person.id, [])
        if groups:
            display_name = f"{person.first_name} {person.last_name}".strip() or str(person)
            eligible_people.append({"person": person, "groups": groups})
            person_choices.append((person.id, display_name))
            person_group_map[person.id] = {group.id for group in groups}
        else:
            unavailable_people.append(person)

    window_choices = [
        (window_data["window"].id, window_data["window"].display_label)
        for window_data in open_windows
    ]

    if not open_windows:
        messages.warning(
            request,
            "There are no active check-in windows right now. Configure an active schedule first.",
        )

    form = CheckInSelectionForm(
        request.POST or None,
        person_choices=person_choices,
        window_choices=window_choices,
        person_group_map=person_group_map,
        window_group_map={
            window_id: data["group_ids"] for window_id, data in window_group_map.items()
        },
    )

    if request.method == "POST" and form.is_valid():
        window_id = form.cleaned_data["window_id"]
        selected_person_ids = form.cleaned_data["person_ids"]
        window = get_object_or_404(
            CheckInWindow.objects.select_related("configuration"), pk=window_id
        )
        window_groups = window_group_map.get(window_id, {}).get("group_ids", set())
        records = []
        with transaction.atomic():
            for person_id in selected_person_ids:
                person = person_lookup.get(person_id)
                if not person:
                    continue
                candidate_group_ids = person_group_map.get(person_id, set())
                resolved_group_id = next(
                    (group_id for group_id in candidate_group_ids if group_id in window_groups),
                    None,
                )
                records.append(
                    AttendanceRecord.objects.create(
                        person=person,
                        household=household,
                        group_id=resolved_group_id,
                        configuration=window.configuration,
                        checkin_window=window,
                        method=AttendanceRecord.METHOD_KIOSK,
                    )
                )
        request.session[KIOSK_CONFIRMATION_KEY] = [record.id for record in records]
        return redirect("attendance:kiosk_confirmation")

    return render(
        request,
        "attendance/kiosk_family_select.html",
        {
            "household": household,
            "eligible_people": eligible_people,
            "unavailable_people": unavailable_people,
            "form": form,
            "open_windows": open_windows,
            "selected_people": form["person_ids"].value() if form.is_bound else [],
            "selected_window": form["window_id"].value() if form.is_bound else None,
        },
    )


def kiosk_confirmation(request):
    gate = _ensure_kiosk_session(request)
    if gate:
        return gate

    record_ids = request.session.get(KIOSK_CONFIRMATION_KEY)
    if not record_ids:
        return redirect("attendance:kiosk_lookup")

    records = list(
        AttendanceRecord.objects.filter(id__in=record_ids).select_related(
            "person", "group", "configuration"
        )
    )
    request.session.pop(KIOSK_CONFIRMATION_KEY, None)

    return render(
        request,
        "attendance/kiosk_confirmation.html",
        {
            "records": records,
        },
    )

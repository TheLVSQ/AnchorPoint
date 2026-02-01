from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from messaging.models import CommunicationLog

from core.permissions import staff_required
from households.forms import (
    HouseholdMembershipForm,
    HouseholdQuickCreateForm,
)
from households.models import HouseholdMember
from .models import Person
from .forms import PersonForm


@staff_required
def people_list(request):
    query = request.GET.get("q")

    if query:
        people = Person.objects.filter(
            first_name__icontains=query
        ) | Person.objects.filter(last_name__icontains=query)
    else:
        people = Person.objects.all().order_by("last_name", "first_name")

    return render(request, "people/people_list.html", {"people": people})


@staff_required
def people_add(request):
    if request.method == "POST":
        form = PersonForm(request.POST, request.FILES)
        if form.is_valid():
            person = form.save()
            messages.success(request, "Person added successfully!")
            return redirect("people_detail", pk=person.pk)
    else:
        form = PersonForm()

    return render(request, "people/people_form.html", {"form": form})


@staff_required
def people_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    households = (
        person.households.all()
        .prefetch_related("memberships__person")
        .order_by("name")
    )
    registrations = (
        person.event_registrations.select_related("event", "registration")
        .order_by("-registration__created_at")
    )
    communication_logs = (
        CommunicationLog.objects.filter(person=person)
        .select_related("recorded_by")
        .order_by("-created_at")[:10]
    )
    existing_household_form = HouseholdMembershipForm(person=person)
    new_household_form = HouseholdQuickCreateForm(initial={"primary_adult": person.pk})
    context = {
        "person": person,
        "households": households,
        "registrations": registrations,
        "communication_logs": communication_logs,
        "existing_household_form": existing_household_form,
        "new_household_form": new_household_form,
    }
    return render(request, "people/people_detail.html", context)


@staff_required
def people_edit(request, pk):
    person = get_object_or_404(Person, pk=pk)

    if request.method == "POST":
        form = PersonForm(request.POST, request.FILES, instance=person)
        if form.is_valid():
            form.save()
            messages.success(request, "Person updated successfully!")
            return redirect("people_detail", pk=pk)
    else:
        form = PersonForm(instance=person)

    return render(request, "people/people_form.html", {"form": form})


@staff_required
def people_household_add(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST":
        form = HouseholdMembershipForm(request.POST, person=person)
        if form.is_valid():
            household = form.cleaned_data["household"]
            relationship_type = form.cleaned_data["relationship_type"]
            try:
                HouseholdMember.objects.create(
                    household=household,
                    person=person,
                    relationship_type=relationship_type,
                )
                messages.success(
                    request, f"{person} was linked to {household.name}."
                )
            except IntegrityError:
                messages.warning(
                    request,
                    f"{person} is already part of {household.name}.",
                )
        else:
            messages.error(request, "Unable to link to family. Please fix the errors.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_household_create(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST":
        form = HouseholdQuickCreateForm(request.POST)
        if form.is_valid():
            relationship_type = form.cleaned_data["relationship_type"]
            household = form.save()
            HouseholdMember.objects.create(
                household=household,
                person=person,
                relationship_type=relationship_type,
            )
            messages.success(request, f"Created {household.name} and linked {person}.")
        else:
            messages.error(request, "Could not create family. Please check the form.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_household_remove(request, pk, household_pk):
    person = get_object_or_404(Person, pk=pk)
    membership = get_object_or_404(
        HouseholdMember, person=person, household_id=household_pk
    )
    if request.method == "POST":
        membership.delete()
        messages.success(request, "Removed from family.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_lookup(request):
    query = (request.GET.get("q") or "").strip()
    results = []
    if query:
        people = (
            Person.objects.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
            )
            .order_by("last_name", "first_name")[:8]
        )
        for person in people:
            results.append(
                {
                    "id": person.pk,
                    "name": f"{person.first_name} {person.last_name}".strip(),
                    "email": person.email or "",
                    "phone": person.phone or "",
                }
            )
    return JsonResponse({"results": results})

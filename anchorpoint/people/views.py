from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
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
from households.models import Household, HouseholdMember
from .models import Person
from .forms import PersonForm


@staff_required
def people_list(request):
    query = request.GET.get("q", "").strip()

    if query:
        people = (
            Person.objects.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
            ).order_by("last_name", "first_name")
        )
    else:
        people = Person.objects.all().order_by("last_name", "first_name")

    page_obj = Paginator(people, 25).get_page(request.GET.get("page"))
    return render(request, "people/people_list.html", {
        "page_obj": page_obj,
        "query": query,
    })


@staff_required
def people_add(request):
    if request.method == "POST":
        form = PersonForm(request.POST, request.FILES)
        if form.is_valid():
            person = form.save()

            # Handle household assignment
            household_action = request.POST.get("household_action", "skip")
            relationship_type = request.POST.get(
                "household_relationship", "adult"
            )

            if household_action == "existing":
                household_id = request.POST.get("household_id")
                if household_id:
                    try:
                        household = Household.objects.get(pk=household_id)
                        HouseholdMember.objects.create(
                            household=household,
                            person=person,
                            relationship_type=relationship_type,
                        )
                        messages.success(
                            request,
                            f"Person added and linked to {household.name}.",
                        )
                    except (Household.DoesNotExist, IntegrityError):
                        messages.success(
                            request,
                            "Person added, but could not link to household.",
                        )
                else:
                    messages.success(request, "Person added successfully!")

            elif household_action == "new":
                household_name = request.POST.get(
                    "new_household_name", ""
                ).strip()
                if not household_name:
                    household_name = f"{person.last_name} Family"
                household = Household.objects.create(
                    name=household_name, primary_adult=person
                )
                HouseholdMember.objects.create(
                    household=household,
                    person=person,
                    relationship_type=relationship_type,
                )
                messages.success(
                    request,
                    f"Person added and {household.name} household created.",
                )
            else:
                messages.success(request, "Person added successfully!")

            return redirect("people_detail", pk=person.pk)
    else:
        form = PersonForm()

    households = Household.objects.all().order_by("name")
    return render(request, "people/people_form.html", {
        "form": form,
        "households": households,
    })


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
def people_household_move(request, pk, household_pk):
    """Move or copy a person from one household to another."""
    person = get_object_or_404(Person, pk=pk)
    source_membership = get_object_or_404(
        HouseholdMember, person=person, household_id=household_pk
    )

    if request.method == "POST":
        target_household_id = request.POST.get("target_household")
        action = request.POST.get("move_action", "move")  # "move" or "copy"
        relationship_type = request.POST.get(
            "relationship_type", source_membership.relationship_type
        )

        if not target_household_id:
            messages.error(request, "Please select a target household.")
            return redirect("people_detail", pk=pk)

        try:
            target_household = Household.objects.get(pk=target_household_id)
        except Household.DoesNotExist:
            messages.error(request, "Target household not found.")
            return redirect("people_detail", pk=pk)

        # Create membership in target household
        try:
            HouseholdMember.objects.create(
                household=target_household,
                person=person,
                relationship_type=relationship_type,
            )
        except IntegrityError:
            messages.warning(
                request,
                f"{person} is already in {target_household.name}.",
            )
            return redirect("people_detail", pk=pk)

        # Remove from source if "move" (not "copy")
        if action == "move":
            source_membership.delete()
            messages.success(
                request,
                f"Moved {person} from {source_membership.household.name} "
                f"to {target_household.name}.",
            )
        else:
            messages.success(
                request,
                f"Added {person} to {target_household.name} "
                f"(kept in {source_membership.household.name}).",
            )

        return redirect("people_detail", pk=pk)

    # GET: show the move form
    other_households = Household.objects.exclude(pk=household_pk).order_by("name")
    return render(request, "people/people_household_move.html", {
        "person": person,
        "source_membership": source_membership,
        "other_households": other_households,
        "relationship_choices": HouseholdMember.RelationshipType.choices,
    })


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


@staff_required
def people_search(request):
    """HTMX endpoint: returns the people results partial for live search."""
    query = request.GET.get("q", "").strip()
    if query:
        people = Person.objects.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
        ).order_by("last_name", "first_name")
    else:
        people = Person.objects.all().order_by("last_name", "first_name")

    page_obj = Paginator(people, 25).get_page(request.GET.get("page"))
    return render(request, "people/partials/people_results.html", {
        "page_obj": page_obj,
        "query": query,
    })

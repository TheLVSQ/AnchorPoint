from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError

from households.forms import (
    HouseholdMembershipForm,
    HouseholdQuickCreateForm,
)
from households.models import HouseholdMember
from .models import Person
from .forms import PersonForm


@login_required
def people_list(request):
    query = request.GET.get("q")

    if query:
        people = Person.objects.filter(
            first_name__icontains=query
        ) | Person.objects.filter(last_name__icontains=query)
    else:
        people = Person.objects.all().order_by("last_name", "first_name")

    return render(request, "people/people_list.html", {"people": people})


@login_required
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


@login_required
def people_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    households = (
        person.households.all()
        .prefetch_related("memberships__person")
        .order_by("name")
    )
    existing_household_form = HouseholdMembershipForm(person=person)
    new_household_form = HouseholdQuickCreateForm(initial={"primary_adult": person.pk})
    context = {
        "person": person,
        "households": households,
        "existing_household_form": existing_household_form,
        "new_household_form": new_household_form,
    }
    return render(request, "people/people_detail.html", context)


@login_required
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


@login_required
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


@login_required
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


@login_required
def people_household_remove(request, pk, household_pk):
    person = get_object_or_404(Person, pk=pk)
    membership = get_object_or_404(
        HouseholdMember, person=person, household_id=household_pk
    )
    if request.method == "POST":
        membership.delete()
        messages.success(request, "Removed from family.")
    return redirect("people_detail", pk=pk)

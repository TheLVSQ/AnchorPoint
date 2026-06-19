from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.permissions import staff_required
from people.models import Person

from .forms import HouseholdForm
from .models import Household, HouseholdMember


@staff_required
def family_list(request):
    query = request.GET.get("q", "").strip()

    families = (
        Household.objects.all()
        .select_related("primary_adult")
        .prefetch_related("memberships__person")
        .annotate(member_count=Count("memberships"))
        .order_by("name")
    )
    if query:
        families = families.filter(
            Q(name__icontains=query) | Q(members__last_name__icontains=query)
        ).distinct()

    page_obj = Paginator(families, 25).get_page(request.GET.get("page"))
    return render(request, "households/family_list.html", {
        "page_obj": page_obj,
        "query": query,
    })


@staff_required
def family_detail(request, pk):
    household = get_object_or_404(
        Household.objects.select_related("primary_adult"), pk=pk
    )
    memberships = household.memberships.select_related("person").order_by(
        "relationship_type", "person__last_name", "person__first_name"
    )

    # Add-member search: candidates are people not already in this family.
    member_query = request.GET.get("member_q", "").strip()
    candidates = []
    if member_query:
        candidates = (
            Person.objects.filter(
                Q(first_name__icontains=member_query)
                | Q(last_name__icontains=member_query)
            )
            .exclude(household_memberships__household=household)
            .order_by("last_name", "first_name")[:10]
        )

    return render(request, "households/family_detail.html", {
        "household": household,
        "memberships": memberships,
        "member_query": member_query,
        "candidates": candidates,
        "relationship_choices": HouseholdMember.RelationshipType.choices,
    })


@staff_required
def family_edit(request, pk):
    household = get_object_or_404(Household, pk=pk)

    if request.method == "POST":
        form = HouseholdForm(request.POST, instance=household)
        _limit_primary_adult_choices(form, household)
        if form.is_valid():
            form.save()
            messages.success(request, f"{household.name} updated.")
            return redirect("households:family_detail", pk=household.pk)
    else:
        form = HouseholdForm(instance=household)
        _limit_primary_adult_choices(form, household)

    return render(request, "households/family_form.html", {
        "form": form,
        "household": household,
    })


@staff_required
def family_delete(request, pk):
    """Delete a family — but only once it has no members. Remaining people must
    first be moved to another family or deleted outright (an orphaned family is
    not a valid end state). The confirmation page offers both resolutions per
    member; the final delete is blocked server-side while any member remains."""
    household = get_object_or_404(
        Household.objects.select_related("primary_adult"), pk=pk
    )

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "move":
            membership = get_object_or_404(
                HouseholdMember, pk=request.POST.get("member_pk", ""), household=household
            )
            target_id = request.POST.get("target_household", "")
            target = (
                Household.objects.exclude(pk=household.pk).filter(pk=target_id).first()
                if target_id.isdigit()
                else None
            )
            if target is None:
                messages.error(request, "Choose a family to move them to.")
            else:
                person = membership.person
                HouseholdMember.objects.get_or_create(
                    household=target,
                    person=person,
                    defaults={"relationship_type": membership.relationship_type},
                )
                membership.delete()
                if household.primary_adult_id == person.pk:
                    household.primary_adult = None
                    household.save(update_fields=["primary_adult"])
                messages.success(request, f"{person} moved to {target.name}.")
            return redirect("households:family_delete", pk=pk)

        if action == "delete_person":
            membership = get_object_or_404(
                HouseholdMember, pk=request.POST.get("member_pk", ""), household=household
            )
            person = membership.person
            name = str(person)
            # Person.delete() cascades to their household memberships, check-ins,
            # group memberships and comms logs; primary_adult FK is SET_NULL.
            person.delete()
            messages.success(request, f"{name} was permanently deleted.")
            return redirect("households:family_delete", pk=pk)

        if action == "delete_family":
            if household.memberships.exists():
                messages.error(
                    request,
                    "This family still has members. Move or delete each person first.",
                )
                return redirect("households:family_delete", pk=pk)
            name = household.name
            household.delete()
            messages.success(request, f"{name} was deleted.")
            return redirect("households:family_list")

        messages.error(request, "Unknown action.")
        return redirect("households:family_delete", pk=pk)

    members = household.memberships.select_related("person").order_by(
        "relationship_type", "person__last_name", "person__first_name"
    )
    other_families = Household.objects.exclude(pk=household.pk).order_by("name")
    return render(request, "households/family_confirm_delete.html", {
        "household": household,
        "members": members,
        "other_families": other_families,
    })


def _limit_primary_adult_choices(form, household):
    """Primary adult must be one of the family's current members."""
    form.fields["primary_adult"].queryset = Person.objects.filter(
        household_memberships__household=household
    )


@staff_required
@require_POST
def family_member_add(request, pk):
    household = get_object_or_404(Household, pk=pk)
    person_id = request.POST.get("person_id", "")
    relationship = request.POST.get("relationship_type", HouseholdMember.RelationshipType.ADULT)
    if relationship not in HouseholdMember.RelationshipType.values:
        relationship = HouseholdMember.RelationshipType.ADULT

    person = Person.objects.filter(pk=person_id).first() if person_id.isdigit() else None
    if person is None:
        messages.error(request, "Pick a person to add.")
        return redirect("households:family_detail", pk=pk)

    _, created = HouseholdMember.objects.get_or_create(
        household=household,
        person=person,
        defaults={"relationship_type": relationship},
    )
    if created:
        messages.success(request, f"{person} added to {household.name}.")
    else:
        messages.info(request, f"{person} is already in {household.name}.")
    return redirect("households:family_detail", pk=pk)


@staff_required
@require_POST
def family_member_remove(request, pk, member_pk):
    membership = get_object_or_404(HouseholdMember, pk=member_pk, household_id=pk)
    person = membership.person
    household = membership.household
    membership.delete()
    if household.primary_adult_id == person.pk:
        household.primary_adult = None
        household.save(update_fields=["primary_adult"])
    messages.success(request, f"{person} removed from {household.name}.")
    return redirect("households:family_detail", pk=pk)


@staff_required
@require_POST
def family_member_role(request, pk, member_pk):
    membership = get_object_or_404(HouseholdMember, pk=member_pk, household_id=pk)
    relationship = request.POST.get("relationship_type", "")
    if relationship in HouseholdMember.RelationshipType.values:
        membership.relationship_type = relationship
        membership.save(update_fields=["relationship_type"])
        messages.success(
            request,
            f"{membership.person} is now {membership.get_relationship_type_display()}.",
        )
    else:
        messages.error(request, "Pick a valid relationship.")
    return redirect("households:family_detail", pk=pk)


@staff_required
@require_POST
def family_set_primary(request, pk):
    household = get_object_or_404(Household, pk=pk)
    person_id = request.POST.get("person_id", "")
    member = (
        HouseholdMember.objects.filter(household=household, person_id=person_id)
        .select_related("person")
        .first()
        if person_id.isdigit()
        else None
    )
    if member is None:
        messages.error(request, "Primary adult must be a member of the family.")
    else:
        household.primary_adult = member.person
        household.save(update_fields=["primary_adult"])
        messages.success(request, f"{member.person} is now the primary adult.")
    return redirect("households:family_detail", pk=pk)

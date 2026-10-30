from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.permissions import staff_required
from households.models import Household
from people.models import Person
from scheduling.models import Assignment

from .forms import GroupForm, MembershipForm, PositionForm
from .models import Group, GroupMembership, Position


@staff_required
def group_list(request):
    groups = Group.objects.all()
    category_counts = (
        groups.values("category")
        .order_by()
        .annotate(total=Count("id"))
    )
    counts_by_category = {item["category"]: item["total"] for item in category_counts}
    category_summary = [
        {
            "key": key,
            "label": label,
            "count": counts_by_category.get(key, 0),
        }
        for key, label in Group.CATEGORY_CHOICES
    ]

    active_category_count = sum(1 for item in category_summary if item["count"] > 0)

    category = request.GET.get("category", "")
    listed = groups.annotate(member_count=Count("memberships", distinct=True))
    if category in counts_by_category:
        listed = listed.filter(category=category)
    else:
        category = ""
    page_obj = Paginator(listed.order_by("-is_active", "name"), 25).get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "group_count": groups.count(),
        "category_summary": category_summary,
        "active_category_count": active_category_count,
        "category": category,
    }
    return render(request, "groups/group_list.html", context)


@staff_required
def group_create(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            messages.success(request, f"{group.name} created successfully.")
            return redirect("groups:list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = GroupForm()

    return render(request, "groups/group_form.html", {
        "form": form,
        "title": "Create Group",
        "cancel_url": reverse("groups:list"),
    })


def _memberships(group):
    return group.memberships.select_related("person").prefetch_related("positions").order_by(
        "person__last_name", "person__first_name"
    )


@staff_required
def group_detail(request, pk, position_form=None):
    group = get_object_or_404(Group, pk=pk)
    return render(request, "groups/group_detail.html", {
        "group": group,
        "memberships": _memberships(group),
        "positions": group.positions.annotate(people=Count("memberships")),
        "position_form": position_form or PositionForm(group=group),
    })


@staff_required
@require_POST
def position_add(request, pk):
    group = get_object_or_404(Group, pk=pk)
    form = PositionForm(request.POST, group=group)
    if not form.is_valid():
        return group_detail(request, pk, position_form=form)
    position = form.save()
    messages.success(request, f"Added {position.name}. Tick it on each member who can fill it.")
    return redirect("groups:detail", pk=pk)


@staff_required
@require_POST
def position_remove(request, pk, position_id):
    position = get_object_or_404(Position, pk=position_id, group_id=pk)
    plans = position.assignments.values("plan").distinct().count()
    if plans:
        messages.error(request, f"{position.name} is on {plans} schedule{'s' if plans != 1 else ''}. "
                                "Take those people off it first.")
        return redirect("groups:detail", pk=pk)
    position.delete()
    messages.success(request, f"Removed {position.name}.")
    return redirect("groups:detail", pk=pk)


@staff_required
def member_edit(request, pk, mid):
    membership = get_object_or_404(
        GroupMembership.objects.select_related("group", "person"), pk=mid, group_id=pk
    )
    form = MembershipForm(request.POST or None, instance=membership)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Updated {membership.person} on {membership.group}.")
        return redirect("groups:detail", pk=pk)
    return render(request, "groups/member_edit.html", {
        "form": form, "membership": membership, "group": membership.group,
    })


@staff_required
def group_edit(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, f"{group.name} updated.")
            return redirect("groups:detail", pk=pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = GroupForm(instance=group)
    return render(request, "groups/group_form.html", {
        "form": form,
        "group": group,
        "title": "Edit Group",
        "cancel_url": reverse("groups:detail", args=[pk]),
    })


@staff_required
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        name = group.name
        plans = Assignment.objects.filter(position__group=group).values("plan").distinct().count()
        if plans:
            messages.error(request, f"{name} is on {plans} schedule{'s' if plans != 1 else ''}. "
                                    "Take its people off those dates first, or archive the group.")
            return redirect("groups:detail", pk=group.pk)
        group.delete()
        messages.success(request, f"{name} deleted.")
        return redirect("groups:list")
    return render(request, "groups/group_confirm_delete.html", {"group": group})


# ---------------------------------------------------------------------------
# Member management helpers + HTMX views
# ---------------------------------------------------------------------------

def _render_member_list(request, group):
    return render(request, "groups/group_member_list.html", {
        "group": group,
        "memberships": _memberships(group),
    })


@staff_required
def group_member_search(request, pk):
    group = get_object_or_404(Group, pk=pk)
    q = request.GET.get("q", "").strip()
    if not q:
        return HttpResponse("")

    existing_ids = set(group.memberships.values_list("person_id", flat=True))
    people = (
        Person.objects.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
        .exclude(pk__in=existing_ids)
        .prefetch_related("households__members")
        [:10]
    )

    results = []
    for person in people:
        household = person.households.first()
        family_count = None
        if household:
            family_count = household.members.exclude(pk__in=existing_ids).count()
            if family_count <= 1:
                # Only this person would be added — no point showing "Add family"
                household = None
                family_count = None
        results.append({
            "person": person,
            "household": household,
            "family_count": family_count,
        })

    return render(request, "groups/group_member_search_results.html", {
        "group": group,
        "results": results,
    })


@staff_required
@require_POST
def group_member_add(request, pk):
    group = get_object_or_404(Group, pk=pk)
    person_id = request.POST.get("person_id")
    household_id = request.POST.get("household_id")

    if person_id:
        person = get_object_or_404(Person, pk=person_id)
        GroupMembership.objects.get_or_create(
            group=group,
            person=person,
            defaults={"role": "member"},
        )
    elif household_id:
        household = get_object_or_404(Household, pk=household_id)
        existing_ids = set(group.memberships.values_list("person_id", flat=True))
        new_memberships = [
            GroupMembership(group=group, person=person, role="member")
            for person in household.members.exclude(pk__in=existing_ids)
        ]
        GroupMembership.objects.bulk_create(new_memberships, ignore_conflicts=True)

    return _render_member_list(request, group)


@staff_required
@require_POST
def group_member_remove(request, pk, mid):
    group = get_object_or_404(Group, pk=pk)
    membership = get_object_or_404(GroupMembership, pk=mid)
    if membership.group_id != group.pk:
        raise Http404("Membership does not belong to this group.")
    membership.delete()
    return _render_member_list(request, group)

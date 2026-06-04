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

from .forms import GroupForm
from .models import Group, GroupMembership


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

    page_obj = Paginator(groups.order_by("name"), 25).get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "group_count": groups.count(),
        "category_summary": category_summary,
        "active_category_count": active_category_count,
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


@staff_required
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk)
    memberships = group.memberships.select_related("person").order_by(
        "person__last_name", "person__first_name"
    )
    return render(request, "groups/group_detail.html", {
        "group": group,
        "memberships": memberships,
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
        group.delete()
        messages.success(request, f"{name} deleted.")
        return redirect("groups:list")
    return render(request, "groups/group_confirm_delete.html", {"group": group})


# ---------------------------------------------------------------------------
# Member management helpers + HTMX views
# ---------------------------------------------------------------------------

def _render_member_list(request, group):
    memberships = group.memberships.select_related("person").order_by(
        "person__last_name", "person__first_name"
    )
    return render(request, "groups/group_member_list.html", {
        "group": group,
        "memberships": memberships,
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

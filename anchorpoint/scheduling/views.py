from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Min, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.permissions import staff_required
from groups.models import Group, GroupMembership, Position
from people.models import Person

from . import schedule
from .forms import (
    AddDatesForm, BlockoutForm, PlanForm, ServiceTypeForm, ServingWeeksForm,
)
from .models import Assignment, Blockout, Plan, ServiceType
from .services import current_blockouts, serving_memberships


def _own_person(user):
    """The Person this login belongs to, or None (e.g. a staff login with no linked person)."""
    profile = getattr(user, "profile", None)
    return profile.person if profile and profile.person_id else None


# ---------------------------------------------------------------------------
# "My serving": a volunteer's own teams, weeks and blockouts
# ---------------------------------------------------------------------------

@login_required
def my_serving(request, blockout_form=None, weeks_form=None):
    person = _own_person(request.user)
    teams = []
    if person:
        for membership in serving_memberships(person):
            form = weeks_form if weeks_form and weeks_form.instance.pk == membership.pk else None
            teams.append((membership, form or ServingWeeksForm(
                instance=membership, prefix=f"m{membership.pk}")))
    return render(request, "scheduling/my_serving.html", {
        "person": person,
        "teams": teams,
        "blockouts": current_blockouts(person) if person else [],
        "blockout_form": blockout_form or (BlockoutForm(person=person) if person else None),
    })


def _own_membership(request, mid):
    person = _own_person(request.user)
    if not person:
        raise Http404
    return get_object_or_404(serving_memberships(person), pk=mid)


@login_required
@require_POST
def my_serving_weeks(request, mid):
    membership = _own_membership(request, mid)
    form = ServingWeeksForm(request.POST, instance=membership, prefix=f"m{membership.pk}")
    if not form.is_valid():
        return my_serving(request, weeks_form=form)
    form.save()
    messages.success(request, f"Saved: you serve {membership.serving_weeks_label.lower()} "
                              f"on {membership.group}.")
    return redirect("scheduling:my_serving")


@login_required
@require_POST
def my_blockout_add(request):
    person = _own_person(request.user)
    if not person:
        raise Http404
    form = BlockoutForm(request.POST, person=person)
    if not form.is_valid():
        return my_serving(request, blockout_form=form)
    blockout = form.save()
    messages.success(request, f"Blocked out {blockout.label}.")
    return redirect("scheduling:my_serving")


@login_required
@require_POST
def my_blockout_delete(request, pk):
    person = _own_person(request.user)
    if not person:
        raise Http404
    blockout = get_object_or_404(Blockout, pk=pk, person=person)
    blockout.delete()
    messages.success(request, f"Removed the blockout for {blockout.label}.")
    return redirect("scheduling:my_serving")


# ---------------------------------------------------------------------------
# Staff: blockouts on a person's page
# ---------------------------------------------------------------------------

@staff_required
@require_POST
def person_blockout_add(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    form = BlockoutForm(request.POST, person=person)
    if form.is_valid():
        blockout = form.save()
        messages.success(request, f"Blocked out {blockout.label} for {person.first_name}.")
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"Blockout not saved: {errors}")
    return redirect("people_detail", pk=person.pk)


@staff_required
@require_POST
def person_blockout_delete(request, person_id, pk):
    blockout = get_object_or_404(Blockout, pk=pk, person_id=person_id)
    blockout.delete()
    messages.success(request, f"Removed the blockout for {blockout.label}.")
    return redirect("people_detail", pk=person_id)


# ---------------------------------------------------------------------------
# Staff: service types, plans and the schedule grid
# ---------------------------------------------------------------------------

GRID_COLUMNS = 6


@staff_required
def service_type_list(request):
    today = timezone.localdate()
    service_types = ServiceType.objects.annotate(
        next_date=Min("plans__date", filter=Q(plans__date__gte=today)),
        upcoming=Count("plans", filter=Q(plans__date__gte=today)),
        positions=Count("needs", distinct=True),
    )
    return render(request, "scheduling/service_type_list.html", {
        "active": [s for s in service_types if s.is_active],
        "inactive": [s for s in service_types if not s.is_active],
    })


@staff_required
def service_type_form(request, pk=None):
    service_type = get_object_or_404(ServiceType, pk=pk) if pk else None
    form = ServiceTypeForm(request.POST or None, instance=service_type)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        if service_type:
            messages.success(request, f"Saved {saved}.")
        else:
            messages.success(request, f"Created {saved}. Next, add its dates.")
        return redirect("scheduling:schedule", pk=saved.pk)
    return render(request, "scheduling/service_type_form.html", {
        "form": form, "service_type": service_type,
    })


@staff_required
def schedule_grid(request, pk):
    service_type = get_object_or_404(ServiceType, pk=pk)
    today = timezone.localdate()
    start = parse_date(request.GET.get("start") or "") or today
    plans = list(service_type.plans.filter(date__gte=start)[:GRID_COLUMNS])
    earlier = list(service_type.plans.filter(date__lt=start)
                   .order_by("-date").values_list("date", flat=True)[:GRID_COLUMNS])
    later = None
    if plans and service_type.plans.filter(date__gt=plans[-1].date).exists():
        later = plans[-1].date + timedelta(days=1)

    teams = list(Group.objects.filter(positions__needs__service_type=service_type)
                 .distinct().order_by("name"))
    team = next((t for t in teams if str(t.pk) == request.GET.get("team")), None)
    return render(request, "scheduling/schedule.html", {
        "service_type": service_type,
        "plans": plans,
        "grid": schedule.build_grid(service_type, plans, team=team),
        "teams": teams,
        "team": team,
        "start": start,
        "earlier": earlier[-1] if earlier else None,
        "later": later,
        "dates_form": AddDatesForm(initial={
            "starts_on": today, "ends_on": today + timedelta(weeks=13)}),
    })


@staff_required
@require_POST
def plans_add(request, pk):
    service_type = get_object_or_404(ServiceType, pk=pk)
    form = AddDatesForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("scheduling:schedule", pk=pk)
    start, end = form.cleaned_data["starts_on"], form.cleaned_data["ends_on"]
    added = schedule.generate_plans(service_type, start, end)
    if added:
        messages.success(request, f"Added {added} date{'s' if added != 1 else ''}.")
    else:
        messages.info(request, "Those dates already have plans.")
    return redirect(f"{reverse('scheduling:schedule', args=[pk])}?start={start.isoformat()}")


@staff_required
def plan_detail(request, pk):
    plan = get_object_or_404(Plan.objects.select_related("service_type"), pk=pk)
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved the plan.")
        return redirect("scheduling:plan_detail", pk=plan.pk)
    siblings = plan.service_type.plans
    return render(request, "scheduling/plan_detail.html", {
        "plan": plan,
        "form": form,
        "grid": schedule.build_grid(plan.service_type, [plan]),
        "previous": siblings.filter(date__lt=plan.date).order_by("-date").first(),
        "next": siblings.filter(date__gt=plan.date).order_by("date").first(),
    })


@staff_required
@require_POST
def plan_delete(request, pk):
    plan = get_object_or_404(Plan.objects.select_related("service_type"), pk=pk)
    service_type, people = plan.service_type, plan.assignments.count()
    plan.delete()
    note = f" ({people} scheduled {'person' if people == 1 else 'people'} removed)" if people else ""
    messages.success(request, f"Deleted {plan.date:%b %-d}{note}.")
    return redirect("scheduling:schedule", pk=service_type.pk)


# HTMX: one grid cell (plan × position): show it, pick someone for it, add, remove.

def _cell_parts(pk, position_id):
    plan = get_object_or_404(Plan.objects.select_related("service_type"), pk=pk)
    position = get_object_or_404(Position.objects.select_related("group"), pk=position_id)
    return plan, position


def _render_cell(request, plan, position):
    if not request.headers.get("HX-Request"):
        return redirect("scheduling:plan_detail", pk=plan.pk)
    return render(request, "scheduling/_cell.html",
                  {"cell": schedule.build_cell(plan, position)})


@staff_required
def cell(request, pk, position_id):
    return _render_cell(request, *_cell_parts(pk, position_id))


@staff_required
def cell_pick(request, pk, position_id):
    plan, position = _cell_parts(pk, position_id)
    fits, others = schedule.candidates(plan, position)
    return render(request, "scheduling/_picker.html", {
        "cell": schedule.build_cell(plan, position), "fits": fits, "others": others,
    })


@staff_required
@require_POST
def cell_assign(request, pk, position_id):
    plan, position = _cell_parts(pk, position_id)
    # Only people on the team: the picker never offers the whole directory.
    membership = get_object_or_404(GroupMembership.objects.select_related("person"),
                                   group_id=position.group_id,
                                   person_id=request.POST.get("person") or 0)
    schedule.assign(plan, position, membership.person, by=request.user)
    return _render_cell(request, plan, position)


@staff_required
@require_POST
def assignment_remove(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.select_related("plan__service_type", "position__group"), pk=pk)
    assignment.delete()
    return _render_cell(request, assignment.plan, assignment.position)

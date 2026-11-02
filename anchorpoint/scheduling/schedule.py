"""Plans and the schedule grid: which dates exist, who is in each position, and what's wrong.

A service type's needs (position + how many) are the grid's rows, grouped by team; its
plans are the columns. Warnings come from `availability.Availability`, so the grid and the
picker apply the same rules. Views call this module; they don't query assignments directly.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from groups.models import Group, GroupMembership

from .availability import Availability
from .requests import can_email
from .models import Assignment, Plan

MAX_RANGE_DAYS = 366


def plan_dates(service_type, start, end):
    """The dates a service type has plans on between `start` and `end` (inclusive): its
    weekday each week, or every day when it has no weekday (VBS)."""
    days = []
    day = start
    while day <= end:
        if service_type.weekday is None or day.weekday() == service_type.weekday:
            days.append(day)
        day += timedelta(days=1)
    return days


def generate_plans(service_type, start, end):
    """Create the missing plans between `start` and `end`; returns how many were added.
    Safe to re-run: existing dates are left alone."""
    added = 0
    for day in plan_dates(service_type, start, end):
        _, created = Plan.objects.get_or_create(
            service_type=service_type, date=day, defaults={"time": service_type.default_time}
        )
        added += created
    return added


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------

@dataclass
class Slot:
    """One person in a cell, with anything wrong about it."""
    assignment: Assignment
    warnings: list
    emailable: bool = True  # False: requests and reminders can't reach them


@dataclass
class Cell:
    plan: Plan
    position: object
    needed: int
    slots: list = field(default_factory=list)

    @property
    def filled(self):
        return sum(1 for s in self.slots
                   if s.assignment.status != Assignment.Status.DECLINED)

    @property
    def short(self):
        return max(self.needed - self.filled, 0)

    @property
    def dom_id(self):
        return f"cell-{self.plan.pk}-{self.position.pk}"


@dataclass
class Row:
    position: object
    needed: int
    cells: list


@dataclass
class TeamRows:
    team: Group
    rows: list


def build_grid(service_type, plans, *, team=None, positions=None):
    """Rows for `plans` (columns): one per needed position (plus any position someone is
    assigned to that the service type no longer needs), grouped by team."""
    plans = list(plans)
    needs = {n.position_id: n for n in service_type.needs.select_related("position__group")}
    assignments = list(
        Assignment.objects.filter(plan__in=plans)
        .select_related("person", "position__group", "plan__service_type")
        .order_by("person__first_name", "person__last_name")
    )
    by_position = {pid: n.position for pid, n in needs.items()}
    for a in assignments:
        by_position.setdefault(a.position_id, a.position)
    wanted = [p for p in by_position.values()
              if (team is None or p.group_id == team.pk)
              and (positions is None or p in positions)]

    availability = Availability({a.person_id for a in assignments}, [p.date for p in plans])
    teams = {p.group_id for p in wanted}
    memberships = {
        (m.group_id, m.person_id): m
        for m in GroupMembership.objects.filter(
            group_id__in=teams, person_id__in={a.person_id for a in assignments}
        ).select_related("group")
    }
    cells = {}
    for a in assignments:
        membership = memberships.get((a.position.group_id, a.person_id))
        warnings = [] if a.status == Assignment.Status.DECLINED else availability.reasons(
            membership, a.plan.date, person_id=a.person_id, team=a.position.group, skip=a,
        )
        cells.setdefault((a.plan_id, a.position_id), []).append(
            Slot(a, warnings, can_email(a.person)))

    grouped = {}
    for position in sorted(wanted, key=lambda p: (p.group.name, p.name)):
        needed = needs[position.pk].count if position.pk in needs else 0
        row = Row(position, needed, [
            Cell(plan, position, needed, cells.get((plan.pk, position.pk), []))
            for plan in plans
        ])
        grouped.setdefault(position.group_id, TeamRows(position.group, [])).rows.append(row)
    return list(grouped.values())


def build_cell(plan, position):
    """The one cell for `plan` × `position` (HTMX refresh after a change)."""
    for team_rows in build_grid(plan.service_type, [plan], positions=[position]):
        return team_rows.rows[0].cells[0]
    return Cell(plan, position, 0)  # not needed and nobody in it


# ---------------------------------------------------------------------------
# Picking someone for a cell
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    membership: GroupMembership
    reasons: list


def candidates(plan, position):
    """Team members who could go in this cell, as (fits, others):
    - fits: members marked for `position`, available ones first, each with its reasons;
    - others: the rest of the team (not marked for it), so a new team with no positions
      set up yet can still be scheduled.
    People already in the cell are left out."""
    in_cell = plan.assignments.filter(position=position).values("person_id")
    memberships = list(
        GroupMembership.objects.filter(group_id=position.group_id)
        .exclude(person_id__in=in_cell)
        .select_related("person", "group").prefetch_related("positions")
        .order_by("person__first_name", "person__last_name")
    )
    availability = Availability([m.person_id for m in memberships], [plan.date])
    fits, others = [], []
    for m in memberships:
        candidate = Candidate(m, availability.reasons(m, plan.date))
        (fits if position in m.positions.all() else others).append(candidate)
    fits.sort(key=lambda c: bool(c.reasons))  # stable: available first, then by name
    return fits, others


def assign(plan, position, person, *, by=None):
    """Put `person` in `position` on `plan` (no-op if they're already there)."""
    assignment, _ = Assignment.objects.get_or_create(
        plan=plan, position=position, person=person, defaults={"created_by": by}
    )
    return assignment

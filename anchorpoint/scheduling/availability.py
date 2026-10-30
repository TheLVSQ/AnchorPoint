"""Who on a team can serve on a given date, and why not.

Three things count against a person on a date:
- their **serving pattern** on that team (`GroupMembership.serving_weeks`: which weeks of
  the month they serve; the week is the date's week of the month, so the 15th-21st is
  week 3),
- a **blockout** covering the date (any team; yearly ones repeat), and
- **already serving**: another assignment that date (any plan, any position; declined
  ones don't count).

They are warnings, not rules: staff can still schedule someone. The schedule grid and the
picker ask this module (`Availability` for many people and dates at once); never re-derive
these rules in a view.
"""
from collections import defaultdict

from django.db.models import Q

from .models import Assignment, Blockout


def week_of_month(day):
    """1 for the 1st-7th, 2 for the 8th-14th ... 5 for the 29th-31st."""
    return (day.day - 1) // 7 + 1


def ordinal(week):
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}[week]


def blockouts_on(day, people=None):
    """The blockouts covering `day`, optionally only for `people` (ids or a queryset)."""
    qs = Blockout.objects.filter(
        Q(repeats_yearly=True) | Q(starts_on__lte=day, ends_on__gte=day)
    )
    if people is not None:
        qs = qs.filter(person__in=people)
    # One-off ranges are filtered by the database; the few yearly ones are checked here.
    return [b for b in qs if b.covers(day)]


def blocked_person_ids(day, people=None):
    return {b.person_id for b in blockouts_on(day, people)}


def available(memberships, day, position=None):
    """`memberships` (a GroupMembership queryset) narrowed to people whose pattern includes
    that week, who aren't blocked out, and (if given) who can fill `position`. Doesn't look
    at other assignments that day; `Availability.reasons` does."""
    qs = memberships.filter(serving_weeks__contains=str(week_of_month(day)))
    if position is not None:
        qs = qs.filter(positions=position)
    return qs.exclude(person_id__in=blocked_person_ids(day, qs.values("person_id")))


class Availability:
    """Answers "why can't this person serve on this date" for many people and dates with
    two queries (blockouts, assignments), however many cells the grid has."""

    def __init__(self, person_ids, days):
        self.days = sorted(set(days))
        person_ids = set(person_ids)
        self._blockouts = defaultdict(list)
        self._assignments = defaultdict(list)
        if not person_ids or not self.days:
            return
        first, last = self.days[0], self.days[-1]
        for b in Blockout.objects.filter(person_id__in=person_ids).filter(
            Q(repeats_yearly=True) | Q(starts_on__lte=last, ends_on__gte=first)
        ):
            self._blockouts[b.person_id].append(b)
        for a in (
            Assignment.objects.filter(person_id__in=person_ids, plan__date__in=self.days)
            .exclude(status=Assignment.Status.DECLINED)
            .select_related("plan__service_type", "position")
        ):
            self._assignments[(a.person_id, a.plan.date)].append(a)

    def reasons(self, membership, day, *, person_id=None, team=None, skip=None):
        """Plain-language reasons against serving on `day` (empty = good to go).

        `membership` is the person's membership on the team, or None if they're not on it
        (then pass `person_id` and `team`). `skip` = the assignment being checked, so it
        doesn't count as "already serving" against itself."""
        reasons = []
        if membership is None:
            reasons.append(f"Not on {team}")
        else:
            person_id = membership.person_id
            week = week_of_month(day)
            if not membership.serves_week(week):
                reasons.append(f"Serves {membership.serving_weeks_label} on "
                               f"{membership.group}, not the {ordinal(week)} week")
        for b in self._blockouts.get(person_id, ()):
            if b.covers(day):
                reasons.append("Blocked out" + (f": {b.note}" if b.note else ""))
        for a in self._assignments.get((person_id, day), ()):
            if skip is None or a.pk != skip.pk:
                reasons.append(f"Already serving: {a.position} on {a.plan.service_type}")
        return reasons


def reasons_unavailable(membership, day):
    """Plain-language reasons this member can't serve on `day` (empty = available)."""
    return Availability([membership.person_id], [day]).reasons(membership, day)

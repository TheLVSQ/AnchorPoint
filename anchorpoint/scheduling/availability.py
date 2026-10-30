"""Who on a team can serve on a given date, and why not.

Two things rule a person out:
- their **serving pattern** on that team (`GroupMembership.serving_weeks`: which weeks of
  the month they serve; the week is the date's week of the month, so the 15th-21st is
  week 3), and
- a **blockout** covering the date (any team; yearly ones repeat).

The schedule grid asks this module; never re-derive these rules in a view.
"""
from django.db.models import Q

from .models import Blockout


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
    """`memberships` (a GroupMembership queryset) narrowed to people who can serve on `day`:
    their pattern includes that week, they aren't blocked out, and (if given) they can
    fill `position`."""
    qs = memberships.filter(serving_weeks__contains=str(week_of_month(day)))
    if position is not None:
        qs = qs.filter(positions=position)
    return qs.exclude(person_id__in=blocked_person_ids(day, qs.values("person_id")))


def reasons_unavailable(membership, day):
    """Plain-language reasons this member can't serve on `day` (empty = available)."""
    reasons = []
    week = week_of_month(day)
    if not membership.serves_week(week):
        reasons.append(f"Serves {membership.serving_weeks_label} on {membership.group}, "
                       f"not the {ordinal(week)} week")
    for blockout in blockouts_on(day, [membership.person_id]):
        reasons.append("Blocked out" + (f": {blockout.note}" if blockout.note else ""))
    return reasons

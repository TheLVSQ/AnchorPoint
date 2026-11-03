"""Who may build a schedule, and for which teams.

Staff schedule every team. A **team leader** (a login linked to a Person who is a `leader`
member of an active, schedulable team) schedules only the teams they lead, whatever their
role, so a Team Member who leads worship can fill worship's dates without a Staff login.
Leaders can pick and remove people and send requests for their team; setting up service
types, adding or deleting dates, and editing a plan's details stay staff-only.

The sidebar, every scheduling view and the contact rules ask this module; don't
re-derive "is this person a leader" anywhere else.
"""
from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from core.permissions import is_staff_or_above
from groups.models import Group


def _person_id(user):
    return getattr(getattr(user, "profile", None), "person_id", None)


def led_teams(user):
    """The active, schedulable teams this login leads (empty for anyone else)."""
    person_id = _person_id(user)
    if not person_id:
        return Group.objects.none()
    return (Group.objects.filter(is_active=True, memberships__person_id=person_id,
                                 memberships__role="leader")
            .exclude(category__in=Group.NOT_SCHEDULABLE).distinct().order_by("name"))


def is_team_leader(user):
    return led_teams(user).exists()


def can_manage(user):
    """Set up service types and dates, and edit or delete plans: staff only."""
    return is_staff_or_above(user)


def can_schedule(user, team):
    """May `user` put people on (and take them off) `team`'s positions?"""
    if is_staff_or_above(user):
        return True
    return team is not None and led_teams(user).filter(pk=team.pk).exists()


def schedulable_teams(user, teams):
    """`teams` narrowed to the ones `user` may schedule."""
    if is_staff_or_above(user):
        return list(teams)
    led = set(led_teams(user).values_list("pk", flat=True))
    return [t for t in teams if t.pk in led]


def scheduler_required(view_func):
    """Staff, or a leader of at least one team. Views must still check the specific team
    with `can_schedule`."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not (is_staff_or_above(request.user) or is_team_leader(request.user)):
            return HttpResponseForbidden("You do not have permission to access this page.")
        return view_func(request, *args, **kwargs)
    return wrapper

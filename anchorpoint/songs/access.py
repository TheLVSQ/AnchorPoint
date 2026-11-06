"""Who may use the song library and open charts.

Staff and team leaders (`scheduling.access.is_team_leader`) manage the library. Volunteers
don't browse it; they'll see the setlist and charts for the dates they serve (phase 2b adds
that branch to `can_view_chart`). Views and the sidebar ask this module only.
"""
from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from core.permissions import is_staff_or_above
from scheduling.access import is_team_leader


def can_manage_songs(user):
    return bool(user and user.is_authenticated
                and (is_staff_or_above(user) or is_team_leader(user)))


def can_view_chart(user, chart):
    return can_manage_songs(user)


def songs_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not can_manage_songs(request.user):
            return HttpResponseForbidden("You do not have permission to access this page.")
        return view_func(request, *args, **kwargs)
    return wrapper

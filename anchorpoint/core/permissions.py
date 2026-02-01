"""
Centralized permission checks and decorators for AnchorPoint.

This module provides consistent authorization patterns across all views.
Use these decorators instead of manual permission checks in views.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def _get_user_profile(user):
    """Safely get user profile, returning None if not available."""
    if not user.is_authenticated:
        return None
    return getattr(user, "profile", None)


def is_admin(user):
    """Check if user has admin privileges."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _get_user_profile(user)
    return bool(profile and profile.is_admin)


def is_staff_or_above(user):
    """Check if user is staff or higher (staff, volunteer_admin, or admin)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _get_user_profile(user)
    if not profile:
        return False
    return profile.role in ("admin", "staff", "volunteer_admin")


def has_communications_access(user):
    """Check if user can manage SMS and phone blasts."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _get_user_profile(user)
    return bool(profile and profile.has_communications_access)


def admin_required(view_func):
    """
    Decorator that requires the user to be an admin.

    Usage:
        @admin_required
        def my_admin_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            return redirect("login")
        if not is_admin(request.user):
            return HttpResponseForbidden(
                "You do not have permission to access this page."
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def staff_required(view_func):
    """
    Decorator that requires the user to be staff or higher.

    Usage:
        @staff_required
        def my_staff_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            return redirect("login")
        if not is_staff_or_above(request.user):
            return HttpResponseForbidden(
                "You do not have permission to access this page."
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def communications_required(view_func):
    """
    Decorator that requires communications access.

    Usage:
        @communications_required
        def sms_compose(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            return redirect("login")
        if not has_communications_access(request.user):
            return HttpResponseForbidden(
                "You do not have permission to manage communications."
            )
        return view_func(request, *args, **kwargs)
    return wrapper

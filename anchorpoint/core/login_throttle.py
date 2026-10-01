"""Brute-force protection for password sign-in (app login + Django admin).

Counts failures per client IP and per account in the shared cache. Either
limit blocks further password attempts for the window. Google sign-in is not
affected, so an attacker hammering one account can't lock its owner out of
SSO.
"""
from django.core.cache import cache

from core.net import client_ip

LOGIN_FAIL_LIMIT = 10
LOGIN_FAIL_WINDOW = 15 * 60


def _keys(request, identifier):
    return (
        f"login-fail:ip:{client_ip(request) or 'unknown'}",
        f"login-fail:acct:{(identifier or '').strip().lower()}",
    )


def login_locked_out(request, identifier):
    return any(cache.get(k, 0) >= LOGIN_FAIL_LIMIT for k in _keys(request, identifier))


def record_login_failure(request, identifier):
    for key in _keys(request, identifier):
        if not cache.add(key, 1, LOGIN_FAIL_WINDOW):
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, LOGIN_FAIL_WINDOW)


def throttled_admin_login(request, extra_context=None):
    """Django admin's login view with the same lockout."""
    from django.contrib import admin
    from django.http import HttpResponse

    username = request.POST.get("username", "") if request.method == "POST" else ""
    if request.method == "POST" and login_locked_out(request, username):
        return HttpResponse(
            "Too many failed sign-in attempts. Please wait 15 minutes and try again.",
            status=429,
        )
    response = admin.site.login(request, extra_context=extra_context)
    if request.method == "POST" and not request.user.is_authenticated:
        record_login_failure(request, username)
    return response

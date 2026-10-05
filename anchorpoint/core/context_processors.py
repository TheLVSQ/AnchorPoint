from .models import OrganizationSettings


def organization_settings(request):
    return {
        "organization_settings": OrganizationSettings.load(),
        "family_flags_open": _family_flags_badge(request),
        "nav": _nav(request),
    }


# Longest prefix wins; values are the sidebar link keys.
_NAV_SECTIONS = [
    ("/families/review/", "family_review"),
    ("/people/", "people"),
    ("/families/", "families"),
    ("/groups/", "groups"),
    ("/checkin/", "checkin"),
    ("/events/manage/", "events"),
    ("/reports/", "reports"),
    ("/communications/", "messaging"),
    ("/users/", "users"),
    ("/permissions/", "permissions"),
    ("/settings/", "settings"),
    ("/profile/", "profile"),
    ("/help/", "help"),
]


def _nav(request):
    """What the sidebar may show this user (no links to pages that 403) and
    which section is active."""
    from core.permissions import (
        has_communications_access, is_admin, is_checkin_admin, is_staff_or_above,
    )
    user = getattr(request, "user", None)
    path = getattr(request, "path", "") or ""
    if path == "/":
        active = "dashboard"
    else:
        active = next((key for prefix, key in _NAV_SECTIONS if path.startswith(prefix)), "")
    if not user or not user.is_authenticated:
        return {"active": active}
    return {
        "active": active,
        "staff": is_staff_or_above(user),
        "checkin": is_checkin_admin(user),
        "comms": has_communications_access(user),
        "admin": is_admin(user),
    }


def _family_flags_badge(request):
    """Open family-safety flags, shown to alert recipients and admins only."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return 0
    from core.permissions import is_admin
    from households.family_flags import is_alert_recipient, open_flag_count
    if not (is_admin(user) or is_alert_recipient(user)):
        return 0
    return open_flag_count()

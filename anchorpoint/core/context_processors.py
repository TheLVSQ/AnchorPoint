from .models import OrganizationSettings


def organization_settings(request):
    return {
        "organization_settings": OrganizationSettings.load(),
        "family_flags_open": _family_flags_badge(request),
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

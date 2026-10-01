"""Shared kiosk test helpers."""
from core.models import OrganizationSettings
from households.models import Household

from checkin import views


def unlock_kiosk(session, households=None):
    """Mark a test-client session as a properly unlocked kiosk: unlocked now,
    with the current PIN, and allowed to open `households` (default: every
    household that exists right now — tests often open a family by id)."""
    session[views.KIOSK_SESSION_KEY] = True
    session[views.KIOSK_UNLOCKED_AT_KEY] = int(views.timezone.now().timestamp())
    session[views.KIOSK_PIN_FP_KEY] = views._pin_fingerprint(
        OrganizationSettings.load().kiosk_pin
    )
    if households is None:
        households = Household.objects.values_list("pk", flat=True)
    session[views.KIOSK_HOUSEHOLDS_KEY] = list(households)

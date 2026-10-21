"""Text the pickup security code to a family's adults at check-in.

Pickup tags get lost; text messages don't. Sends are best-effort and must never
block or fail a check-in — no Twilio config or no opted-in adult simply means
zero sends. Consent (Person.phone_opt_in) is enforced by the outbound
communications module; this is a transactional Communication, so it ignores
the blackout window.
"""

import logging

from core.models import OrganizationSettings
from households.models import HouseholdMember
from messaging import outbound
from messaging.models import Communication, Delivery

logger = logging.getLogger(__name__)


def send_security_code_sms(household, checkins, security_code, session) -> int:
    """Send the pickup code to every opted-in adult in the household.

    Returns the number of texts sent (0 on any configuration problem).
    """
    checkins = list(checkins)
    if not checkins or not security_code:
        return 0

    adults = [
        membership.person
        for membership in household.memberships.filter(
            relationship_type=HouseholdMember.RelationshipType.ADULT
        ).select_related("person")
    ]
    first_names = ", ".join(c.person.first_name for c in checkins)
    body = (
        f"{OrganizationSettings.load().name}: {first_names} checked in. "
        f"Pickup code: {security_code}"
    )
    try:
        comm = outbound.send_transactional(
            Communication.Channel.SMS,
            people=adults,
            body=body,
            title="Check-in pickup code",
            metadata={
                "security_code": security_code,
                "checkin_session_id": session.pk if session else None,
            },
        )
    except Exception:
        logger.exception("Check-in code SMS failed")
        return 0
    if comm is None:
        return 0
    return comm.deliveries.filter(status=Delivery.Status.SENT).count()

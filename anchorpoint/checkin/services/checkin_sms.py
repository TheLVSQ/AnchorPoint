"""Text the pickup security code to a family's adults at check-in.

Pickup tags get lost; text messages don't. Sends are best-effort and must never
block or fail a check-in — no Twilio config or no opted-in adult simply means
zero sends. Consent is the existing Person.phone_opt_in flag.
"""

import logging

from core.models import OrganizationSettings
from households.models import HouseholdMember
from messaging.models import CommunicationLog
from messaging.services import (
    TwilioConfigurationError,
    TwilioRequestError,
    TwilioService,
)

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
        if membership.person.phone and membership.person.phone_opt_in
    ]
    if not adults:
        return 0

    settings_obj = OrganizationSettings.load()
    try:
        service = TwilioService(settings_obj)
    except TwilioConfigurationError:
        return 0

    first_names = ", ".join(c.person.first_name for c in checkins)
    body = (
        f"{settings_obj.name}: {first_names} checked in. "
        f"Pickup code: {security_code}"
    )

    sent = 0
    for adult in adults:
        try:
            sid = service.send_sms(adult.phone, body)
        except (TwilioConfigurationError, TwilioRequestError) as exc:
            logger.warning(
                "Check-in code SMS to %s failed: %s", adult.phone, exc
            )
            continue
        sent += 1
        CommunicationLog.objects.create(
            person=adult,
            communication_type=CommunicationLog.CommunicationType.SMS,
            summary="Check-in pickup code",
            detail=body,
            metadata={
                "phone_number": adult.phone,
                "twilio_sid": sid,
                "security_code": security_code,
                "checkin_session_id": session.pk if session else None,
            },
            recorded_by=None,
        )
    return sent

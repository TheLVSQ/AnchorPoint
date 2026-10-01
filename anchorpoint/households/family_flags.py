"""Family-safety flags: a child already in one family linked to another.

Raised by public event registration when it matches an existing child and the
registering guardian isn't in any of the child's families. The link is applied
right away (so honest registrations aren't held up); designated staff are
alerted and can undo exactly what the registration changed.

Alert channels:
- flag raised (online registration): email + in-app badge/review page
- flagged child checked in at the kiosk: email + SMS, once per session
"""
import logging

from django.urls import reverse
from django.utils import timezone

from .models import FamilyConflictFlag, Household, HouseholdMember

logger = logging.getLogger(__name__)


def conflicting_households(child, guardian):
    """The child's existing families, if the guardian belongs to none of them
    (i.e. linking would attach the child to an outside family). Else []."""
    existing = list(Household.objects.filter(members=child).distinct())
    if not existing or guardian is None:
        return []
    if HouseholdMember.objects.filter(household__in=existing, person=guardian).exists():
        return []
    return existing


def record_registration_conflict(*, child, guardian, household, added_membership,
                                 prior_households, filled_fields, registration):
    flag = FamilyConflictFlag.objects.create(
        child=child,
        guardian=guardian,
        household=household,
        added_membership=added_membership,
        existing_households=", ".join(h.name for h in prior_households)[:500],
        filled_fields=filled_fields,
        registration=registration,
    )
    try:
        _email_recipients(
            subject=f"Family review needed: {child.first_name} {child.last_name}",
            body=_registration_message(flag),
        )
    except Exception:
        logger.exception("Family flag email failed (flag %s)", flag.pk)
    return flag


def open_flag_count():
    return FamilyConflictFlag.objects.filter(status=FamilyConflictFlag.STATUS_OPEN).count()


def is_alert_recipient(user):
    if not user.is_authenticated:
        return False
    from core.models import OrganizationSettings
    return OrganizationSettings.load().family_alert_recipients.filter(pk=user.pk).exists()


def undo_flag(flag, user):
    """Reverse exactly what the flagged registration changed: the new family
    membership, and any blank fields it filled (only if still unchanged)."""
    child = flag.child
    if flag.added_membership and flag.household_id:
        HouseholdMember.objects.filter(household_id=flag.household_id, person=child).delete()
    reverted = []
    for field, value in (flag.filled_fields or {}).items():
        current = getattr(child, field, None)
        if current is not None and str(current) == str(value):
            model_field = child._meta.get_field(field)
            setattr(child, field, None if model_field.null else "")
            reverted.append(field)
    if reverted:
        child.save(update_fields=reverted)
    _resolve(flag, user, FamilyConflictFlag.STATUS_UNDONE)


def mark_reviewed(flag, user):
    _resolve(flag, user, FamilyConflictFlag.STATUS_REVIEWED)


def _resolve(flag, user, status):
    flag.status = status
    flag.resolved_at = timezone.now()
    flag.resolved_by = user if user and user.is_authenticated else None
    flag.save(update_fields=["status", "resolved_at", "resolved_by"])


def alert_flagged_checkins(checkins, session):
    """Email + SMS the recipients when a child with an open flag is checked in.
    Once per flag per session. Best-effort: never raises."""
    by_person = {c.person_id: c for c in checkins}
    if not by_person:
        return 0
    flags = list(
        FamilyConflictFlag.objects.filter(
            status=FamilyConflictFlag.STATUS_OPEN, child_id__in=by_person,
        ).exclude(last_kiosk_alert_session_id=session.pk).select_related("child", "guardian")
    )
    sent = 0
    for flag in flags:
        checkin = by_person[flag.child_id]
        room = checkin.room.name if checkin.room_id else "no room"
        text = (
            f"Family alert: {flag.child.first_name} {flag.child.last_name} was just checked in "
            f"({room}, {session.name}). Open family review: {_review_url()}"
        )
        try:
            _email_recipients(
                subject=f"Flagged child checked in: {flag.child.first_name} {flag.child.last_name}",
                body=text + "\n\n" + _registration_message(flag),
            )
            _sms_recipients(text)
            sent += 1
        except Exception:
            logger.exception("Kiosk family alert failed (flag %s)", flag.pk)
        flag.last_kiosk_alert_session_id = session.pk
        flag.save(update_fields=["last_kiosk_alert_session_id"])
    return sent


# ---------------------------------------------------------------------------


def _recipients():
    from core.models import OrganizationSettings
    return list(
        OrganizationSettings.load().family_alert_recipients.filter(is_active=True)
        .select_related("profile", "profile__person")
    )


def _review_url():
    from messaging.services import get_site_base_url
    path = reverse("households:family_flags")
    base = get_site_base_url()
    return f"{base.rstrip('/')}{path}" if base else path


def _registration_message(flag):
    child = flag.child
    guardian = flag.guardian
    lines = [
        f"{child.first_name} {child.last_name} was already in: {flag.existing_households or 'another family'}.",
        f"A registration linked them to: {flag.household.name if flag.household else 'a new family'}"
        + (f" (registered by {guardian.first_name} {guardian.last_name})" if guardian else "") + ".",
    ]
    if flag.registration_id:
        lines.append(f"Event: {flag.registration.event.title}")
    if flag.filled_fields:
        lines.append("Filled blank fields: " + ", ".join(sorted(flag.filled_fields)))
    lines.append(f"Review or undo: {_review_url()}")
    return "\n".join(lines)


def _email_recipients(subject, body):
    from django.conf import settings
    from django.core.mail import send_mail
    emails = [u.email for u in _recipients() if u.email]
    if emails:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, emails, fail_silently=True)


def _sms_recipients(text):
    from core.models import OrganizationSettings
    from messaging.services import TwilioService, TwilioConfigurationError
    phones = []
    for user in _recipients():
        profile = getattr(user, "profile", None)
        phone = (profile.phone_number if profile else "") or (
            profile.person.phone if profile and profile.person_id else ""
        )
        if phone:
            phones.append(phone)
    if not phones:
        return
    try:
        service = TwilioService(OrganizationSettings.load())
    except TwilioConfigurationError:
        logger.warning("Family alert SMS skipped: Twilio not configured")
        return
    for phone in phones:
        try:
            service.send_sms(phone, text)
        except Exception:
            logger.exception("Family alert SMS to %s failed", phone)

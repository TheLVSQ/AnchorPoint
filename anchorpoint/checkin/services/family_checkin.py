"""Check a family in at the kiosk, stage families on the Pre-print page, and print
their labels (terms in GLOSSARY.md).

Interface:

- ``check_in_family(...)``  kiosk: pre-staged arrivals + walk-ins, then labels,
  pickup-code text, auto-enroll and the family-safety alert
- ``stage_families(...)``   Pre-print: create Expected check-ins (or reprint) per family
- ``confirm_arrivals(...)`` staff "mark arrived" on the manager page (+ safety alert)
- ``print_labels(...)``     the one way to print check-in labels

Pickup-code policy: a kiosk **walk-in** gets a FRESH code (one per submission, shared
by the siblings checked in together). The kiosk is self-service, so it must never
print or show a family's existing live code to whoever is standing there. Pre-print is
staff-only, so it reuses the family's active code to keep one code per family.
Pre-staged arrivals keep the code already printed on their tag.

Side effects (printing, texting, alerts, auto-enroll) are best-effort: a printer or
Twilio problem is logged and never blocks the check-in line.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone

from groups.models import GroupMembership
from households.family_flags import alert_flagged_checkins

from ..models import CheckIn, generate_unique_security_code
from .checkin_sms import send_security_code_sms
from .eligibility import match_room
from .print_queue import enqueue_checkin_labels

logger = logging.getLogger(__name__)


@dataclass
class KioskCheckIn:
    checkins: list = field(default_factory=list)  # everyone checked in by this submission
    printed: list = field(default_factory=list)  # new walk-in check-ins (need labels)
    new_code: str = ""  # the walk-in code minted now; "" if only pre-staged arrivals
    labels_queued: bool = False  # walk-in labels went to a print agent
    texted: bool = False  # at least one pickup-code text went out

    @property
    def needs_browser_print(self):
        """Walk-in labels exist but no print agent took them."""
        return bool(self.printed) and not self.labels_queued


@dataclass
class Staging:
    created: int = 0
    reprinted: int = 0
    families: int = 0


# --------------------------------------------------------------------------- public


def check_in_family(session, household, selections, *, agent=None) -> KioskCheckIn:
    """Kiosk check-in for one family. ``selections`` = [(person, room_or_None)].

    Pre-staged people (Expected or No-show) arrive and keep their printed code; nothing
    is reprinted. Everyone else is a walk-in: created Present with one fresh code for
    this submission, in the chosen room or else their age/grade-matched room."""
    result = KioskCheckIn()
    people = [person for person, _room in selections]
    prestaged = _prestaged(session, people)
    rooms = None
    walkin_code = None  # minted on the first walk-in; shown only if a new row holds it
    for person, room in selections:
        checkin = prestaged.get(person.pk)
        if checkin is not None:
            checkin.arrive()  # self check-in: no staff user to record
            result.checkins.append(checkin)
            continue
        if walkin_code is None:
            walkin_code = generate_unique_security_code(session)
        if room is None:
            rooms = rooms if rooms is not None else list(session.rooms.all())
            room = match_room(person, rooms)
        checkin, created = _create_active(session, person, room, walkin_code, arrived=True)
        if not created and checkin.state != CheckIn.State.PRESENT:
            checkin.arrive()  # raced a Pre-print of the same child: they're here now
        result.checkins.append(checkin)
        if created:
            result.printed.append(checkin)
            result.new_code = walkin_code

    _auto_enroll(session, people)
    if result.printed:
        result.labels_queued = print_labels(result.printed, session, agent=agent) > 0
    result.texted = _text_pickup_codes(household, result.checkins, session)
    _safety_alert(result.checkins, session)
    return result


def stage_families(session, selections) -> Staging:
    """Pre-print. ``selections`` = [(person, room_or_None)]. Grouped by family: anyone
    without an active check-in gets an Expected one (family code, chosen or matched
    room); anyone already active has their label reprinted with the code they hold."""
    people = [person for person, _room in selections]
    active = {c.person_id: c for c in session.checkins.active().filter(person__in=people)
              .select_related("person", "room")}
    buckets = defaultdict(list)
    for person, room in selections:
        household = person.primary_household
        buckets[household.pk if household else f"solo-{person.pk}"].append(
            (person, household, room)
        )

    staging = Staging()
    rooms = list(session.rooms.all())
    for entries in buckets.values():
        household = entries[0][1]
        code = None
        labels = []
        for person, _household, room in entries:
            existing = active.get(person.pk)
            if existing is None:
                code = code or _family_code(session, household)
                checkin, created = _create_active(
                    session, person, room or match_room(person, rooms), code, arrived=False
                )
                if created:
                    staging.created += 1
                else:
                    staging.reprinted += 1  # raced a kiosk check-in: reprint what exists
                labels.append(checkin)
            else:
                staging.reprinted += 1
                labels.append(existing)
        if labels:
            staging.families += 1
            print_labels(labels, session)
    return staging


def confirm_arrivals(session, checkins, user):
    """Manager "mark arrived" for a queryset of the session's check-ins. Records the
    staff member, then sends the family-safety alert for anyone who just arrived.
    Returns how many arrived."""
    arriving = list(
        (checkins.expected() | checkins.no_show()).filter(session=session)
        .values_list("pk", flat=True)
    )
    count = CheckIn.objects.filter(pk__in=arriving).arrive(user=user)
    if arriving:
        _safety_alert(
            CheckIn.objects.filter(pk__in=arriving).select_related("room", "person"), session
        )
    return count


def print_labels(checkins, session, *, agent=None) -> int:
    """Queue labels to a print agent: child labels plus ONE pickup tag PER CODE.
    Returns jobs queued (0 if no agent is online, or on error). Never raises."""
    checkins = list(checkins)
    if not checkins:
        return 0
    try:
        return enqueue_checkin_labels(checkins, session, agent=agent)
    except Exception:
        logger.exception("Failed to queue check-in labels")
        return 0


# --------------------------------------------------------------------------- internals


def _prestaged(session, people):
    """{person_id: check-in} for those pre-staged (Expected or No-show) this session."""
    return {
        c.person_id: c
        for c in (session.checkins.expected() | session.checkins.no_show())
        .filter(person__in=people)
        .select_related("room", "person")
    }


def _create_active(session, person, room, code, *, arrived):
    """Create the person's active check-in, or return the one a concurrent request
    just created (one active check-in per person per session). -> (checkin, created)"""
    try:
        with transaction.atomic():
            return CheckIn.objects.create(
                session=session, person=person, room=room, security_code=code,
                arrived_at=timezone.now() if arrived else None,
            ), True
    except IntegrityError:
        existing = session.checkins.active().filter(person=person).first()
        if existing is None:
            raise
        return existing, False


def _family_code(session, household):
    """The family's existing active code in this session (one code per family), else a
    fresh unique one. Staff-only paths only: never call this from the kiosk."""
    if household is not None:
        existing = (
            session.checkins.active()
            .filter(person__households=household)
            .exclude(security_code="")
            .first()
        )
        if existing:
            return existing.security_code
    return generate_unique_security_code(session)


def _auto_enroll(session, people):
    """Add everyone checked in to the configuration's auto-enroll group (e.g. VBS
    walk-ins land on the next day's Pre-print roster)."""
    group = session.configuration.auto_enroll_group if session.configuration else None
    if not group:
        return
    try:
        for person in people:
            GroupMembership.objects.get_or_create(group=group, person=person)
    except Exception:
        logger.exception("Check-in auto-enroll failed")


def _text_pickup_codes(household, checkins, session) -> bool:
    """One text per pickup code to the family's opted-in adults."""
    by_code = defaultdict(list)
    for checkin in checkins:
        by_code[checkin.security_code].append(checkin)
    sent = 0
    for code, group in by_code.items():
        try:
            sent += send_security_code_sms(household, group, code, session)
        except Exception:
            logger.exception("Pickup-code text failed")
    return sent > 0


def _safety_alert(checkins, session):
    """Alert staff when a child with an open family-conflict flag arrives."""
    try:
        alert_flagged_checkins(checkins, session)
    except Exception:
        logger.exception("Family-safety alert failed")

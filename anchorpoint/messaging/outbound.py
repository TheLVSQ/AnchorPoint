"""Outbound communications: the one place that decides who may be contacted, when, over
which channel, and records what happened (see GLOSSARY.md).

Interface:

- ``check_broadcast(...)``  compose-time problems (channel ready, recipients, time, blackout)
- ``broadcast(...)``        queue a staff-written Communication; never sends itself
- ``send_transactional(...)`` send an event-triggered Communication now (ignores blackout)
- ``dispatch_due(...)``     the scheduler's entry point: send every due broadcast
- ``record_call_status(...)`` settle a voice Delivery from Twilio's status callback
- ``channel_ready(...)``    is a channel configured (for compose-page banners)

Consent is re-checked when a broadcast is actually sent, not only when it was written:
someone who opts out after a text is scheduled is skipped, with the reason recorded.
"""
from dataclasses import dataclass, field

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.module_loading import import_string

from core.models import OrganizationSettings
from people.models import Person

from .adapters import DeliveryError
from .models import Communication, Delivery

Channel = Communication.Channel

# Which Person field holds the address, and which holds consent, per channel. Email gets
# its own entry (and an opt-in field) when the email channel lands.
_ADDRESS_FIELD = {Channel.SMS: "phone", Channel.VOICE: "phone"}
_CONSENT_FIELD = {Channel.SMS: "phone_opt_in", Channel.VOICE: "phone_opt_in"}

_NOT_READY = "Add your Twilio SID, auth token, and phone number in Organization Settings."

# Twilio CallStatus -> Delivery status. Anything else (ringing, in-progress) is ignored.
_CALL_STATUS = {
    "completed": Delivery.Status.ANSWERED,
    "no-answer": Delivery.Status.NO_ANSWER,
    "busy": Delivery.Status.FAILED,
    "failed": Delivery.Status.FAILED,
    "canceled": Delivery.Status.FAILED,
}


@dataclass(frozen=True)
class Problem:
    """Why a broadcast can't be sent. ``field`` names the compose-form field, or None."""

    field: str | None
    message: str


class BroadcastRejected(Exception):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(p.message for p in self.problems))


@dataclass
class DispatchReport:
    sent: list = field(default_factory=list)  # Communications that went out (or are ringing)
    failed: list = field(default_factory=list)  # Communications where every send failed
    deferred: int = 0  # due broadcasts held back by the blackout window


# --------------------------------------------------------------------------- public


def channel_ready(channel) -> bool:
    return _adapter(channel, OrganizationSettings.load()).ready()


def is_within_blackout_window(settings_obj: OrganizationSettings, moment) -> bool:
    start, end = settings_obj.sms_blackout_start, settings_obj.sms_blackout_end
    if not start or not end or start == end:
        return False
    now_time = timezone.localtime(moment).time()
    if start < end:
        return start <= now_time < end
    return now_time >= start or now_time < end  # overnight window


def check_broadcast(channel, *, person=None, group=None, scheduled_for=None, now=None):
    """Return the list of Problems that would stop this broadcast (empty = OK)."""
    settings_obj = OrganizationSettings.load()
    now = now or timezone.now()
    problems = []
    if not _adapter(channel, settings_obj).ready():
        problems.append(Problem(None, _NOT_READY))

    if person is not None:
        if not _address(person, channel):
            problems.append(Problem("person", "That person does not have a phone number."))
        elif not _consents(person, channel):
            problems.append(Problem("person", "This person has opted out of phone contact."))
    elif group is not None:
        if not _group_recipients(group, channel):
            problems.append(Problem(
                None, "Nobody in this group has a phone number with contact opt-in."
            ))
    else:
        problems.append(Problem(None, "Choose a person or a group to contact."))

    if scheduled_for:
        if scheduled_for < now:
            problems.append(Problem("scheduled_for", "Schedule time must be in the future."))
        elif is_within_blackout_window(settings_obj, scheduled_for):
            problems.append(Problem(
                "scheduled_for", "This time falls inside your configured blackout window."
            ))
    elif is_within_blackout_window(settings_obj, now):
        problems.append(Problem(
            None,
            "You are inside the configured blackout window. Choose a later send time.",
        ))
    return problems


def broadcast(channel, *, created_by, person=None, group=None, scheduled_for=None,
              title="", body="", audio_file=None, notes="") -> Communication:
    """Queue a staff-written Communication with one pending Delivery per consenting
    recipient. The scheduler (``dispatch_due``) sends it, at ``scheduled_for`` or within
    a minute. Raises BroadcastRejected if ``check_broadcast`` finds problems."""
    problems = check_broadcast(
        channel, person=person, group=group, scheduled_for=scheduled_for
    )
    if problems:
        raise BroadcastRejected(problems)
    recipients = [person] if person is not None else _group_recipients(group, channel)
    with transaction.atomic():
        comm = Communication.objects.create(
            channel=channel,
            kind=Communication.Kind.BROADCAST,
            status=Communication.Status.SCHEDULED,
            created_by=created_by,
            title=title,
            body=body,
            audio_file=audio_file or "",
            notes=notes,
            target_type=(
                Communication.TargetType.PERSON if person is not None
                else Communication.TargetType.GROUP
            ),
            person=person,
            group=group,
            scheduled_for=scheduled_for,
        )
        Delivery.objects.bulk_create(
            Delivery(communication=comm, person=p, address=_address(p, channel))
            for p in recipients
        )
    return comm


def send_transactional(channel, *, people, body, title="", metadata=None):
    """Send an event-triggered Communication now to whichever of ``people`` have an
    address and consent. Ignores the blackout window. Returns the Communication, or None
    (recording nothing) when the channel isn't configured or nobody can be contacted.
    Per-recipient send failures are recorded on the Delivery, never raised."""
    settings_obj = OrganizationSettings.load()
    adapter = _adapter(channel, settings_obj)
    if not adapter.ready():
        return None
    recipients = list({
        p.pk: p for p in people if _address(p, channel) and _consents(p, channel)
    }.values())
    if not recipients:
        return None
    with transaction.atomic():
        comm = Communication.objects.create(
            channel=channel,
            kind=Communication.Kind.TRANSACTIONAL,
            status=Communication.Status.SENDING,
            title=title,
            body=body,
            metadata=metadata or {},
            started_at=timezone.now(),
        )
        Delivery.objects.bulk_create(
            Delivery(communication=comm, person=p, address=_address(p, channel))
            for p in recipients
        )
    _send_pending(comm, adapter, recheck_consent=False)
    return comm


def dispatch_due(now=None) -> DispatchReport:
    """Send every broadcast that is due. Run by ``process_communications`` each minute."""
    settings_obj = OrganizationSettings.load()
    now = now or timezone.now()
    report = DispatchReport()
    due = (
        Communication.objects.filter(
            kind=Communication.Kind.BROADCAST, status=Communication.Status.SCHEDULED
        )
        .filter(Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=now))
        .order_by("created_at")
    )
    if is_within_blackout_window(settings_obj, now):
        report.deferred = due.count()
        return report

    for comm in due:
        # Claim it, so an overlapping scheduler run can't send it twice.
        claimed = Communication.objects.filter(
            pk=comm.pk, status=Communication.Status.SCHEDULED
        ).update(status=Communication.Status.SENDING, started_at=now, updated_at=now)
        if not claimed:
            continue
        comm.refresh_from_db()
        adapter = _adapter(comm.channel, settings_obj)
        if adapter.ready():
            _send_pending(comm, adapter, recheck_consent=True)
        else:
            comm.deliveries.filter(status=Delivery.Status.PENDING).update(
                status=Delivery.Status.FAILED, error_message=_NOT_READY, completed_at=now
            )
            _settle(comm, attempted=1, sent=0)
        (report.failed if comm.status == Communication.Status.FAILED else report.sent).append(comm)
    return report


def record_call_status(provider_id, provider_status):
    """Apply a Twilio call-status callback. Returns the Delivery, or None if unknown."""
    delivery = (
        Delivery.objects.select_related("communication")
        .filter(provider_id=provider_id, communication__channel=Channel.VOICE)
        .first()
    ) if provider_id else None
    if delivery is None:
        return None
    new_status = _CALL_STATUS.get(provider_status)
    if new_status:
        now = timezone.now()
        delivery.status = new_status
        delivery.completed_at = now
        delivery.save(update_fields=["status", "completed_at"])
        comm = delivery.communication
        still_open = comm.deliveries.filter(
            status__in=[Delivery.Status.PENDING, Delivery.Status.SENT]
        ).exists()
        if comm.status == Communication.Status.SENDING and not still_open:
            comm.status = Communication.Status.COMPLETED
            comm.completed_at = now
            comm.save(update_fields=["status", "completed_at", "updated_at"])
    return delivery


# --------------------------------------------------------------------------- internals


def _adapter(channel, settings_obj):
    path = django_settings.OUTBOUND_ADAPTERS.get(channel)
    if not path:
        raise ValueError(f"No outbound adapter configured for channel {channel!r}")
    return import_string(path)(settings_obj)


def _address(person, channel) -> str:
    return (getattr(person, _ADDRESS_FIELD[channel]) or "").strip()


def _consents(person, channel) -> bool:
    return bool(getattr(person, _CONSENT_FIELD[channel]))


def _group_recipients(group, channel):
    people = Person.objects.filter(group_memberships__group=group).distinct()
    return [p for p in people if _address(p, channel) and _consents(p, channel)]


def _send_pending(comm, adapter, *, recheck_consent):
    sent = failed = 0
    for delivery in comm.deliveries.filter(status=Delivery.Status.PENDING).select_related("person"):
        delivery.communication = comm
        if recheck_consent:
            person = delivery.person
            address = _address(person, comm.channel) if person else ""
            if not address:
                _skip(delivery, Delivery.SkipReason.NO_ADDRESS)
                continue
            if not _consents(person, comm.channel):
                _skip(delivery, Delivery.SkipReason.OPTED_OUT)
                continue
            delivery.address = address  # they may have updated their number since
        try:
            provider_id = adapter.send(delivery)
        except DeliveryError as exc:
            delivery.status = Delivery.Status.FAILED
            delivery.error_message = str(exc)
            delivery.completed_at = timezone.now()
            delivery.save(update_fields=["address", "status", "error_message", "completed_at"])
            failed += 1
            continue
        delivery.status = Delivery.Status.SENT
        delivery.provider_id = provider_id or ""
        delivery.sent_at = timezone.now()
        delivery.save(update_fields=["address", "status", "provider_id", "sent_at"])
        sent += 1
    _settle(comm, attempted=sent + failed, sent=sent)


def _skip(delivery, reason):
    delivery.status = Delivery.Status.SKIPPED
    delivery.skip_reason = reason
    delivery.completed_at = timezone.now()
    delivery.save(update_fields=["status", "skip_reason", "completed_at"])


def _settle(comm, *, attempted, sent):
    """Voice stays SENDING while calls ring (the status callback finishes it); otherwise
    FAILED if every attempt failed, else COMPLETED (including "everyone was skipped")."""
    ringing = comm.channel == Channel.VOICE and comm.deliveries.filter(
        status=Delivery.Status.SENT
    ).exists()
    if ringing:
        comm.status = Communication.Status.SENDING
    else:
        comm.status = (
            Communication.Status.FAILED if attempted and not sent
            else Communication.Status.COMPLETED
        )
        comm.completed_at = timezone.now()
    comm.save(update_fields=["status", "completed_at", "updated_at"])

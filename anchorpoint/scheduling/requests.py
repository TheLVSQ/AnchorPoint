"""Schedule requests, answers and reminders.

1. Staff build the grid: new assignments are **drafts** (only staff see them).
2. "Send requests" (`queue_requests`) marks a service type's upcoming drafts as requested.
   From then on the volunteer sees them (My serving, the dashboard, the emailed link).
3. `send_due()` (cron, every minute) emails each person once, listing their new dates with
   a link to answer. Emails go out from the cron, never inside a web request: a VBS-sized
   batch over SMTP would outlast the request timeout.
4. The person accepts or declines (`respond`): on My serving when logged in, or through the
   emailed link without a login (one-time VBS volunteers). A decline emails whoever
   scheduled them.
5. `send_due()` also sends one reminder `REMINDER_DAYS` before the date (not overnight).

Email is the only channel (system email; consent = `Person.email_opt_in`). People who can't
be emailed are flagged in the grid ("No email") so staff tell them another way.
"""
from datetime import time, timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from messaging import outbound
from messaging.models import Communication
from messaging.services import get_site_base_url
from people.models import Person

from .models import Assignment

EMAIL = Communication.Channel.EMAIL
REMINDER_DAYS = 3
REMINDER_EARLIEST_HOUR = 8  # local time
RESPOND_LINK_DAYS = 90
_RESPOND_SALT = "scheduling.respond"  # never the unsubscribe salt: tokens mustn't cross over


class NotReady(Exception):
    """Requests can't be emailed right now (message is shown to staff as-is)."""


def can_email(person):
    return outbound.reachable(person, EMAIL)


def visible_to_volunteer(qs):
    """Assignments the volunteer can see: requested, i.e. not a staff draft."""
    return qs.filter(requested_at__isnull=False)


def upcoming_for(person, today=None):
    today = today or timezone.localdate()
    return (visible_to_volunteer(Assignment.objects.filter(person=person, plan__date__gte=today))
            .select_related("plan__service_type", "position__group")
            .order_by("plan__date", "plan__time", "position__name"))


def drafts(service_type, team=None, today=None):
    """Upcoming assignments on `service_type` (optionally one team's) that haven't been sent
    to the volunteer."""
    today = today or timezone.localdate()
    qs = Assignment.objects.filter(plan__service_type=service_type, plan__date__gte=today,
                                   requested_at__isnull=True)
    return qs.filter(position__group=team) if team else qs


def check_ready():
    if not outbound.channel_ready(EMAIL):
        raise NotReady("Email isn't set up (no from address), so requests can't be sent.")
    if not get_site_base_url():
        raise NotReady("The site address isn't set (SITE_BASE_URL or Settings → Organization → "
                       "Website), so the emailed answer links wouldn't work.")


def queue_requests(service_type, team=None, now=None):
    """Mark the service type's upcoming drafts (only `team`'s, if given: another team may
    still be building theirs) as requested; the cron emails them within a minute.
    Returns (people asked, those of them who can't be emailed)."""
    check_ready()
    now = now or timezone.now()
    qs = drafts(service_type, team)
    people = list(Person.objects.filter(pk__in=qs.values("person_id"))
                  .order_by("first_name", "last_name"))
    qs.update(requested_at=now)
    return people, [p for p in people if not can_email(p)]


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------

def respond_url(person, base_url):
    token = signing.dumps(person.pk, salt=_RESPOND_SALT)
    return f"{base_url}{reverse('scheduling:respond', args=[token])}"


def person_from_token(token):
    """The person a respond link was made for, or None (tampered, expired, or not ours)."""
    try:
        pk = signing.loads(token, salt=_RESPOND_SALT, max_age=timedelta(days=RESPOND_LINK_DAYS))
    except signing.BadSignature:
        return None
    return Person.objects.filter(pk=pk).first()


class TooLate(Exception):
    pass


def respond(assignment, *, accept, reason=""):
    """Record the volunteer's answer. Raises TooLate once the date has passed."""
    if assignment.plan.date < timezone.localdate():
        raise TooLate("That date has passed.")
    new = Assignment.Status.ACCEPTED if accept else Assignment.Status.DECLINED
    changed = assignment.status != new
    assignment.status = new
    assignment.decline_reason = "" if accept else reason.strip()[:200]
    assignment.responded_at = timezone.now()
    assignment.save(update_fields=["status", "decline_reason", "responded_at"])
    if changed and not accept:
        _tell_scheduler(assignment)
    return assignment


def _tell_scheduler(assignment):
    """Staff alert (not a Communication): whoever scheduled them hears about a decline."""
    staff = assignment.created_by
    if not staff or not staff.email or not settings.DEFAULT_FROM_EMAIL:
        return
    plan, person = assignment.plan, assignment.person
    lines = [f"{person.first_name} {person.last_name} can't serve {assignment.position} "
             f"({assignment.position.group}) on {_when(plan)}, {plan.service_type}."]
    if assignment.decline_reason:
        lines.append(f'They said: "{assignment.decline_reason}"')
    base = get_site_base_url()
    if base:
        lines.append(f"Find someone else: {base}{reverse('scheduling:plan_detail', args=[plan.pk])}")
    send_mail(f"{person.first_name} declined {assignment.position} on {plan.date:%b %-d}",
              "\n\n".join(lines), settings.DEFAULT_FROM_EMAIL, [staff.email],
              fail_silently=True)


# ---------------------------------------------------------------------------
# The cron: request and reminder emails
# ---------------------------------------------------------------------------

def _when(plan):
    text = plan.date.strftime("%A, %b %-d")
    if plan.time:
        text += plan.time.strftime(" at %-I:%M %p")
    return text


def _line(a):
    return f"- {_when(a.plan)}: {a.position} ({a.position.group}), {a.plan.service_type}"


def _claim(qs, field, now):
    """Stamp `field` on each row still unstamped, returning the rows this run claimed, so two
    overlapping cron runs never email the same thing twice."""
    mine = []
    for a in qs.select_related("person", "plan__service_type", "position__group"):
        if Assignment.objects.filter(pk=a.pk, **{f"{field}__isnull": True}).update(**{field: now}):
            mine.append(a)
    return mine


def _by_person(assignments):
    grouped = {}
    for a in sorted(assignments, key=lambda a: (a.plan.date, a.plan.time or time.min)):
        grouped.setdefault(a.person_id, []).append(a)
    return grouped.values()


def _request_email(person, assignments, base_url):
    first = assignments[0].plan
    subject = (f"Can you serve on {first.date:%b %-d}?" if len(assignments) == 1
               else f"Can you serve? {len(assignments)} dates")
    body = "\n".join([
        f"Hi {person.first_name},", "",
        "You've been scheduled to serve:", "",
        *[_line(a) for a in assignments], "",
        "Please let us know if you can make it:",
        respond_url(person, base_url), "",
        "Thank you for serving!",
    ])
    return subject, body


def _reminder_email(person, assignments, base_url):
    first = assignments[0].plan
    unanswered = [a for a in assignments if a.status == Assignment.Status.PENDING]
    lines = [f"Hi {person.first_name},", "",
             "A reminder that you're serving soon:", "",
             *[_line(a) for a in assignments], ""]
    if unanswered:
        lines += ["You haven't said yet whether you can make it. Let us know here:",
                  respond_url(person, base_url), ""]
    else:
        lines += ["Can't make it after all? Let us know here:", respond_url(person, base_url), ""]
    lines.append("Thank you for serving!")
    return f"Reminder: you're serving {_when(first)}", "\n".join(lines)


def send_due(now=None):
    """Email due requests and reminders. Returns (requests, reminders) emails sent."""
    if not outbound.channel_ready(EMAIL):
        return 0, 0
    base_url = get_site_base_url()
    if not base_url:
        return 0, 0
    now = now or timezone.now()
    today = timezone.localdate(now)
    upcoming = visible_to_volunteer(Assignment.objects.filter(plan__date__gte=today))

    requests_sent = 0
    # Pending only: they may have answered on My serving before the email went out.
    due = upcoming.filter(request_sent_at__isnull=True, status=Assignment.Status.PENDING)
    for assignments in _by_person(_claim(due, "request_sent_at", now)):
        person = assignments[0].person
        subject, body = _request_email(person, assignments, base_url)
        if outbound.send_transactional(EMAIL, people=[person], subject=subject, body=body,
                                       title="Schedule request",
                                       metadata={"assignments": [a.pk for a in assignments]}):
            requests_sent += 1

    reminders_sent = 0
    if timezone.localtime(now).hour >= REMINDER_EARLIEST_HOUR:
        # Not for a request sent in the last day: they've just had an email. (requested_at,
        # not request_sent_at: someone who answered before the email went out has none.)
        due = (upcoming.filter(plan__date__lte=today + timedelta(days=REMINDER_DAYS),
                               reminded_at__isnull=True,
                               requested_at__lte=now - timedelta(days=1))
               .exclude(status=Assignment.Status.DECLINED))
        for assignments in _by_person(_claim(due, "reminded_at", now)):
            person = assignments[0].person
            subject, body = _reminder_email(person, assignments, base_url)
            if outbound.send_transactional(EMAIL, people=[person], subject=subject, body=body,
                                           title="Serving reminder",
                                           metadata={"assignments": [a.pk for a in assignments]}):
                reminders_sent += 1
    return requests_sent, reminders_sent

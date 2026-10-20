"""Public, read-only event feeds for the church website (JSON + iCalendar).

Only what the public event pages already show goes out: published events with
an upcoming occurrence, and none of the contact, capacity, registration or
release-document fields. The repo is public, so assume the endpoint is known.
"""
import hashlib
import json
from datetime import timedelta, timezone as dt_timezone

from django.db.models import Prefetch
from django.urls import reverse
from django.utils import timezone

from .models import Event, EventOccurrence

# Per event, in the JSON feed. Recurring events can have a long tail.
MAX_OCCURRENCES_PER_EVENT = 10
# iCalendar feed horizon.
ICS_HORIZON_DAYS = 365


def upcoming_events():
    """Same set as the public events list, with upcoming occurrences prefetched."""
    now = timezone.now()
    events = (
        Event.objects.upcoming()
        .prefetch_related(
            Prefetch(
                "occurrences",
                queryset=EventOccurrence.objects.filter(starts_at__gte=now).order_by("starts_at"),
                to_attr="upcoming_occurrence_list",
            ),
            "photos",
        )
    )
    # Soonest first, by the next *upcoming* occurrence (not the first ever).
    events = [e for e in events if e.upcoming_occurrence_list]
    return sorted(events, key=lambda e: (e.upcoming_occurrence_list[0].starts_at, e.id))


def _detail_path(event):
    return reverse("events:public_detail", args=[event.slug])


def feed_items(build_url):
    """JSON-ready dicts, one per event. ``build_url(path)`` makes an absolute URL."""
    items = []
    for event in upcoming_events():
        occurrences = event.upcoming_occurrence_list[:MAX_OCCURRENCES_PER_EVENT]
        photos = sorted(event.photos.all(), key=lambda p: (p.display_order, p.id))
        items.append(
            {
                "title": event.title,
                "slug": event.slug,
                "summary": event.summary,
                "url": build_url(_detail_path(event)),
                "next_start": occurrences[0].starts_at.isoformat(),
                "occurrences": [
                    {
                        "starts_at": o.starts_at.isoformat(),
                        "ends_at": o.ends_at.isoformat() if o.ends_at else None,
                        "is_all_day": o.is_all_day,
                    }
                    for o in occurrences
                ],
                "location_name": event.location_name,
                "location_city": event.location_city,
                "photo_url": build_url(photos[0].image.url) if photos else None,
                "is_free": event.is_free or not event.cost_amount,
                "cost_display": event.display_cost,
                "registration_open": event.can_register(),
            }
        )
    return items


def feed_hash(items):
    """Stable fingerprint of the feed, so the rebuild trigger can spot changes."""
    payload = json.dumps(items, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


# ---- iCalendar ---------------------------------------------------------------


def _ics_escape(value):
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _ics_fold(line):
    """Fold to 75-octet lines (RFC 5545 §3.1) without splitting a UTF-8 character."""
    out, current = [], ""
    for char in line:
        limit = 75 if not out else 74  # continuation lines start with a space
        if len((current + char).encode()) > limit:
            out.append(current)
            current = char
        else:
            current += char
    out.append(current)
    return "\r\n ".join(out)


def _utc(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_calendar(build_url, calendar_name):
    now = timezone.now()
    horizon = now + timedelta(days=ICS_HORIZON_DAYS)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AnchorPoint//Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
        "X-WR-TIMEZONE:America/New_York",
    ]
    for event in upcoming_events():
        url = build_url(_detail_path(event))
        description = "\n\n".join(filter(None, [event.summary, url]))
        location = ", ".join(filter(None, [event.location_name, event.location_city]))
        for occ in event.upcoming_occurrence_list:
            if occ.starts_at > horizon:
                break
            lines += ["BEGIN:VEVENT", f"UID:event-occurrence-{occ.pk}@anchorpoint", f"DTSTAMP:{_utc(now)}"]
            if occ.is_all_day:
                start = timezone.localtime(occ.starts_at).date()
                end = timezone.localtime(occ.ends_at).date() if occ.ends_at else start
                lines += [
                    f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                    f"DTEND;VALUE=DATE:{end + timedelta(days=1):%Y%m%d}",
                ]
            else:
                lines.append(f"DTSTART:{_utc(occ.starts_at)}")
                if occ.ends_at:
                    lines.append(f"DTEND:{_utc(occ.ends_at)}")
            lines += [f"SUMMARY:{_ics_escape(event.title)}", f"URL:{url}"]
            if location:
                lines.append(f"LOCATION:{_ics_escape(location)}")
            if description:
                lines.append(f"DESCRIPTION:{_ics_escape(description)}")
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"

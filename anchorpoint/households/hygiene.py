"""Nightly people/family hygiene: find likely duplicates and orphaned families.

Writes ``CleanupFinding`` rows (the admin "Data cleanup" queue). Runs nightly
from the cron sidecar (``manage.py family_hygiene``) and again right after an
admin acts on a finding, so a merge that creates a new duplicate shows up at once.

Rules are deliberately conservative — a false "duplicate" costs an admin a
click, a wrong merge costs a family their records:

People (a pair must share a first name; two different birthdates veto it, which
keeps Jr/Sr apart; twins differ by first name so never pair):
- same last name + any of birthdate / email / phone / family / address
- different last name + at least two of birthdate / email / phone / family / address

Families:
- never pair two families imported with different external ids
- same street address (line 1 + 2, ZIP or city), or same phone
- same name + a shared adult member
(A shared *child* is not a signal — shared custody puts kids in two families.)

Orphans: a family with no members, or members but no adult (by role or age).
"""
import re
from collections import defaultdict
from itertools import combinations

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from people.models import Person, normalize_phone

from .models import CleanupFinding, Household, HouseholdMember

F = CleanupFinding


def _norm(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _address_key(obj):
    line1 = _norm(getattr(obj, "address_line1", ""))
    if not line1:
        return ""
    where = (getattr(obj, "postal_code", "") or "").strip()[:5] or _norm(getattr(obj, "city", ""))
    if not where:
        return ""
    line1 = re.sub(r"[.,#]", "", line1)
    return "|".join([line1, re.sub(r"[.,#]", "", _norm(getattr(obj, "address_line2", ""))), where])


# ---------------------------------------------------------------------------
# Detection


def _person_signals(a, b, fams):
    signals = []
    if a.birthdate and b.birthdate:
        if a.birthdate != b.birthdate:
            return None  # different people (Jr/Sr, cousins)
        signals.append("birthdate")
    if a.email and b.email and _norm(a.email) == _norm(b.email):
        signals.append("email")
    if a.normalized_phone and len(a.normalized_phone) >= 7 and a.normalized_phone == b.normalized_phone:
        signals.append("phone")
    if fams.get(a.pk, set()) & fams.get(b.pk, set()):
        signals.append("family")
    addr = _address_key(a)
    if addr and addr == _address_key(b):
        signals.append("address")
    same_last = _norm(a.last_name) == _norm(b.last_name)
    if same_last and signals:
        return ["name"] + signals
    if not same_last and len(signals) >= 2:
        return ["first name"] + signals
    return None


def _duplicate_people():
    fams = defaultdict(set)
    for person_id, household_id in HouseholdMember.objects.values_list("person_id", "household_id"):
        fams[person_id].add(household_id)
    by_first = defaultdict(list)
    for p in Person.objects.only(
        "first_name", "last_name", "birthdate", "email", "normalized_phone",
        "address_line1", "address_line2", "city", "postal_code",
    ):
        if _norm(p.first_name):
            by_first[_norm(p.first_name)].append(p)
    out = []
    for group in by_first.values():
        for a, b in combinations(sorted(group, key=lambda p: p.pk), 2):
            signals = _person_signals(a, b, fams)
            if signals:
                out.append({
                    "kind": F.KIND_DUPLICATE_PERSON,
                    "key": f"person:{a.pk}:{b.pk}",
                    "person_a": a, "person_b": b,
                    "label": f"{a.first_name} {a.last_name} / {b.first_name} {b.last_name}",
                    "reasons": "Same " + ", ".join(signals),
                })
    return out


def _households_with_people():
    return list(
        Household.objects.prefetch_related("memberships__person").order_by("pk")
    )


def _duplicate_households(households):
    adults = {
        h.pk: {m.person_id for m in h.memberships.all() if m.relationship_type == HouseholdMember.RelationshipType.ADULT}
        for h in households
    }
    by_addr, by_phone, by_name = defaultdict(list), defaultdict(list), defaultdict(list)
    for h in households:
        if _address_key(h):
            by_addr[_address_key(h)].append(h)
        phone = normalize_phone(h.phone)
        if len(phone) >= 7:
            by_phone[phone].append(h)
        by_name[_norm(h.name)].append(h)

    pairs = defaultdict(list)
    for bucket, reason in ((by_addr, "address"), (by_phone, "phone")):
        for group in bucket.values():
            for a, b in combinations(group, 2):
                pairs[(a, b)].append(reason)
    for group in by_name.values():
        for a, b in combinations(group, 2):
            if adults[a.pk] & adults[b.pk]:
                pairs[(a, b)].append("name + shared adult")

    out = []
    for (a, b), reasons in pairs.items():
        if a.external_id and b.external_id and a.external_id != b.external_id:
            continue  # two real families in the source system
        out.append({
            "kind": F.KIND_DUPLICATE_HOUSEHOLD,
            "key": f"household:{a.pk}:{b.pk}",
            "household_a": a, "household_b": b,
            "label": f"{a.name} / {b.name}",
            "reasons": "Same " + ", ".join(reasons),
        })
    return out


def _orphan_households(households):
    out = []
    for h in households:
        members = list(h.memberships.all())
        if not members:
            out.append({
                "kind": F.KIND_EMPTY_HOUSEHOLD, "key": f"empty:{h.pk}",
                "household_a": h, "label": h.name, "reasons": "No members",
            })
        elif not any(
            m.relationship_type == HouseholdMember.RelationshipType.ADULT
            or (m.person.age is not None and m.person.age >= 18)
            for m in members
        ):
            out.append({
                "kind": F.KIND_NO_ADULT_HOUSEHOLD, "key": f"noadult:{h.pk}",
                "household_a": h, "label": h.name,
                "reasons": f"{len(members)} member{'s' if len(members) != 1 else ''}, no adult",
            })
    return out


def detect():
    households = _households_with_people()
    return _duplicate_people() + _duplicate_households(households) + _orphan_households(households)


# ---------------------------------------------------------------------------
# Queue


LAST_RUN_CACHE_KEY = "hygiene:last_run"
_FK_FIELDS = ("person_a", "person_b", "household_a", "household_b")


@transaction.atomic
def run(dry_run=False):
    """Detect and sync the queue. Returns counts by kind (+ opened/resolved)."""
    found = detect()
    counts = defaultdict(int)
    for f in found:
        counts[f["kind"]] += 1
    if dry_run:
        return dict(counts)

    now = timezone.now()
    existing = {f.key: f for f in CleanupFinding.objects.filter(key__in=[x["key"] for x in found])}
    for item in found:
        finding = existing.get(item["key"])
        values = {k: item.get(k) for k in _FK_FIELDS}
        values.update(kind=item["kind"], label=item["label"][:255], reasons=item["reasons"][:255])
        if finding is None:
            CleanupFinding.objects.create(key=item["key"], last_seen_at=now, **values)
            counts["opened"] += 1
            continue
        for k, v in values.items():
            setattr(finding, k, v)
        finding.last_seen_at = now
        if finding.status == F.STATUS_RESOLVED:  # it came back
            finding.status, finding.resolution, finding.resolved_at, finding.resolved_by = F.STATUS_OPEN, "", None, None
            counts["opened"] += 1
        finding.save()

    cache.set(LAST_RUN_CACHE_KEY, now, None)
    stale = CleanupFinding.objects.filter(status=F.STATUS_OPEN).exclude(key__in=[x["key"] for x in found])
    counts["resolved"] = stale.update(
        status=F.STATUS_RESOLVED, resolution="No longer applies", resolved_at=now, resolved_by=None,
    )
    return dict(counts)


def last_run():
    return cache.get(LAST_RUN_CACHE_KEY)


def open_count():
    return CleanupFinding.objects.filter(status=F.STATUS_OPEN).count()


def resolve(finding, user, status, resolution):
    finding.status = status
    finding.resolution = resolution[:255]
    finding.resolved_at = timezone.now()
    finding.resolved_by = user if user and user.is_authenticated else None
    finding.save(update_fields=["status", "resolution", "resolved_at", "resolved_by"])


# ---------------------------------------------------------------------------
# Review-page details


def person_card(person):
    if person is None:
        return None
    from core.models import UserProfile
    return {
        "obj": person,
        "families": list(person.households.order_by("name")),
        "checkins": person.checkins.count(),
        "registrations": person.event_registrations.count(),
        "groups": person.group_memberships.count(),
        "has_login": UserProfile.objects.filter(person=person).exists(),
    }


def household_card(household):
    if household is None:
        return None
    members = list(
        household.memberships.select_related("person").order_by("relationship_type", "person__first_name")
    )
    return {"obj": household, "members": members}


def counts_by_kind():
    rows = (
        CleanupFinding.objects.filter(status=F.STATUS_OPEN)
        .values("kind").annotate(n=Count("id"))
    )
    labels = dict(F.KIND_CHOICES)
    got = {r["kind"]: r["n"] for r in rows}
    return [{"kind": k, "label": labels[k], "count": got.get(k, 0)} for k, _ in F.KIND_CHOICES]

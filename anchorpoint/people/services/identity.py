"""Person identity: "is this incoming record someone we already have?" (GLOSSARY.md).

Every intake path asks here: public registration, the staff match queue, signup and
Rock imports, kiosk add-child. Interface:

- ``find_person(incoming, family=None)`` -> Match | None
- ``find_or_create(incoming, fields, family=None)`` -> (person, Match | None)
- ``absorb(person, fields)``  apply incoming data to a matched person
- ``phone_key(raw)`` / ``same_phone(a, b)``  the one phone-equality rule

Bias: a wrong match writes one person's details (allergies, birthdate, grade) onto
someone else; a missed match only lands in the staff queue or becomes a duplicate the
nightly cleanup finds. So every automatic match needs the FIRST NAME to agree (email
and phone are shared within families), a different birthdate rules a candidate out,
and two or more candidates at a step is "don't know" (None), never a guess.
"""
from dataclasses import dataclass
from datetime import date

from django.db.models import Q

from people.models import Person, normalize_phone

# Blank fields are filled from incoming data; never overwrite a value we already have.
FILL_FIELDS = [
    "email", "phone", "birthdate", "grade", "gender", "marital_status",
    "address_line1", "address_line2", "city", "state", "postal_code",
    "salvation_date", "baptism_date", "first_visit_date",
    "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
]
# Safety / notes text is ADDED TO, never dropped: losing a second allergy or a custody
# note would be a check-in safety gap.
APPEND_FIELDS = ["allergies", "security_notes", "notes", "custody_notes", "unauthorized_pickup"]

FILLED, APPENDED = "filled", "appended"


@dataclass(frozen=True)
class Incoming:
    first_name: str
    last_name: str = ""
    email: str = ""
    phone: str = ""
    birthdate: date | None = None
    external_id: str = ""


@dataclass(frozen=True)
class Match:
    person: Person
    matched_by: str  # "external id" | "email" | "name + birthdate" | "phone" | "family"


def phone_key(raw) -> str:
    """Last 10 digits, so "+1 (555) 123-4567" and "555-123-4567" agree. "" if fewer."""
    digits = normalize_phone(raw or "")
    return digits[-10:] if len(digits) >= 10 else ""


def same_phone(a, b) -> bool:
    key = phone_key(a)
    return bool(key) and key == phone_key(b)


def find_person(incoming: Incoming, family=None):
    """The existing Person this incoming record is, or None if no single safe answer.

    Order: external id, then (first name required from here) email, name + birthdate,
    phone, and finally the same name inside ``family`` (a Household or a queryset of
    them) for people with no other identifying data, e.g. VBS kids."""
    external_id = (incoming.external_id or "").strip()
    if external_id:
        found = _only(Person.objects.filter(external_id=external_id))
        if found is not _NONE:
            return Match(found, "external id") if found else None

    first = (incoming.first_name or "").strip()
    if not first:
        return None
    candidates = Person.objects.filter(first_name__iexact=first)
    if incoming.birthdate:
        # A different birthdate is a different person (Jr/Sr, cousins).
        candidates = candidates.filter(Q(birthdate__isnull=True) | Q(birthdate=incoming.birthdate))
    last = (incoming.last_name or "").strip()

    steps = []
    email = (incoming.email or "").strip()
    if email:
        steps.append(("email", candidates.filter(email__iexact=email)))
    if last and incoming.birthdate:
        steps.append(("name + birthdate",
                      candidates.filter(last_name__iexact=last, birthdate=incoming.birthdate)))
    key = phone_key(incoming.phone)
    if key:
        steps.append(("phone", candidates.filter(normalized_phone__endswith=key)))
    if family is not None and last:
        steps.append(("family", candidates.filter(
            last_name__iexact=last, households__in=_households(family),
        )))

    for matched_by, qs in steps:
        found = _only(qs.distinct())
        if found is _NONE:
            continue
        return Match(found, matched_by) if found else None  # ambiguous -> None
    return None


def find_or_create(incoming: Incoming, fields=None, family=None):
    """-> (person, Match | None). On a match, absorb ``fields``; otherwise create a
    Person from ``incoming`` plus ``fields``."""
    fields = dict(fields or {})
    match = find_person(incoming, family=family)
    if match:
        absorb(match.person, {
            "email": incoming.email, "phone": incoming.phone,
            "birthdate": incoming.birthdate, **fields,
        })
        if incoming.external_id and not match.person.external_id:
            match.person.external_id = incoming.external_id
            match.person.save(update_fields=["external_id"])
        return match.person, match
    person = Person.objects.create(
        first_name=incoming.first_name,
        last_name=incoming.last_name,
        email=incoming.email or None,
        phone=incoming.phone or None,
        birthdate=incoming.birthdate,
        external_id=incoming.external_id or "",
        **{k: v for k, v in fields.items() if v not in (None, "")},
    )
    return person, None


def absorb(person: Person, fields) -> dict:
    """Apply incoming data to an existing person: fill blank fields, ADD safety text,
    set custody_flag if raised, set photo_consent only if still unknown.
    Returns {field: "filled" | "appended"} for what changed (saved once)."""
    changed = {}
    for field, value in fields.items():
        if value in (None, ""):
            continue
        if field in APPEND_FIELDS:
            mine = (getattr(person, field, None) or "").strip()
            theirs = str(value).strip()
            if theirs and theirs.lower() not in mine.lower():
                setattr(person, field, f"{mine}\n{theirs}" if mine else theirs)
                changed[field] = APPENDED if mine else FILLED
        elif field == "custody_flag":
            if value and not person.custody_flag:
                person.custody_flag = True
                changed[field] = FILLED
        elif field == "photo_consent":
            if person.photo_consent == "unknown" and value != "unknown":
                person.photo_consent = value
                changed[field] = FILLED
        elif not getattr(person, field, None):
            setattr(person, field, value)
            changed[field] = FILLED
    if changed:
        person.save()
    return changed


# --------------------------------------------------------------------------- internals

_NONE = object()  # "no candidates at this step" (vs None = ambiguous)


def _only(qs):
    """The single result, _NONE if none, None if two or more (ambiguous)."""
    rows = list(qs[:2])
    if not rows:
        return _NONE
    return rows[0] if len(rows) == 1 else None


def _households(family):
    from households.models import Household

    if isinstance(family, Household):
        return [family.pk]
    return family

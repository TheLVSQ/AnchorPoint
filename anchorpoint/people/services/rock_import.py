"""Import a Rock RMS "all person" export into AnchorPoint people + households.

One row per person. Rows are grouped into households by Rock's `Primary Family
Id` (with `Family Name` as the household name), so we don't rely on phone
matching. Family role is inferred from age: under 18 → child, else adult.

Idempotent via `Person.external_id` ("rock:<Id>"): a re-run updates the matched
person (filling only blank fields) instead of duplicating. Dry-run by default —
the work runs inside a transaction that is rolled back unless commit=True.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction

from households.models import Household, HouseholdMember
from people.models import Person

REQUIRED_HEADERS = {"Id", "Last Name", "Nick Name", "Primary Family Id", "Record Type"}
DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y")
MINOR_AGE = 18

GENDER_MAP = {"male": "male", "female": "female", "m": "male", "f": "female"}
MARITAL_MAP = {
    "married": "married", "single": "single", "divorced": "divorced",
    "widowed": "widowed", "separated": "separated", "engaged": "engaged",
}
STATUS_MAP = {
    "member": "member", "attendee": "regular_attendee",
    "participant": "regular_attendee", "regular attendee": "regular_attendee",
    "visitor": "visitor", "guest": "guest", "prospect": "guest",
    "active": "member", "inactive": "inactive",
}
SKIP_RECORD_TYPES = {"restuser", "business"}
# Rock ships these stock records; never import them.
STOCK_KEYS = {("admin", "admin"), ("giver", "anonymous"), ("presence", "presence")}

# Person fields we update on an existing match only when they're currently blank.
_FILLABLE = [
    "email", "phone", "gender", "birthdate", "marital_status", "allergies",
    "custody_notes", "security_notes", "notes", "address_line1", "address_line2",
    "city", "state", "postal_code",
]


class RockImportError(Exception):
    """Aborts the whole import (bad/missing headers, empty file)."""


@dataclass
class RockResult:
    log: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    committed: bool = False

    def add(self, level, text):
        self.log.append((level, text))


def _g(row, key):
    return (row.get(key) or "").strip() if row.get(key) is not None else ""


def _parse_date(raw):
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _truthy(v):
    return str(v or "").strip().lower() in {"true", "yes", "1", "y"}


# Rock free-text fields often hold a literal "No"/"None" answer; treat those as
# empty so they don't become a false allergy ✚ or custody shield on the label.
_NEGATIVES = {"", "no", "none", "n/a", "na", "n", "nka", "none known",
              "no allergies", "no allergy", "-", "."}


def _clean(value):
    v = (value or "").strip()
    return "" if v.lower() in _NEGATIVES else v


def parse_csv(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise RockImportError("The file has no data rows.")
    missing = REQUIRED_HEADERS - set(rows[0].keys())
    if missing:
        raise RockImportError(
            "CSV is missing required columns: " + ", ".join(sorted(missing))
            + ". Expected a Rock RMS person export."
        )
    return rows


def _person_fields(row):
    """Map a Rock row to AnchorPoint Person field values."""
    first = _g(row, "Nick Name") or _g(row, "Name").split(" ")[0] or "Unknown"
    last = _g(row, "Last Name") or _g(row, "Name").split(" ")[-1] or "Unknown"
    emergency = ""
    ec_name = _g(row, "Emergency Contact: Name")
    if ec_name:
        rel = _g(row, "Emergency Contact: Relationship")
        ph = _g(row, "Emergency Contact: Phone Number")
        emergency = "Emergency contact: " + ec_name + (f" ({rel})" if rel else "") + (f" {ph}" if ph else "")
    custody = _clean(_g(row, "Custody Notes"))
    return {
        "first_name": first,
        "last_name": last,
        "email": _g(row, "Email"),
        "phone": _g(row, "Phone Number"),
        "gender": GENDER_MAP.get(_g(row, "Gender").lower(), ""),
        "birthdate": _parse_date(_g(row, "Birth Date")),
        "marital_status": MARITAL_MAP.get(_g(row, "Marital Status").lower(), ""),
        "allergies": _clean(_g(row, "Allergy")),
        "custody_notes": custody,
        "custody_flag": bool(custody),
        "security_notes": _g(row, "Legal Notes"),
        "notes": emergency,
        "status": STATUS_MAP.get(_g(row, "Connection Status").lower(), "visitor"),
    }


def _household_address(row):
    return {
        "address_line1": _g(row, "Home Address - Street 1"),
        "address_line2": _g(row, "Home Address - Street 2"),
        "city": _g(row, "Home Address - City"),
        "state": _g(row, "Home Address - State"),
        "postal_code": _g(row, "Home Address - Postal Code"),
    }


def _skip_reason(row):
    if _g(row, "Record Type").lower() in SKIP_RECORD_TYPES:
        return "record type " + _g(row, "Record Type")
    if _truthy(row.get("Is Deceased")):
        return "deceased"
    first = _g(row, "Nick Name").lower()
    last = _g(row, "Last Name").lower()
    if (first, last) in STOCK_KEYS:
        return "stock record"
    if not last and not first and not _g(row, "Name"):
        return "no name"
    return None


def run_rock_import(rows, *, commit=False) -> RockResult:
    """Import Rock person rows into People + Households. Returns a RockResult."""
    result = RockResult(committed=commit)
    stats = result.stats = {
        "people_created": 0, "people_matched": 0, "children": 0, "adults": 0,
        "families_created": 0, "skipped": 0,
    }

    # Group surviving rows by Rock family id (fallback: per-person family).
    families = {}
    for i, row in enumerate(rows, start=2):
        reason = _skip_reason(row)
        if reason:
            stats["skipped"] += 1
            continue
        fam_id = _g(row, "Primary Family Id") or f"solo-{_g(row, 'Id') or i}"
        families.setdefault(fam_id, []).append(row)

    with transaction.atomic():
        for fam_id, members in families.items():
            fam_name = _g(members[0], "Family Name") or (
                _g(members[0], "Last Name") + " Family"
            )
            addr = next((_household_address(r) for r in members
                         if _g(r, "Home Address - Street 1")), _household_address(members[0]))
            # Key on the Rock family id, not the name — two unrelated families
            # can share a surname and must stay separate.
            household, created = Household.objects.get_or_create(
                external_id=f"rock-fam:{fam_id}",
                defaults={"name": fam_name, **addr},
            )
            if created:
                stats["families_created"] += 1
            for key, val in addr.items():
                if val and not getattr(household, key):
                    setattr(household, key, val)
            household.save()

            first_adult = household.primary_adult
            for row in members:
                ext = f"rock:{_g(row, 'Id')}" if _g(row, "Id") else ""
                fields = _person_fields(row)
                person = Person.objects.filter(external_id=ext).first() if ext else None
                if person:
                    for f in _FILLABLE:
                        if fields.get(f) and not getattr(person, f):
                            setattr(person, f, fields[f])
                    if fields["custody_flag"] and not person.custody_flag:
                        person.custody_flag = True
                    person.save()
                    stats["people_matched"] += 1
                else:
                    person = Person.objects.create(external_id=ext, **fields)
                    stats["people_created"] += 1

                is_child = person.is_minor is True
                rel = (HouseholdMember.RelationshipType.CHILD if is_child
                       else HouseholdMember.RelationshipType.ADULT)
                HouseholdMember.objects.get_or_create(
                    household=household, person=person,
                    defaults={"relationship_type": rel},
                )
                if is_child:
                    stats["children"] += 1
                else:
                    stats["adults"] += 1
                    if first_adult is None:
                        first_adult = person

            if first_adult and household.primary_adult_id != first_adult.pk:
                household.primary_adult = first_adult
                household.save(update_fields=["primary_adult"])

        result.add("info", f"{len(families)} families, "
                   f"{stats['people_created']} created, {stats['people_matched']} matched, "
                   f"{stats['children']} children, {stats['adults']} adults, "
                   f"{stats['skipped']} rows skipped")

        if not commit:
            transaction.set_rollback(True)

    return result

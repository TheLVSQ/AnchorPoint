"""Shared signup-import logic, used by both the `import_signups` management
command and the web Import page so they run identical code.

One CSV row per child; rows are grouped into families by parent phone (falling
back to email, then name). Dry-run by default — the import runs inside a
transaction that is rolled back unless commit=True, so the preview is produced
by the exact code path a real run executes.

CSV contract: see docs/signup-import-template.csv.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction

from events.services import (
    _apply_contact_data,
    _ensure_household,
    _ensure_person,
    _match_person,
)
from groups.models import Group, GroupMembership
from people.models import Person, normalize_phone

# child_birthdate is optional: signup forms often collect grade instead of DOB,
# and VBS eligibility runs off group/grade anyway.
REQUIRED_HEADERS = {
    "parent_first_name", "parent_last_name", "parent_phone", "child_first_name",
}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")
TRUTHY = {"yes", "y", "true", "1"}
GRADE_ALIASES = {
    "prek": "pre-k", "pre k": "pre-k", "preschool": "pre-k",
    "preschool/prek": "pre-k", "pre-k/preschool": "pre-k", "pk": "pre-k",
    "kindergarten": "k", "kinder": "k",
}
VALID_GRADES = {value for value, _ in Person.GRADE_CHOICES}


class SignupImportError(Exception):
    """Raised for problems that abort the whole import (bad/missing headers)."""


@dataclass
class LogLine:
    level: str   # family | create | match | skip | warn | group
    text: str


@dataclass
class ImportResult:
    log: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    families_count: int = 0
    group_name: str = ""
    group_created: bool = None
    group_member_count: int = None
    committed: bool = False

    def add(self, level, text):
        self.log.append(LogLine(level, text))


def _parse_date(raw):
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_grade(raw):
    """Normalize '3rd Grade', 'Kindergarten', 'Pre-K' etc. to model choices."""
    g = (raw or "").strip().lower().replace("grade", "").strip()
    if not g:
        return None
    g = GRADE_ALIASES.get(g.replace("-", " ").strip(), g)
    for suffix in ("st", "nd", "rd", "th"):
        if g.endswith(suffix) and g[:-len(suffix)].isdigit():
            g = g[:-len(suffix)]
            break
    return g if g in VALID_GRADES else None


def _match_parent(email, first, last, phone):
    """Match like the events service, plus a last-10-digits phone fallback —
    stored numbers often carry a +1 country code while form responses don't."""
    person = _match_person(email, first, last, None, phone)
    if person:
        return person
    digits = normalize_phone(phone)
    if len(digits) >= 10:
        return Person.objects.filter(normalized_phone__endswith=digits[-10:]).first()
    return None


def _child_in_household(parent, first_name, last_name):
    """An existing person with this name already in one of the parent's
    households. Lets us dedupe children that carry no birthdate (so
    `_match_person` can't) — e.g. VBS rosters — by matching a kid by name within
    the family rather than creating a duplicate."""
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    if not (getattr(parent, "pk", None) and first_name):
        return None
    return (
        Person.objects.filter(
            households__members=parent,
            first_name__iexact=first_name,
            last_name__iexact=last_name,
        )
        .exclude(pk=parent.pk)
        .distinct()
        .first()
    )


def parse_csv(text):
    """Parse CSV text into a list of row dicts. Raises SignupImportError on
    empty content or missing required columns."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise SignupImportError("The file has no data rows.")
    missing = REQUIRED_HEADERS - set(rows[0].keys())
    if missing:
        raise SignupImportError(
            "CSV is missing required columns: "
            + ", ".join(sorted(missing))
            + ". See docs/signup-import-template.csv for the expected format."
        )
    return rows


def run_import(rows, *, commit=False, group_name="") -> ImportResult:
    """Import family rows. Returns a structured ImportResult (log + stats).

    Dry-run (commit=False) does all the work then rolls back, so the result
    reflects exactly what a committed run would do."""
    group_name = (group_name or "").strip()
    result = ImportResult(group_name=group_name, committed=commit)
    result.stats = {
        "parents_created": 0, "parents_matched": 0,
        "children_created": 0, "children_matched": 0, "rows_skipped": 0,
    }
    stats = result.stats

    # Group rows into families by parent phone, then email, then name.
    families = {}
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        key = (
            normalize_phone(row.get("parent_phone"))
            or (row.get("parent_email") or "").strip().lower()
            or f"{row.get('parent_first_name', '').strip().lower()} {row.get('parent_last_name', '').strip().lower()}"
        )
        families.setdefault(key, []).append((i, row))
    result.families_count = len(families)

    with transaction.atomic():
        group = None
        if group_name:
            group, created = Group.objects.get_or_create(
                name=group_name, defaults={"category": "event"}
            )
            result.group_created = created
            result.add("group", f"Group: {'created' if created else 'using existing'} '{group_name}'")

        for key, fam_rows in families.items():
            _, first_row = fam_rows[0]
            p_first = (first_row.get("parent_first_name") or "").strip()
            p_last = (first_row.get("parent_last_name") or "").strip()
            p_phone = (first_row.get("parent_phone") or "").strip()
            p_email = (first_row.get("parent_email") or "").strip()

            if not (p_first and p_last and p_phone):
                result.add("skip", f"SKIP family '{key}': missing parent name or phone "
                                    f"(rows {', '.join(str(n) for n, _ in fam_rows)})")
                stats["rows_skipped"] += len(fam_rows)
                continue

            result.add("family", f"{p_first} {p_last} ({p_phone})")

            parent = _match_parent(p_email, p_first, p_last, p_phone)
            if parent:
                matched_name = str(parent)
                parent = _apply_contact_data(
                    parent, {"email": p_email, "phone": parent.phone or p_phone}
                )
                stats["parents_matched"] += 1
                result.add("match", f"MATCHED parent → existing #{parent.pk} ({matched_name})")
            else:
                parent = _ensure_person(p_first, p_last, email=p_email, phone=p_phone)
                stats["parents_created"] += 1
                raw = (first_row.get("phone_opt_in") or "yes").strip().lower()
                parent.phone_opt_in = raw in TRUTHY
                parent.save(update_fields=["phone_opt_in"])
                result.add("create", f"CREATE parent #{parent.pk} (opt-in: {parent.phone_opt_in})")

            for line_no, row in fam_rows:
                c_first = (row.get("child_first_name") or "").strip()
                c_last = (row.get("child_last_name") or "").strip() or p_last
                if not c_first:
                    result.add("skip", f"SKIP row {line_no}: missing child name")
                    stats["rows_skipped"] += 1
                    continue
                raw_bd = (row.get("child_birthdate") or "").strip()
                birthdate = _parse_date(raw_bd)
                if raw_bd and birthdate is None:
                    result.add("warn", f"row {line_no}: unrecognized birthdate "
                                       f"{raw_bd!r} — leaving blank (use YYYY-MM-DD or MM/DD/YYYY)")

                grade = _parse_grade(row.get("child_grade"))
                if row.get("child_grade", "").strip() and grade is None:
                    result.add("warn", f"row {line_no}: unrecognized grade "
                                       f"{row['child_grade']!r} — leaving blank")

                allergies = (row.get("child_allergies") or "").strip()

                # Match by the usual keys (email/birthdate/phone); kids rarely
                # carry any, so fall back to matching by name within the parent's
                # family. Without this, birthdate-less rosters (VBS) duplicate
                # every child on re-import.
                child = _match_person("", c_first, c_last, birthdate, "")
                if child is None:
                    child = _child_in_household(parent, c_first, c_last)
                is_new = child is None

                if is_new:
                    child = Person.objects.create(
                        first_name=c_first, last_name=c_last,
                        birthdate=birthdate, grade=grade, allergies=allergies,
                    )
                else:
                    _apply_contact_data(
                        child,
                        {"birthdate": birthdate, "grade": grade, "allergies": allergies},
                    )

                custody_notes = (row.get("custody_notes") or "").strip()
                unauthorized = (row.get("unauthorized_pickup") or "").strip()
                if custody_notes or unauthorized:
                    changed = []
                    if custody_notes and not child.custody_notes:
                        child.custody_notes = custody_notes
                        changed.append("custody_notes")
                    if unauthorized and not child.unauthorized_pickup:
                        child.unauthorized_pickup = unauthorized
                        changed.append("unauthorized_pickup")
                    if changed and not child.custody_flag:
                        child.custody_flag = True
                        changed.append("custody_flag")
                    if changed:
                        child.save(update_fields=changed)

                # Emergency contact (often a non-family contact named on the form):
                # fill missing fields, never overwrite what's already recorded.
                ec_name = (row.get("emergency_contact_name") or "").strip()
                ec_phone = (row.get("emergency_contact_phone") or "").strip()
                ec_rel = (row.get("emergency_contact_relationship") or "").strip()
                ec_changed = []
                if ec_phone and not child.emergency_contact_phone:
                    child.emergency_contact_phone = ec_phone
                    ec_changed.append("emergency_contact_phone")
                if ec_name and not child.emergency_contact_name:
                    child.emergency_contact_name = ec_name
                    ec_changed.append("emergency_contact_name")
                if ec_rel and not child.emergency_contact_relationship:
                    child.emergency_contact_relationship = ec_rel
                    ec_changed.append("emergency_contact_relationship")
                if ec_changed:
                    child.save(update_fields=ec_changed)

                # Photo/likeness consent: fill only while still "unknown" — sets it
                # for new kids AND backfills matched ones, but never overwrites an
                # explicit choice. yes/true -> granted, no/false -> denied.
                if child.photo_consent == "unknown":
                    raw = (row.get("photo_consent") or "").strip().lower()
                    if raw in TRUTHY:
                        child.photo_consent = "granted"
                        child.save(update_fields=["photo_consent"])
                    elif raw in {"no", "n", "false", "0", "denied"}:
                        child.photo_consent = "denied"
                        child.save(update_fields=["photo_consent"])

                if is_new:
                    stats["children_created"] += 1
                    extras = " ⚠ custody" if (custody_notes or unauthorized) else ""
                    allergy = " ✚ allergies" if allergies else ""
                    contact = " ☎ contact" if ec_phone else ""
                    result.add("create", f"CREATE child #{child.pk} {child} "
                               f"({birthdate}{', grade ' + grade if grade else ''}){allergy}{extras}{contact}")
                else:
                    stats["children_matched"] += 1
                    result.add("match", f"MATCHED child → existing #{child.pk} ({child})")

                _ensure_household(parent, child)
                if group:
                    GroupMembership.objects.get_or_create(group=group, person=child)

        if group is not None:
            result.group_member_count = group.memberships.count()

        if not commit:
            transaction.set_rollback(True)

    return result

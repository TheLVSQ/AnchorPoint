"""Bulk-import families (parents + kids) from a signup CSV.

Built for VBS pre-registration collected via Google Forms: one row per child,
rows grouped into families by parent phone. Dry-run by default — the report is
produced by the exact code path a real run executes (the transaction is simply
rolled back), so what you review is what you get.

CSV contract: see docs/signup-import-template.csv.

Usage:
  python manage.py import_signups signups.csv                       # dry run
  python manage.py import_signups signups.csv --commit
  python manage.py import_signups signups.csv --commit --group "VBS 2026"
  cat signups.csv | python manage.py import_signups -               # stdin
"""

import csv
import sys
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.services import (
    _apply_contact_data,
    _ensure_household,
    _ensure_person,
    _match_person,
)
from groups.models import Group, GroupMembership
from people.models import Person, normalize_phone

REQUIRED_HEADERS = {
    "parent_first_name", "parent_last_name", "parent_phone",
    "child_first_name", "child_birthdate",
}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")
TRUTHY = {"yes", "y", "true", "1"}
GRADE_ALIASES = {
    "prek": "pre-k", "pre k": "pre-k", "preschool": "pre-k",
    "kindergarten": "k", "kinder": "k",
}
VALID_GRADES = {value for value, _ in Person.GRADE_CHOICES}


def _parse_date(raw):
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _match_parent(email, first, last, phone):
    """Match like the events service, plus a last-10-digits phone fallback —
    stored numbers often carry a +1 country code while form responses don't."""
    person = _match_person(email, first, last, None, phone)
    if person:
        return person
    digits = normalize_phone(phone)
    if len(digits) >= 10:
        return Person.objects.filter(
            normalized_phone__endswith=digits[-10:]
        ).first()
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


class Command(BaseCommand):
    help = "Import families from a signup CSV (one row per child). Dry-run unless --commit."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV, or '-' for stdin")
        parser.add_argument("--commit", action="store_true",
                            help="Write to the database (default: dry-run report only)")
        parser.add_argument("--group", default="",
                            help="Enroll every imported child in this group (created if missing)")

    def handle(self, *args, **options):
        commit = options["commit"]
        group_name = options["group"].strip()

        if options["csv_path"] == "-":
            rows = list(csv.DictReader(sys.stdin))
        else:
            try:
                with open(options["csv_path"], newline="", encoding="utf-8-sig") as fh:
                    rows = list(csv.DictReader(fh))
            except OSError as exc:
                raise CommandError(f"Cannot read {options['csv_path']}: {exc}")
        if not rows:
            raise CommandError("CSV has no data rows.")

        missing = REQUIRED_HEADERS - set(rows[0].keys())
        if missing:
            raise CommandError(
                f"CSV is missing required columns: {', '.join(sorted(missing))}. "
                "See docs/signup-import-template.csv for the expected format."
            )

        # Group rows into families: parent phone, falling back to email / name.
        families = {}
        for i, row in enumerate(rows, start=2):  # row 1 is the header
            key = (
                normalize_phone(row.get("parent_phone"))
                or (row.get("parent_email") or "").strip().lower()
                or f"{row.get('parent_first_name', '').strip().lower()} {row.get('parent_last_name', '').strip().lower()}"
            )
            families.setdefault(key, []).append((i, row))

        stats = {"parents_created": 0, "parents_matched": 0,
                 "children_created": 0, "children_matched": 0, "rows_skipped": 0}

        with transaction.atomic():
            group = None
            if group_name:
                group, created = Group.objects.get_or_create(
                    name=group_name, defaults={"category": "event"}
                )
                self.stdout.write(
                    f"Group: {'created' if created else 'using existing'} '{group_name}'"
                )

            for key, fam_rows in families.items():
                _, first_row = fam_rows[0]
                p_first = (first_row.get("parent_first_name") or "").strip()
                p_last = (first_row.get("parent_last_name") or "").strip()
                p_phone = (first_row.get("parent_phone") or "").strip()
                p_email = (first_row.get("parent_email") or "").strip()

                if not (p_first and p_last and p_phone):
                    self.stdout.write(self.style.WARNING(
                        f"  SKIP family '{key}': missing parent name or phone "
                        f"(rows {', '.join(str(n) for n, _ in fam_rows)})"
                    ))
                    stats["rows_skipped"] += len(fam_rows)
                    continue

                self.stdout.write(f"\n── {p_first} {p_last} ({p_phone})")

                parent = _match_parent(p_email, p_first, p_last, p_phone)
                if parent:
                    matched_name = str(parent)
                    parent = _apply_contact_data(
                        parent, {"email": p_email, "phone": parent.phone or p_phone}
                    )
                    stats["parents_matched"] += 1
                    # Print the matched record's name so a wrong phone-based
                    # match is obvious during dry-run review.
                    self.stdout.write(f"   MATCHED parent → existing #{parent.pk} ({matched_name})")
                else:
                    parent = _ensure_person(p_first, p_last, email=p_email, phone=p_phone)
                    stats["parents_created"] += 1
                    # Consent comes from the form only for people we create —
                    # never flip an existing person's opt-in from a CSV.
                    raw = (first_row.get("phone_opt_in") or "yes").strip().lower()
                    parent.phone_opt_in = raw in TRUTHY
                    parent.save(update_fields=["phone_opt_in"])
                    self.stdout.write(
                        f"   CREATE parent #{parent.pk} (opt-in: {parent.phone_opt_in})"
                    )

                for line_no, row in fam_rows:
                    c_first = (row.get("child_first_name") or "").strip()
                    c_last = (row.get("child_last_name") or "").strip() or p_last
                    birthdate = _parse_date(row.get("child_birthdate"))
                    if not c_first or not birthdate:
                        self.stdout.write(self.style.WARNING(
                            f"   SKIP row {line_no}: "
                            + ("missing child name" if not c_first else
                               f"bad birthdate {row.get('child_birthdate')!r} "
                               "(use YYYY-MM-DD or MM/DD/YYYY)")
                        ))
                        stats["rows_skipped"] += 1
                        continue

                    grade = _parse_grade(row.get("child_grade"))
                    if row.get("child_grade", "").strip() and grade is None:
                        self.stdout.write(self.style.WARNING(
                            f"   row {line_no}: unrecognized grade "
                            f"{row['child_grade']!r} — leaving blank"
                        ))

                    child_existing = _match_person("", c_first, c_last, birthdate, "")
                    child = _ensure_person(
                        c_first, c_last, birthdate=birthdate,
                        grade=grade, allergies=(row.get("child_allergies") or "").strip(),
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

                    if child_existing:
                        stats["children_matched"] += 1
                        self.stdout.write(f"   MATCHED child  → existing #{child.pk} ({child})")
                    else:
                        stats["children_created"] += 1
                        extras = " ⚠custody" if (custody_notes or unauthorized) else ""
                        allergy = " ✚allergies" if (row.get("child_allergies") or "").strip() else ""
                        self.stdout.write(
                            f"   CREATE child  #{child.pk} {child} "
                            f"({birthdate}{', grade ' + grade if grade else ''}){allergy}{extras}"
                        )

                    _ensure_household(parent, child)
                    if group:
                        GroupMembership.objects.get_or_create(group=group, person=child)

            self.stdout.write(self.style.MIGRATE_HEADING("\n=== SUMMARY ==="))
            self.stdout.write(f"families processed : {len(families)}")
            self.stdout.write(f"parents  created/matched : {stats['parents_created']}/{stats['parents_matched']}")
            self.stdout.write(f"children created/matched : {stats['children_created']}/{stats['children_matched']}")
            self.stdout.write(f"rows skipped : {stats['rows_skipped']}")
            if group:
                self.stdout.write(f"group '{group_name}' members: {group.memberships.count()}")

            if not commit:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    "\nDRY RUN — nothing was written. Re-run with --commit to apply."
                ))
            else:
                self.stdout.write(self.style.SUCCESS("\nCommitted."))

"""Bulk-import families (parents + kids) from a signup CSV.

Built for VBS pre-registration collected via Google Forms: one row per child,
rows grouped into families by parent phone. Dry-run by default — the report is
produced by the exact code path a real run executes (the transaction is simply
rolled back), so what you review is what you get. Shares its logic with the web
Import page (people/services/signup_import.py).

CSV contract: see docs/signup-import-template.csv.

Usage:
  python manage.py import_signups signups.csv                       # dry run
  python manage.py import_signups signups.csv --commit
  python manage.py import_signups signups.csv --commit --group "VBS 2026"
  cat signups.csv | python manage.py import_signups -               # stdin
"""

import sys

from django.core.management.base import BaseCommand, CommandError

from people.services.signup_import import SignupImportError, parse_csv, run_import


class Command(BaseCommand):
    help = "Import families from a signup CSV (one row per child). Dry-run unless --commit."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV, or '-' for stdin")
        parser.add_argument("--commit", action="store_true",
                            help="Write to the database (default: dry-run report only)")
        parser.add_argument("--group", default="",
                            help="Enroll every imported child in this group (created if missing)")

    def handle(self, *args, **options):
        if options["csv_path"] == "-":
            text = sys.stdin.read()
        else:
            try:
                with open(options["csv_path"], encoding="utf-8-sig") as fh:
                    text = fh.read()
            except OSError as exc:
                raise CommandError(f"Cannot read {options['csv_path']}: {exc}")

        try:
            rows = parse_csv(text)
            result = run_import(rows, commit=options["commit"], group_name=options["group"])
        except SignupImportError as exc:
            raise CommandError(str(exc))

        styles = {
            "skip": self.style.WARNING,
            "warn": self.style.WARNING,
            "family": lambda t: "\n── " + t,
        }
        for line in result.log:
            style = styles.get(line.level)
            if line.level in ("create", "match"):
                self.stdout.write("   " + line.text)
            elif line.level == "family":
                self.stdout.write(f"\n── {line.text}")
            elif style:
                self.stdout.write(style(("   " if line.level in ("skip", "warn") else "") + line.text))
            else:
                self.stdout.write(line.text)

        s = result.stats
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== SUMMARY ==="))
        self.stdout.write(f"families processed : {result.families_count}")
        self.stdout.write(f"parents  created/matched : {s['parents_created']}/{s['parents_matched']}")
        self.stdout.write(f"children created/matched : {s['children_created']}/{s['children_matched']}")
        self.stdout.write(f"rows skipped : {s['rows_skipped']}")
        if result.group_member_count is not None:
            self.stdout.write(f"group '{result.group_name}' members: {result.group_member_count}")

        if not result.committed:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing was written. Re-run with --commit to apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\nCommitted."))

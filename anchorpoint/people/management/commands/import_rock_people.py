"""Migrate a Rock RMS "all person" export into AnchorPoint people + households.

One row per person, grouped into households by Rock's Primary Family Id. Family
role inferred from age (<18 child, else adult). Idempotent via Person.external_id
("rock:<Id>"). Dry-run by default — re-run with --commit to write.

Usage:
  python manage.py import_rock_people rock_people.csv            # dry run
  python manage.py import_rock_people rock_people.csv --commit
  cat rock_people.csv | python manage.py import_rock_people -    # stdin
"""

import sys

from django.core.management.base import BaseCommand, CommandError

from people.services.rock_import import RockImportError, parse_csv, run_rock_import


class Command(BaseCommand):
    help = "Import people + households from a Rock RMS person export. Dry-run unless --commit."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV, or '-' for stdin")
        parser.add_argument("--commit", action="store_true",
                            help="Write to the database (default: dry-run summary only)")

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
            result = run_rock_import(rows, commit=options["commit"])
        except RockImportError as exc:
            raise CommandError(str(exc))

        for _level, msg in result.log:
            self.stdout.write(msg)

        s = result.stats
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== SUMMARY ==="))
        self.stdout.write(f"families created : {s['families_created']}")
        self.stdout.write(f"people created/matched : {s['people_created']}/{s['people_matched']}")
        self.stdout.write(f"adults / children : {s['adults']} / {s['children']}")
        self.stdout.write(f"rows skipped : {s['skipped']}")

        if not result.committed:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing was written. Re-run with --commit to apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\nCommitted."))

"""Nightly people/family hygiene (cron sidecar). See households/hygiene.py."""
from django.core.management.base import BaseCommand

from households import hygiene
from households.models import CleanupFinding


class Command(BaseCommand):
    help = "Find likely duplicate people/families and orphaned families; update the Data cleanup queue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Only print counts by kind (no names); change nothing.",
        )

    def handle(self, *args, dry_run=False, **options):
        counts = hygiene.run(dry_run=dry_run)
        labels = dict(CleanupFinding.KIND_CHOICES)
        for kind, label in labels.items():
            self.stdout.write(f"{label}: {counts.get(kind, 0)}")
        if dry_run:
            self.stdout.write("(dry run — nothing saved)")
        else:
            self.stdout.write(
                f"New/reopened: {counts.get('opened', 0)} · auto-resolved: {counts.get('resolved', 0)} · "
                f"open now: {hygiene.open_count()}"
            )

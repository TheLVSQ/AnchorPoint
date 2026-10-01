"""Clear stored label images from old print jobs.

Labels carry children's names, allergies, pickup codes and (optionally)
emergency phone numbers. Finished jobs are cleared on ack; this catches
anything left behind (stuck/abandoned jobs). Job rows stay for history.
Run daily by the cron sidecar.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from checkin.models import PrintJob


class Command(BaseCommand):
    help = "Clear label images from print jobs older than --hours (default 24)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(hours=opts["hours"])
        n = (
            PrintJob.objects.filter(created_at__lt=cutoff)
            .exclude(image_data=b"")
            .update(image_data=b"")
        )
        self.stdout.write(f"Cleared label images from {n} print job(s).")

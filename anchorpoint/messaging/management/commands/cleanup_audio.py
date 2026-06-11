import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from messaging.models import PhoneBlast


DEFAULT_RETENTION_DAYS = 30
UPLOAD_SUBDIR = "communications/phone_blasts"


class Command(BaseCommand):
    help = (
        "Delete phone-blast audio files that are no longer needed: recordings for "
        "blasts that finished more than N days ago, plus any orphaned files on disk "
        "not referenced by a PhoneBlast."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help=(
                "Retention window in days. Files for blasts that completed more than "
                "this many days ago are purged. Defaults to AUDIO_RETENTION_DAYS env "
                f"or {DEFAULT_RETENTION_DAYS}."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without deleting anything.",
        )

    def _retention_days(self, days):
        if days is not None:
            return days
        return int(os.getenv("AUDIO_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        retention_days = self._retention_days(options["days"])
        cutoff = timezone.now() - timezone.timedelta(days=retention_days)

        purged = self._purge_aged_blasts(cutoff, dry_run)
        orphans = self._sweep_orphans(dry_run)

        verb = "Would remove" if dry_run else "Removed"
        self.stdout.write(
            f"{verb} {purged} aged blast recording(s) and {orphans} orphaned file(s)."
        )

    def _purge_aged_blasts(self, cutoff, dry_run):
        """Clear audio_file for finished blasts older than the cutoff."""
        finished = (PhoneBlast.Status.COMPLETED, PhoneBlast.Status.FAILED)
        queryset = PhoneBlast.objects.filter(
            status__in=finished,
            completed_at__lt=cutoff,
        ).exclude(audio_file="")
        count = 0
        for blast in queryset:
            if not blast.audio_file:
                continue
            self.stdout.write(
                f"  blast #{blast.pk} ({blast.title!r}): {blast.audio_file.name}"
            )
            if not dry_run:
                # delete(save=True) removes the stored file and clears the field.
                blast.audio_file.delete(save=True)
            count += 1
        return count

    def _sweep_orphans(self, dry_run):
        """Delete files on disk under the upload dir not referenced by any blast."""
        media_root = settings.MEDIA_ROOT
        target_dir = os.path.join(str(media_root), UPLOAD_SUBDIR)
        if not os.path.isdir(target_dir):
            return 0

        referenced = {
            os.path.normpath(os.path.join(str(media_root), name))
            for name in PhoneBlast.objects.exclude(audio_file="").values_list(
                "audio_file", flat=True
            )
        }
        count = 0
        for entry in os.scandir(target_dir):
            if not entry.is_file():
                continue
            if os.path.normpath(entry.path) in referenced:
                continue
            self.stdout.write(f"  orphan: {entry.path}")
            if not dry_run:
                try:
                    os.remove(entry.path)
                except OSError as exc:
                    self.stderr.write(f"  could not remove {entry.path}: {exc}")
                    continue
            count += 1
        return count

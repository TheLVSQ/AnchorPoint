"""The song library: songs, their arrangements, and each arrangement's charts and links.

A song is archived (`is_active=False`), never deleted, so past setlists and the CCLI usage
report keep pointing at it. Chart PDFs live under `songs/charts/` with random names; that
folder isn't public (`core/media.py`), and pages link to `songs:chart` (access-checked),
never to the file's URL.
"""
import uuid

from django.core.validators import URLValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.validators import validate_pdf, validate_pdf_size


class Song(models.Model):
    title = models.CharField(max_length=200)
    author = models.CharField("Writers", max_length=200, blank=True)
    ccli_number = models.CharField(
        "CCLI song number", max_length=20, blank=True,
        help_text="From SongSelect. Used for the CCLI usage report.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(
        "Active", default=True,
        help_text="Archived songs are hidden from the library but stay on past setlists.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class Arrangement(models.Model):
    """One way the team plays a song: its key, tempo, charts and reference links."""

    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="arrangements")
    name = models.CharField(max_length=100, default="Default")
    key = models.CharField(max_length=10, blank=True, help_text="e.g. G, Bb, F#m")
    bpm = models.PositiveSmallIntegerField("BPM", null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Road map, intro, endings…")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["song", "name"], name="unique_arrangement_name"),
        ]

    def __str__(self):
        return f"{self.song} ({self.name})"


def chart_upload_path(instance, filename):
    return f"songs/charts/{uuid.uuid4().hex}.pdf"


class Chart(models.Model):
    arrangement = models.ForeignKey(Arrangement, on_delete=models.CASCADE, related_name="charts")
    label = models.CharField(max_length=100, help_text="e.g. Chord chart, Lead sheet, Vocals")
    file = models.FileField(upload_to=chart_upload_path,
                            validators=[validate_pdf, validate_pdf_size])
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "pk"]

    def __str__(self):
        return f"{self.arrangement}: {self.label}"


@receiver(post_delete, sender=Chart)
def _delete_chart_file(sender, instance, **kwargs):
    """Rows don't take their files with them; this covers cascades from an arrangement too."""
    if instance.file:
        instance.file.delete(save=False)


class MediaLink(models.Model):
    """A recording or video to rehearse with (YouTube, Spotify, a shared audio file…)."""

    arrangement = models.ForeignKey(Arrangement, on_delete=models.CASCADE, related_name="links")
    label = models.CharField(max_length=100, help_text="e.g. YouTube, Rehearsal track")
    url = models.URLField("Link", max_length=500,
                          validators=[URLValidator(schemes=["http", "https"])])

    class Meta:
        ordering = ["label", "pk"]

    def __str__(self):
        return self.label

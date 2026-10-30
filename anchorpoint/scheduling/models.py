from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def _same_day_in(year, day):
    """`day` moved to `year`; Feb 29 becomes Feb 28 in a non-leap year."""
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


class Blockout(models.Model):
    """Dates a person can't serve on any team (vacation, "out the 14th"). A yearly blockout
    repeats on the same dates every year. Regular "only the 3rd Sunday" serving is not a
    blockout: that's GroupMembership.serving_weeks."""

    person = models.ForeignKey(
        "people.Person", related_name="blockouts", on_delete=models.CASCADE
    )
    starts_on = models.DateField("From")
    ends_on = models.DateField("To")
    repeats_yearly = models.BooleanField("Every year", default=False)
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_on"]

    def __str__(self):
        return f"{self.person}: {self.label}"

    def clean(self):
        if self.starts_on and self.ends_on:
            if self.ends_on < self.starts_on:
                raise ValidationError({"ends_on": "The end date can't be before the start date."})
            year_later = _same_day_in(self.starts_on.year + 1, self.starts_on)
            if self.repeats_yearly and self.ends_on >= year_later - timedelta(days=1):
                raise ValidationError({"ends_on": "A yearly blockout must be shorter than a year."})

    @property
    def label(self):
        fmt = "%b %-d" if self.repeats_yearly else "%b %-d, %Y"
        text = self.starts_on.strftime(fmt)
        if self.ends_on != self.starts_on:
            text += f" – {self.ends_on.strftime(fmt)}"
        return text + (" (every year)" if self.repeats_yearly else "")

    def covers(self, day):
        if not self.repeats_yearly:
            return self.starts_on <= day <= self.ends_on
        length = self.ends_on - self.starts_on
        # The range may cross New Year (Dec 28 – Jan 3), so try this year's and last year's.
        for year in (day.year - 1, day.year):
            start = _same_day_in(year, self.starts_on)
            if start <= day <= start + length:
                return True
        return False

    def is_current(self, today=None):
        """Still relevant: a yearly blockout always is; a one-off until it has ended."""
        today = today or timezone.localdate()
        return self.repeats_yearly or self.ends_on >= today

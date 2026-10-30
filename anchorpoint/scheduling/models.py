from datetime import timedelta

from django.conf import settings
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


class ServiceType(models.Model):
    """A kind of service that gets scheduled ("Sunday Morning", "VBS 2027"). It says which
    positions each date needs; a Plan is one date of it."""

    WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
                (4, "Friday"), (5, "Saturday"), (6, "Sunday")]

    name = models.CharField(max_length=80, unique=True)
    weekday = models.PositiveSmallIntegerField(
        choices=WEEKDAYS, null=True, blank=True, default=6,
        help_text="Adding dates creates one plan per week on this day. "
                  "Pick Every day for a run of days like VBS.",
    )
    default_time = models.TimeField("Service time", null=True, blank=True)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ServiceTypeNeed(models.Model):
    """How many people in one position each plan of a service type needs."""

    service_type = models.ForeignKey(ServiceType, related_name="needs", on_delete=models.CASCADE)
    position = models.ForeignKey("groups.Position", related_name="needs",
                                 on_delete=models.CASCADE)
    count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["position__group__name", "position__name"]
        constraints = [
            models.UniqueConstraint(fields=["service_type", "position"],
                                    name="unique_need_per_service_type"),
        ]

    def __str__(self):
        return f"{self.service_type}: {self.count} × {self.position}"


class Plan(models.Model):
    """One date of a service type: who serves in each position."""

    service_type = models.ForeignKey(ServiceType, related_name="plans", on_delete=models.CASCADE)
    date = models.DateField()
    time = models.TimeField(null=True, blank=True)
    title = models.CharField(max_length=120, blank=True, help_text="Optional, e.g. Easter.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["service_type", "date"],
                                    name="unique_plan_per_date"),
        ]

    def __str__(self):
        return f"{self.service_type} {self.date:%b %-d}"


class Assignment(models.Model):
    """One person in one position on one plan. A draft until staff send the request
    (`requested_at`); then Pending until the person accepts or declines."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    plan = models.ForeignKey(Plan, related_name="assignments", on_delete=models.CASCADE)
    # PROTECT: a position can't vanish from schedules people are on.
    position = models.ForeignKey("groups.Position", related_name="assignments",
                                 on_delete=models.PROTECT)
    person = models.ForeignKey("people.Person", related_name="assignments",
                               on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   related_name="+", on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    # Staff pressed "Send requests" (the volunteer can see and answer it from then on);
    # the cron sends the email and stamps request_sent_at. See scheduling/requests.py.
    requested_at = models.DateTimeField(null=True, blank=True)
    request_sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=200, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["plan__date", "position__name", "person__last_name"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "position", "person"],
                                    name="unique_assignment"),
        ]

    def __str__(self):
        return f"{self.person} – {self.position} – {self.plan}"

    @property
    def is_draft(self):
        return self.requested_at is None

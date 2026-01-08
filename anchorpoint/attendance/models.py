from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CheckInConfiguration(models.Model):
    """Named check-in experiences that control availability and kiosk behavior."""

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(
        blank=True,
        help_text="Optional context shown to staff when picking a check-in flow.",
    )
    welcome_message = models.CharField(
        max_length=255,
        blank=True,
        help_text="Copy displayed on the kiosk welcome screen.",
    )
    location_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Used on rosters and signage to differentiate kiosks.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive configurations stay hidden from the kiosk launcher.",
    )
    groups = models.ManyToManyField(
        "groups.Group",
        related_name="checkin_configurations",
        blank=True,
        help_text="Limit eligible classrooms/teams for this check-in flow.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def active_windows(self):
        return self.windows.filter(is_active=True)

    def open_windows(self, reference_time=None):
        now = reference_time or timezone.localtime()
        return [window for window in self.active_windows() if window.is_open(now)]

    def is_open(self, reference_time=None):
        return bool(self.open_windows(reference_time))

    def schedule_summary(self):
        windows = list(self.active_windows())
        if not windows:
            return "No schedule"
        formatted = []
        for window in windows:
            start = window.opens_at.strftime("%I:%M %p").lstrip("0") if window.opens_at else ""
            end = window.closes_at.strftime("%I:%M %p").lstrip("0") if window.closes_at else ""
            if window.schedule_type == CheckInWindow.TYPE_SPECIFIC_DATE and window.specific_date:
                date_label = window.specific_date.strftime("%b %d, %Y")
                formatted.append(f"{date_label} {start}-{end}".strip())
            else:
                day_label = window.get_day_of_week_display() if window.day_of_week is not None else "Day"
                formatted.append(f"{day_label} {start}-{end}".strip())
        return ", ".join(formatted)


class CheckInWindow(models.Model):
    """Weekly schedule windows when a configuration is available."""

    TYPE_WEEKLY = "weekly"
    TYPE_SPECIFIC_DATE = "specific_date"
    TYPE_CHOICES = [
        (TYPE_WEEKLY, "Recurring (weekly)"),
        (TYPE_SPECIFIC_DATE, "Specific date"),
    ]

    DAY_CHOICES = [
        (0, "Sunday"),
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
        (6, "Saturday"),
    ]

    configuration = models.ForeignKey(
        CheckInConfiguration,
        related_name="windows",
        on_delete=models.CASCADE,
    )
    schedule_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_WEEKLY,
        help_text="Choose weekly recurrence or select a specific date.",
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES, blank=True, null=True)
    specific_date = models.DateField(blank=True, null=True)
    opens_at = models.TimeField()
    closes_at = models.TimeField()
    is_active = models.BooleanField(default=True)
    notes = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional reminder such as special instructions or locations.",
    )

    class Meta:
        ordering = ["schedule_type", "specific_date", "day_of_week", "opens_at"]
        verbose_name = "Check-In Window"
        verbose_name_plural = "Check-In Windows"

    def __str__(self):
        if self.schedule_type == self.TYPE_SPECIFIC_DATE and self.specific_date:
            return f"{self.configuration.name} on {self.specific_date:%Y-%m-%d}"
        day_label = dict(self.DAY_CHOICES).get(self.day_of_week, "Day")
        return f"{self.configuration.name} on {day_label} ({self.opens_at} - {self.closes_at})"

    def clean(self):
        if self.schedule_type == self.TYPE_SPECIFIC_DATE:
            if not self.specific_date:
                raise ValidationError("Specific date is required for date-based windows.")
        else:
            if self.day_of_week is None:
                raise ValidationError("Day of week is required for weekly windows.")
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError("Close time must be after start time.")

    def is_open(self, reference_time=None):
        now = reference_time or timezone.localtime()
        current_time = now.time()
        if self.schedule_type == self.TYPE_SPECIFIC_DATE:
            if not self.specific_date or self.specific_date != now.date():
                return False
        else:
            if self.day_of_week is None or self.day_of_week != now.weekday():
                return False
        return self.opens_at <= current_time <= self.closes_at

    @property
    def display_label(self):
        start = self.opens_at.strftime("%I:%M %p").lstrip("0")
        end = self.closes_at.strftime("%I:%M %p").lstrip("0")
        if self.schedule_type == self.TYPE_SPECIFIC_DATE and self.specific_date:
            date_label = self.specific_date.strftime("%b %d")
            return f"{self.configuration.name} • {date_label} {start}-{end}"
        day_label = self.get_day_of_week_display() if self.day_of_week is not None else "Day"
        return f"{self.configuration.name} • {day_label} {start}-{end}"


class AttendanceRecord(models.Model):
    METHOD_KIOSK = "kiosk"
    METHOD_MANUAL = "manual"
    METHOD_CHOICES = [
        (METHOD_KIOSK, "Kiosk"),
        (METHOD_MANUAL, "Manual"),
    ]

    person = models.ForeignKey(
        "people.Person",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    household = models.ForeignKey(
        "households.Household",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    configuration = models.ForeignKey(
        CheckInConfiguration,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    checkin_window = models.ForeignKey(
        CheckInWindow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    event_occurrence = models.ForeignKey(
        "events.EventOccurrence",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    checked_in_at = models.DateTimeField(auto_now_add=True)
    method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default=METHOD_KIOSK,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.person} @ {self.configuration} ({self.checked_in_at:%Y-%m-%d %H:%M})"

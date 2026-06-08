import hashlib
import random
import secrets
import string

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from people.models import Person

User = get_user_model()


def hash_agent_token(token: str) -> str:
    """Hash a print-agent token for storage. Tokens are high-entropy random
    strings, so a fast SHA-256 is sufficient (no need for password hashing)."""
    return hashlib.sha256(token.encode()).hexdigest()


# Characters that are easy to read and won't be confused
# Excludes: 0/O, 1/I/L, 5/S
SECURITY_CODE_CHARS = "ABCDEFGHJKMNPQRTUVWXYZ234679"


def generate_security_code():
    """Generate a 4-character random alphanumeric security code."""
    return "".join(random.choices(SECURITY_CODE_CHARS, k=4))


def generate_unique_security_code(session, max_attempts=100):
    """Generate a security code that does not collide with any *active*
    (not-yet-checked-out) check-in in the same session.

    Checkout matches families solely by (session, security_code); if two
    families share a code, a parent could be shown — and could check out —
    another family's children. Guaranteeing uniqueness among active codes
    closes that child-safety gap. Codes are free to reuse once checked out.
    """
    for _ in range(max_attempts):
        code = generate_security_code()
        if not session.checkins.filter(
            security_code=code, checked_out_at__isnull=True
        ).exists():
            return code
    # Practically unreachable (28**4 ≈ 614k codes vs. a few hundred active
    # check-ins). Fall back to the last code rather than failing the check-in.
    return code


class CheckInConfiguration(models.Model):
    """Named check-in configuration controlling schedule, eligibility, and rooms."""

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    welcome_message = models.CharField(max_length=255, blank=True)
    location_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    rooms = models.ManyToManyField("Room", related_name="configurations", blank=True)

    # Eligibility filters — all optional, OR logic
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age = models.PositiveIntegerField(null=True, blank=True)
    min_grade = models.CharField(
        max_length=20, choices=Person.GRADE_CHOICES, blank=True
    )
    max_grade = models.CharField(
        max_length=20, choices=Person.GRADE_CHOICES, blank=True
    )
    groups = models.ManyToManyField(
        "groups.Group", related_name="checkin_app_configurations", blank=True
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
        return [w for w in self.active_windows() if w.is_checkin_open(now)]

    def is_open(self, reference_time=None):
        return bool(self.open_windows(reference_time))

    def schedule_summary(self):
        windows = list(self.active_windows())
        if not windows:
            return "No schedule"
        parts = []
        for w in windows:
            opens = w.checkin_opens.strftime("%I:%M %p").lstrip("0")
            closes = w.checkin_closes.strftime("%I:%M %p").lstrip("0")
            if w.schedule_type == CheckInWindow.TYPE_SPECIFIC_DATE and w.specific_date:
                parts.append(f"{w.specific_date:%b %d, %Y} {opens}-{closes}")
            else:
                day = w.get_day_of_week_display() if w.day_of_week is not None else "Day"
                parts.append(f"{day} {opens}-{closes}")
        return ", ".join(parts)

    def has_filters(self):
        return any([
            self.min_age is not None,
            self.max_age is not None,
            self.min_grade,
            self.max_grade,
            self.groups.exists(),
        ])


class CheckInWindow(models.Model):
    """Schedule window with four-time model for check-in availability."""

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
        CheckInConfiguration, related_name="windows", on_delete=models.CASCADE
    )
    schedule_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_WEEKLY
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES, blank=True, null=True)
    specific_date = models.DateField(blank=True, null=True)

    checkin_opens = models.TimeField()
    event_starts = models.TimeField()
    checkin_closes = models.TimeField()
    event_ends = models.TimeField()

    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["schedule_type", "specific_date", "day_of_week", "checkin_opens"]

    def __str__(self):
        if self.schedule_type == self.TYPE_SPECIFIC_DATE and self.specific_date:
            return f"{self.configuration.name} on {self.specific_date:%Y-%m-%d}"
        day = dict(self.DAY_CHOICES).get(self.day_of_week, "Day")
        return f"{self.configuration.name} on {day} ({self.checkin_opens}-{self.checkin_closes})"

    def clean(self):
        if self.schedule_type == self.TYPE_SPECIFIC_DATE:
            if not self.specific_date:
                raise ValidationError("Specific date is required for date-based windows.")
        else:
            if self.day_of_week is None:
                raise ValidationError("Day of week is required for weekly windows.")
        if self.checkin_opens and self.checkin_closes and self.checkin_opens >= self.checkin_closes:
            raise ValidationError("Check-in close time must be after check-in open time.")
        if self.event_starts and self.event_ends and self.event_starts >= self.event_ends:
            raise ValidationError("Event end time must be after event start time.")

    @staticmethod
    def _sunday_weekday(dt):
        """Convert Python weekday (Mon=0..Sun=6) to Sunday-first (Sun=0..Sat=6)."""
        return (dt.weekday() + 1) % 7

    def is_checkin_open(self, reference_time=None):
        now = reference_time or timezone.localtime()
        current_time = now.time()
        if self.schedule_type == self.TYPE_SPECIFIC_DATE:
            if not self.specific_date or self.specific_date != now.date():
                return False
        else:
            if self.day_of_week is None or self.day_of_week != self._sunday_weekday(now):
                return False
        return self.checkin_opens <= current_time <= self.checkin_closes

    @property
    def display_label(self):
        opens = self.checkin_opens.strftime("%I:%M %p").lstrip("0")
        closes = self.checkin_closes.strftime("%I:%M %p").lstrip("0")
        if self.schedule_type == self.TYPE_SPECIFIC_DATE and self.specific_date:
            return f"{self.configuration.name} • {self.specific_date:%b %d} {opens}-{closes}"
        day = self.get_day_of_week_display() if self.day_of_week is not None else "Day"
        return f"{self.configuration.name} • {day} {opens}-{closes}"


class Room(models.Model):
    """Physical check-in room. Eligibility is on CheckInConfiguration, not here."""

    name = models.CharField(max_length=100)
    building = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class CheckInSession(models.Model):
    """Concrete instance of a configuration + window for a specific date."""

    configuration = models.ForeignKey(
        CheckInConfiguration,
        on_delete=models.CASCADE,
        related_name="sessions",
        null=True,
        blank=True,
    )
    window = models.ForeignKey(
        CheckInWindow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )

    name = models.CharField(max_length=100)
    date = models.DateField()

    checkin_opens = models.TimeField()
    checkin_closes = models.TimeField()
    event_starts = models.TimeField()
    event_ends = models.TimeField()

    event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, blank=True
    )

    rooms = models.ManyToManyField(Room, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_sessions",
    )

    class Meta:
        ordering = ["-date", "-checkin_opens"]
        constraints = [
            # At most one schedule-driven session per config+window per day.
            # Standalone sessions (configuration/window NULL) are exempt because
            # NULLs compare distinct, so the kiosk fallback can still create one.
            models.UniqueConstraint(
                fields=["configuration", "window", "date"],
                name="uniq_session_per_config_window_date",
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.date}"

    @property
    def is_open(self):
        if not self.is_active:
            return False
        now = timezone.localtime()
        if self.date != now.date():
            return False
        return self.checkin_opens <= now.time() <= self.checkin_closes

    def total_checked_in(self):
        return self.checkins.filter(checked_out_at__isnull=True).count()


class CheckIn(models.Model):
    """Individual check-in record for one person at one session."""

    session = models.ForeignKey(
        CheckInSession, on_delete=models.CASCADE, related_name="checkins"
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="checkins")
    room = models.ForeignKey(
        Room, on_delete=models.SET_NULL, null=True, blank=True
    )
    security_code = models.CharField(max_length=4)
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_in_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="checked_in_by",
    )
    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_out_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="checked_out_by",
    )
    child_label_printed = models.BooleanField(default=False)
    parent_label_printed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.person} at {self.session}"

    @property
    def is_checked_out(self):
        return self.checked_out_at is not None

    def checkout(self, user=None):
        """Mark this check-in as checked out."""
        self.checked_out_at = timezone.now()
        self.checked_out_by = user
        self.save(update_fields=["checked_out_at", "checked_out_by"])


class PrinterConfiguration(models.Model):
    """Printer settings for label printing."""

    PRINTER_TYPE_CHOICES = [
        ("brother_ql", "Brother QL"),
        ("escpos", "ESC/POS Thermal"),
    ]

    QL_MODEL_CHOICES = [
        ("QL-700", "QL-700"),
        ("QL-800", "QL-800"),
        ("QL-810W", "QL-810W"),
        ("QL-820NWB", "QL-820NWB"),
        ("QL-1100", "QL-1100"),
        ("QL-1110NWB", "QL-1110NWB"),
    ]

    name = models.CharField(max_length=100)
    printer_type = models.CharField(
        max_length=50,
        choices=PRINTER_TYPE_CHOICES,
        blank=True,
    )
    connection_type = models.CharField(max_length=50, blank=True)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(null=True, blank=True)
    ql_model = models.CharField(
        max_length=20,
        choices=QL_MODEL_CHOICES,
        default="QL-800",
        blank=True,
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class LabelTemplate(models.Model):
    """Label template configuration."""

    name = models.CharField(max_length=100)
    width_mm = models.PositiveIntegerField(default=62)
    height_mm = models.PositiveIntegerField(default=76)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


# Online if the agent has polled within this many seconds.
AGENT_ONLINE_WINDOW_SECONDS = 60
# Pairing codes are valid for this long after being issued.
PAIRING_CODE_TTL_SECONDS = 15 * 60


class PrintAgent(models.Model):
    """A local print agent that polls the server for jobs and prints them on a
    LAN printer. The server never connects to the printer — the agent makes
    only outbound HTTPS calls, so no VPN/inbound networking is required."""

    name = models.CharField(max_length=120)
    token_hash = models.CharField(max_length=64, blank=True)
    pairing_code = models.CharField(max_length=12, blank=True, db_index=True)
    pairing_expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_paired(self):
        return bool(self.token_hash)

    @property
    def is_online(self):
        if not self.last_seen_at:
            return False
        return (timezone.now() - self.last_seen_at).total_seconds() < AGENT_ONLINE_WINDOW_SECONDS

    def issue_pairing_code(self):
        """Generate a fresh, short, human-typable pairing code with a TTL."""
        # No ambiguous characters (shares the security-code alphabet).
        self.pairing_code = "".join(random.choices(SECURITY_CODE_CHARS, k=8))
        self.pairing_expires_at = timezone.now() + timezone.timedelta(
            seconds=PAIRING_CODE_TTL_SECONDS
        )
        self.token_hash = ""  # re-pairing invalidates any old token
        self.save(update_fields=["pairing_code", "pairing_expires_at", "token_hash"])
        return self.pairing_code

    def complete_pairing(self):
        """Consume the pairing code and issue a long-lived agent token (returned
        once, only its hash is stored)."""
        token = secrets.token_urlsafe(32)
        self.token_hash = hash_agent_token(token)
        self.pairing_code = ""
        self.pairing_expires_at = None
        self.last_seen_at = timezone.now()
        self.save(update_fields=[
            "token_hash", "pairing_code", "pairing_expires_at", "last_seen_at",
        ])
        return token


class PrintJob(models.Model):
    """A single rendered label (PNG) queued for an agent to print."""

    PENDING = "pending"
    CLAIMED = "claimed"
    PRINTED = "printed"
    FAILED = "failed"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (CLAIMED, "Claimed"),
        (PRINTED, "Printed"),
        (FAILED, "Failed"),
    ]

    agent = models.ForeignKey(
        PrintAgent, on_delete=models.CASCADE, related_name="jobs"
    )
    # PNG bytes stored in the DB (not the public media dir) since labels carry
    # children's names and pickup codes; served only via the authed agent API.
    image_data = models.BinaryField()
    kind = models.CharField(max_length=20, default="label")  # child / pickup / test
    description = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["agent", "status", "created_at"],
                name="ck_printjob_agent_status_idx",
            )
        ]

    def __str__(self):
        return f"{self.kind} job #{self.pk} ({self.status})"

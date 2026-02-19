import random
import string
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from people.models import Person


# Characters that are easy to read and won't be confused
# Excludes: 0/O, 1/I/L, 5/S
SECURITY_CODE_CHARS = "ABCDEFGHJKMNPQRTUVWXYZ234679"


def generate_security_code(length=4):
    """Generate a random security code for check-in."""
    return "".join(random.choices(SECURITY_CODE_CHARS, k=length))


class Room(models.Model):
    """Physical room where people are checked in."""

    name = models.CharField(max_length=100)
    building = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    # Age/grade range for auto-assignment
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age = models.PositiveIntegerField(null=True, blank=True)
    min_grade = models.CharField(max_length=20, blank=True)
    max_grade = models.CharField(max_length=20, blank=True)

    # For ordering rooms in selection lists
    sort_order = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        if self.building:
            return f"{self.name} ({self.building})"
        return self.name

    def current_count(self, session):
        """Get current number of people checked into this room for a session."""
        return CheckIn.objects.filter(
            session=session, room=self, checked_out_at__isnull=True
        ).count()

    def is_at_capacity(self, session):
        """Check if room is at capacity for a session."""
        if not self.capacity:
            return False
        return self.current_count(session) >= self.capacity


class CheckInSession(models.Model):
    """Represents a check-in event/service time."""

    name = models.CharField(max_length=100)  # "Sunday 9am Service"
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    # Optional link to an event
    event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, blank=True
    )

    # Rooms available for this session
    rooms = models.ManyToManyField(Room, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sessions",
    )

    class Meta:
        ordering = ["-date", "-start_time"]

    def __str__(self):
        return f"{self.name} - {self.date}"

    @property
    def is_open(self):
        """Check if session is currently open for check-in."""
        if not self.is_active:
            return False
        now = timezone.localtime()
        if self.date != now.date():
            return False
        return self.start_time <= now.time() <= self.end_time

    def total_checked_in(self):
        """Get total number of people currently checked in."""
        return self.checkins.filter(checked_out_at__isnull=True).count()


class CheckIn(models.Model):
    """Individual check-in record."""

    session = models.ForeignKey(
        CheckInSession, on_delete=models.CASCADE, related_name="checkins"
    )
    person = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="checkins"
    )
    room = models.ForeignKey(
        Room, on_delete=models.SET_NULL, null=True, blank=True, related_name="checkins"
    )

    # Security code for pickup verification - same for all family members
    security_code = models.CharField(max_length=8, db_index=True)

    # Check-in tracking
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_in_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checkins_performed",
    )

    # Check-out tracking
    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_out_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checkouts_performed",
    )

    # Label printing tracking
    child_label_printed = models.BooleanField(default=False)
    parent_label_printed = models.BooleanField(default=False)

    # Notes (allergies alert, special instructions)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ["session", "person"]
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.person} - {self.session}"

    @property
    def is_checked_out(self):
        return self.checked_out_at is not None

    def checkout(self, user=None):
        """Mark this check-in as checked out."""
        self.checked_out_at = timezone.now()
        self.checked_out_by = user
        self.save(update_fields=["checked_out_at", "checked_out_by"])


class PrinterConfiguration(models.Model):
    """Printer setup for label printing."""

    PRINTER_TYPES = [
        ("escpos", "ESC/POS (Generic Thermal)"),
        ("brother", "Brother QL Series"),
        ("cups", "CUPS/System Printer"),
        ("zpl", "Zebra (ZPL)"),
    ]

    name = models.CharField(max_length=100)
    printer_type = models.CharField(max_length=20, choices=PRINTER_TYPES)

    # Connection details (varies by type)
    # ESC/POS USB: "/dev/usb/lp0" or "usb://0x0416:0x5011"
    # ESC/POS Network: "tcp://192.168.1.100:9100"
    # Brother: "tcp://192.168.1.100:9100" or "usb://0x04f9:0x209c"
    # CUPS: "Brother_QL-820NWB" (printer name)
    # ZPL: "tcp://192.168.1.100:9100"
    connection_string = models.CharField(max_length=255)

    # Label settings
    label_width_mm = models.PositiveIntegerField(default=62)
    label_height_mm = models.PositiveIntegerField(
        null=True, blank=True, help_text="Leave blank for continuous roll"
    )

    # DPI setting (203 is common for thermal, 300 for higher-end)
    dpi = models.PositiveIntegerField(default=203)

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Printer Configuration"
        verbose_name_plural = "Printer Configurations"

    def __str__(self):
        return f"{self.name} ({self.get_printer_type_display()})"

    def save(self, *args, **kwargs):
        # Ensure only one default printer
        if self.is_default:
            PrinterConfiguration.objects.filter(is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)
        super().save(*args, **kwargs)


class LabelTemplate(models.Model):
    """Customizable label designs stored as JSON."""

    LABEL_TYPES = [
        ("child", "Child Name Tag"),
        ("parent", "Parent Claim Tag"),
        ("allergy", "Allergy Alert"),
        ("visitor", "Visitor Badge"),
    ]

    name = models.CharField(max_length=100)
    label_type = models.CharField(max_length=20, choices=LABEL_TYPES)

    # Template stored as JSON with layout instructions
    # Example: {"elements": [{"type": "text", "field": "name", "x": 10, "y": 20, "font_size": 48}]}
    template_json = models.JSONField(default=dict)

    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["label_type", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_label_type_display()})"

    def save(self, *args, **kwargs):
        # Ensure only one default per label type
        if self.is_default:
            LabelTemplate.objects.filter(
                label_type=self.label_type, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

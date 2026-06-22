import re
from datetime import date

from django.db import models


def normalize_phone(phone: str) -> str:
    """Strip all non-digit characters from a phone number."""
    return re.sub(r"\D+", "", phone or "")


class Person(models.Model):
    GRADE_CHOICES = [
        ("pre-k", "Pre-K"),
        ("k", "Kindergarten"),
        ("1", "1st Grade"),
        ("2", "2nd Grade"),
        ("3", "3rd Grade"),
        ("4", "4th Grade"),
        ("5", "5th Grade"),
        ("6", "6th Grade"),
        ("7", "7th Grade"),
        ("8", "8th Grade"),
        ("9", "9th Grade"),
        ("10", "10th Grade"),
        ("11", "11th Grade"),
        ("12", "12th Grade"),
    ]

    MARITAL_STATUS_CHOICES = [
        ("single", "Single"),
        ("married", "Married"),
        ("engaged", "Engaged"),
        ("separated", "Separated"),
        ("divorced", "Divorced"),
        ("widowed", "Widowed"),
    ]

    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("other", "Other"),
        ("unknown", "Prefer not to say"),
    ]

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    # Stable id from an external system (e.g. "rock:1234") so migrations/imports
    # are idempotent — match on this before falling back to name/email/phone.
    external_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    email = models.EmailField(blank=True, null=True, db_index=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    normalized_phone = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        editable=False,
        help_text="Auto-generated digits-only version of phone for fast lookups.",
    )
    phone_opt_in = models.BooleanField(
        default=True,
        help_text="Can this person receive text messages at their phone number?",
    )
    birthdate = models.DateField(blank=True, null=True)
    grade = models.CharField(
        max_length=20, choices=GRADE_CHOICES, blank=True, null=True
    )
    marital_status = models.CharField(
        max_length=20, choices=MARITAL_STATUS_CHOICES, blank=True, null=True
    )
    gender = models.CharField(
        max_length=20, choices=GENDER_CHOICES, blank=True, null=True
    )
    profile_photo = models.ImageField(
        upload_to="people/photos/", blank=True, null=True
    )
    address_line1 = models.CharField(
        "Address line 1", max_length=255, blank=True, null=True
    )
    address_line2 = models.CharField(
        "Address line 2", max_length=255, blank=True, null=True
    )
    city = models.CharField(max_length=120, blank=True, null=True)
    state = models.CharField(max_length=80, blank=True, null=True)
    postal_code = models.CharField("ZIP / Postal Code", max_length=20, blank=True, null=True)
    salvation_date = models.DateField(blank=True, null=True)
    baptism_date = models.DateField(blank=True, null=True)
    first_visit_date = models.DateField(blank=True, null=True)
    allergies = models.TextField(blank=True, null=True)
    security_notes = models.TextField(blank=True, null=True)
    # Guardian's photo/likeness permission. Three states so we can tell an
    # explicit "no photos" (which prints a label badge) apart from "never asked"
    # — the default for migrated/unknown records, which prints nothing.
    PHOTO_CONSENT_CHOICES = [
        ("unknown", "Not asked"),
        ("granted", "Granted"),
        ("denied", "Denied — no photos"),
    ]
    photo_consent = models.CharField(
        max_length=10, choices=PHOTO_CONSENT_CHOICES, default="unknown",
        help_text="Guardian's photo/likeness permission (relevant for minors).",
    )
    # Custody/security tracking (only relevant for minors)
    custody_flag = models.BooleanField(default=False)
    custody_notes = models.TextField(blank=True)
    unauthorized_pickup = models.TextField(blank=True)
    # Emergency contact for this person (esp. a minor). Free-form so it can be
    # someone OUTSIDE the household — e.g. a family friend named on a VBS form.
    # The child label uses this when a phone is set, otherwise it falls back to a
    # household adult's phone (see label_generator._emergency_contact).
    emergency_contact_name = models.CharField(max_length=120, blank=True, default="")
    emergency_contact_phone = models.CharField(max_length=50, blank=True, default="")
    emergency_contact_relationship = models.CharField(
        max_length=80, blank=True, default="",
        help_text="How this contact relates to the person (e.g. Grandmother, Family friend).",
    )
    STATUS_CHOICES = [
        ("guest", "Guest"),
        ("visitor", "Visitor"),
        ("regular_attendee", "Regular Attendee"),
        ("member", "Member"),
        ("volunteer", "Volunteer"),
        ("inactive", "Inactive"),
    ]

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default="guest",
    )
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        if not self.birthdate:
            return None
        today = date.today()
        years = today.year - self.birthdate.year - (
            (today.month, today.day) < (self.birthdate.month, self.birthdate.day)
        )
        # A future-dated birthdate (bad data) would yield a negative age; treat
        # it as unknown so it never prints a "-29" on a label or tile.
        return years if years >= 0 else None

    @property
    def is_minor(self):
        """Returns True if person is under 18, False if 18+, None if unknown."""
        if self.age is None:
            return None
        return self.age < 18

    @property
    def formatted_address(self):
        parts = [
            self.address_line1,
            self.address_line2,
            ", ".join(filter(None, [self.city, self.state])) or None,
            self.postal_code,
        ]
        return "\n".join([p for p in parts if p])

    def save(self, *args, **kwargs):
        self.normalized_phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

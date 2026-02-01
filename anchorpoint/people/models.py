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

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True, null=True)
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
    status = models.CharField(max_length=50, default="guest")
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
        return years

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

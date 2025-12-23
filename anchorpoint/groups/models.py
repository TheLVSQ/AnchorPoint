from django.db import models


class Group(models.Model):
    CATEGORY_CHOICES = [
        ("volunteer", "Volunteer Team"),
        ("checkin", "Check-In Classroom"),
        ("community", "Community Group"),
        ("event", "Event Registration"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=150, unique=True)
    short_code = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional code used for kiosks or attendance sheets.",
    )
    description = models.TextField(blank=True)
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="volunteer"
    )
    location = models.CharField(max_length=120, blank=True)
    meeting_schedule = models.CharField(
        max_length=120,
        blank=True,
        help_text="e.g. Sundays at 9:00am or Every 2nd Tuesday evening.",
    )
    capacity = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    ROLE_CHOICES = [
        ("member", "Member"),
        ("leader", "Leader"),
    ]

    group = models.ForeignKey(
        Group,
        related_name="memberships",
        on_delete=models.CASCADE,
    )
    person = models.ForeignKey(
        "people.Person",
        related_name="group_memberships",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="member",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("group", "person")
        ordering = ["group__name", "person__last_name"]

    def __str__(self):
        return f"{self.person} → {self.group}"

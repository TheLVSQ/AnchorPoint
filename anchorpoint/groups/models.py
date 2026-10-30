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

    # Check-in classrooms and event-registration groups hold kids and registrants, not
    # people who get scheduled to serve: no positions or serving weeks there.
    NOT_SCHEDULABLE = ("checkin", "event")

    @property
    def is_schedulable(self):
        return self.category not in self.NOT_SCHEDULABLE


class Position(models.Model):
    """A role on a team that a person can be scheduled into (Keys, Vocals, Sound...)."""

    group = models.ForeignKey(Group, related_name="positions", on_delete=models.CASCADE)
    name = models.CharField(max_length=80)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["group", "name"], name="unique_position_per_group"),
        ]

    def __str__(self):
        return self.name


ALL_WEEKS = "12345"
WEEK_LABELS = {"1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th"}


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
    # Scheduling: the positions this person can fill on this team, and which weeks of the
    # month they serve ("3" = 3rd Sunday only). See scheduling/availability.py.
    positions = models.ManyToManyField(Position, blank=True, related_name="memberships")
    serving_weeks = models.CharField(
        max_length=5,
        default=ALL_WEEKS,
        help_text="Weeks of the month this person serves on this team: digits 1-5.",
    )

    class Meta:
        unique_together = ("group", "person")
        ordering = ["group__name", "person__last_name"]

    def __str__(self):
        return f"{self.person} → {self.group}"

    def serves_week(self, week):
        return str(week) in self.serving_weeks

    @property
    def serving_weeks_label(self):
        """"Every week", "3rd only", "1st and 3rd"..."""
        weeks = [WEEK_LABELS[w] for w in sorted(self.serving_weeks) if w in WEEK_LABELS]
        if self.serving_weeks == ALL_WEEKS:
            return "Every week"
        if not weeks:
            return "Not serving"
        if len(weeks) == 1:
            return f"{weeks[0]} only"
        return ", ".join(weeks[:-1]) + f" and {weeks[-1]}"

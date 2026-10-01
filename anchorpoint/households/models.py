from django.db import models


class Household(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=120, blank=True, null=True)
    state = models.CharField(max_length=80, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    primary_adult = models.ForeignKey(
        "people.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_households",
    )
    members = models.ManyToManyField(
        "people.Person",
        through="HouseholdMember",
        related_name="households",
        blank=True,
    )

    def __str__(self):
        return self.name

    @property
    def formatted_address(self):
        parts = [
            self.address_line1,
            self.address_line2,
            ", ".join(filter(None, [self.city, self.state])) or None,
            self.postal_code,
        ]
        return "\n".join([part for part in parts if part])


class HouseholdMember(models.Model):
    class RelationshipType(models.TextChoices):
        ADULT = ("adult", "Adult")
        CHILD = ("child", "Child")
        STUDENT = ("student", "Student")
        OTHER = ("other", "Other")

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="memberships"
    )
    person = models.ForeignKey(
        "people.Person",
        on_delete=models.CASCADE,
        related_name="household_memberships",
    )
    relationship_type = models.CharField(
        max_length=20,
        choices=RelationshipType.choices,
        default=RelationshipType.ADULT,
    )

    class Meta:
        unique_together = ("household", "person")
        ordering = ["household__name", "person__last_name"]

    def __str__(self):
        return f"{self.person} → {self.household}"

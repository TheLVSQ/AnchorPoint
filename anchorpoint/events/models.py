import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class EventQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)

    def upcoming(self):
        now = timezone.now()
        return (
            self.published()
            .filter(occurrences__starts_at__gte=now)
            .distinct()
        )


class Event(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=255, blank=True)
    summary = models.CharField(
        max_length=300,
        blank=True,
        help_text="Short teaser used on cards and embeds.",
    )
    description = models.TextField(blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    location_address_line1 = models.CharField(max_length=255, blank=True)
    location_address_line2 = models.CharField(max_length=255, blank=True)
    location_city = models.CharField(max_length=120, blank=True)
    location_state = models.CharField(max_length=80, blank=True)
    location_postal_code = models.CharField(max_length=20, blank=True)
    location_notes = models.TextField(blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    is_free = models.BooleanField(default=True)
    cost_amount = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True
    )
    registration_token = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True
    )
    registration_deadline = models.DateTimeField(blank=True, null=True)
    registration_capacity = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Optional cap on total registrations.",
    )
    registration_open = models.BooleanField(default=True)
    is_published = models.BooleanField(
        default=True, help_text="Unpublished events stay hidden from public pages."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or uuid.uuid4().hex[:8]
            slug = base_slug
            counter = 1
            while Event.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                counter += 1
                slug = f"{base_slug}-{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def display_cost(self):
        if self.is_free or not self.cost_amount:
            return "Free"
        return f"${self.cost_amount:.2f}"

    @property
    def location_display(self):
        parts = [
            part
            for part in [
                self.location_name or "",
                self.location_address_line1 or "",
                self.location_address_line2 or "",
                ", ".join(
                    filter(
                        None,
                        [self.location_city, self.location_state],
                    )
                )
                or "",
                self.location_postal_code or "",
            ]
            if part
        ]
        return "\n".join(parts)

    @property
    def next_occurrence(self):
        now = timezone.now()
        return (
            self.occurrences.filter(starts_at__gte=now).order_by("starts_at").first()
        )

    def upcoming_occurrences(self):
        now = timezone.now()
        return self.occurrences.filter(starts_at__gte=now).order_by("starts_at")

    @property
    def primary_photo(self):
        return self.photos.order_by("display_order", "id").first()

    def can_register(self):
        if not self.registration_open:
            return False
        if self.registration_deadline and timezone.now() > self.registration_deadline:
            return False
        if self.registration_capacity is None:
            return True
        total = (
            self.registrations.aggregate(
                total=models.Sum("number_of_attendees")
            ).get("total")
            or 0
        )
        return total < self.registration_capacity


class EventOccurrence(models.Model):
    event = models.ForeignKey(
        Event, related_name="occurrences", on_delete=models.CASCADE
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(blank=True, null=True)
    is_all_day = models.BooleanField(default=False)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.event.title} @ {self.starts_at:%Y-%m-%d %H:%M}"


class EventPhoto(models.Model):
    event = models.ForeignKey(
        Event, related_name="photos", on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to="events/photos/")
    caption = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "id"]

    def __str__(self):
        return f"Photo for {self.event.title}"


class EventRegistration(models.Model):
    event = models.ForeignKey(
        Event, related_name="registrations", on_delete=models.CASCADE
    )
    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    number_of_attendees = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.event.title}"

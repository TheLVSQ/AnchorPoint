import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def event_release_upload_path(instance, filename):
    slug = instance.slug or "event"
    return f"events/releases/{slug}/{filename}"


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


class ReleaseDocument(models.Model):
    CATEGORY_LIABILITY = "liability"
    CATEGORY_MEDIA = "media"
    CATEGORY_OTHER = "other"
    CATEGORY_CHOICES = [
        (CATEGORY_LIABILITY, "Liability"),
        (CATEGORY_MEDIA, "Media"),
        (CATEGORY_OTHER, "Other"),
    ]

    name = models.CharField(max_length=200)
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_LIABILITY
    )
    file = models.FileField(upload_to="events/releases/library/")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class Event(models.Model):
    COST_TYPE_PER_PERSON = "per_person"
    COST_TYPE_PER_FAMILY = "per_family"
    COST_TYPE_PER_GROUP = "per_group"
    COST_TYPE_CHOICES = [
        (COST_TYPE_PER_PERSON, "Per Person"),
        (COST_TYPE_PER_FAMILY, "Per Family"),
        (COST_TYPE_PER_GROUP, "Per Group"),
    ]

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
    cost_type = models.CharField(
        max_length=20,
        choices=COST_TYPE_CHOICES,
        default=COST_TYPE_PER_PERSON,
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
    registration_group = models.ForeignKey(
        "groups.Group",
        related_name="events",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        help_text="Auto-generated group that holds attendees for rosters.",
    )
    liability_release_document = models.ForeignKey(
        ReleaseDocument,
        related_name="liability_events",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        limit_choices_to={"category": ReleaseDocument.CATEGORY_LIABILITY},
    )
    liability_release_custom = models.FileField(
        upload_to=event_release_upload_path, blank=True, null=True
    )
    media_release_document = models.ForeignKey(
        ReleaseDocument,
        related_name="media_events",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        limit_choices_to={"category": ReleaseDocument.CATEGORY_MEDIA},
    )
    media_release_custom = models.FileField(
        upload_to=event_release_upload_path, blank=True, null=True
    )

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
        suffix = ""
        cost_label = self.get_cost_type_display()
        if cost_label:
            suffix = f" {cost_label.lower()}"
        return f"${self.cost_amount:.2f}{suffix}"

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

    def _release_link(self, category):
        if category == "liability":
            if self.liability_release_custom:
                return (
                    self.liability_release_custom.url,
                    f"{self.title} Liability Release",
                )
            if (
                self.liability_release_document
                and self.liability_release_document.file
            ):
                return (
                    self.liability_release_document.file.url,
                    self.liability_release_document.name,
                )
        else:
            if self.media_release_custom:
                return (
                    self.media_release_custom.url,
                    f"{self.title} Media Release",
                )
            if (
                self.media_release_document
                and self.media_release_document.file
            ):
                return (
                    self.media_release_document.file.url,
                    self.media_release_document.name,
                )
        return (None, None)

    def liability_release_link(self):
        return self._release_link("liability")

    def media_release_link(self):
        return self._release_link("media")


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
    birthdate = models.DateField(blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    number_of_attendees = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    liability_release_accepted_at = models.DateTimeField(blank=True, null=True)
    liability_release_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name captured when the liability release was accepted.",
    )
    liability_release_ip = models.GenericIPAddressField(blank=True, null=True)
    liability_release_user_agent = models.TextField(blank=True)
    media_release_accepted_at = models.DateTimeField(blank=True, null=True)
    media_release_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name captured when the media release was accepted.",
    )
    media_release_ip = models.GenericIPAddressField(blank=True, null=True)
    media_release_user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.event.title}"


class EventRegistrationAttendee(models.Model):
    MATCH_STATUS_PENDING = "pending"
    MATCH_STATUS_MATCHED = "matched"
    MATCH_STATUS_DISMISSED = "dismissed"
    MATCH_STATUS_CHOICES = [
        (MATCH_STATUS_PENDING, "Pending Review"),
        (MATCH_STATUS_MATCHED, "Matched"),
        (MATCH_STATUS_DISMISSED, "Dismissed"),
    ]
    registration = models.ForeignKey(
        EventRegistration,
        related_name="attendees",
        on_delete=models.CASCADE,
    )
    event = models.ForeignKey(
        Event,
        related_name="registration_attendees",
        on_delete=models.CASCADE,
    )
    person = models.ForeignKey(
        "people.Person",
        related_name="event_registrations",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    group = models.ForeignKey(
        "groups.Group",
        related_name="event_attendees",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        help_text="Optional group used for rosters and reporting.",
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    birthdate = models.DateField(blank=True, null=True)
    is_minor = models.BooleanField(
        default=False,
        help_text="Captured at registration time to know if guardian details are required.",
    )
    grade = models.CharField(max_length=20, blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    parent_guardian_name = models.CharField(max_length=255, blank=True)
    parent_guardian_email = models.EmailField(blank=True)
    parent_guardian_phone = models.CharField(max_length=50, blank=True)
    allergies = models.TextField(blank=True)
    medical_notes = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True)
    emergency_contact_relationship = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    match_status = models.CharField(
        max_length=20,
        choices=MATCH_STATUS_CHOICES,
        default=MATCH_STATUS_PENDING,
    )
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="matched_event_attendees",
    )
    matched_at = models.DateTimeField(blank=True, null=True)
    match_notes = models.TextField(blank=True)
    suggested_person = models.ForeignKey(
        "people.Person",
        related_name="suggested_event_registrations",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.event.title})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

from django.conf import settings
from django.db import models


class Communication(models.Model):
    """One thing sent to one person or many (see GLOSSARY.md)."""

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        VOICE = "voice", "Phone call"
        EMAIL = "email", "Email"

    class Kind(models.TextChoices):
        BROADCAST = "broadcast", "Broadcast"
        TRANSACTIONAL = "transactional", "Transactional"

    class TargetType(models.TextChoices):
        PERSON = "person", "Individual person"
        GROUP = "group", "Group"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        SENDING = "sending", "Sending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    channel = models.CharField(max_length=10, choices=Channel.choices)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.BROADCAST)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="communications",
    )
    title = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    audio_file = models.FileField(upload_to="communications/phone_blasts/", blank=True)
    notes = models.TextField(blank=True)
    target_type = models.CharField(max_length=20, choices=TargetType.choices, blank=True)
    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeted_communications",
    )
    group = models.ForeignKey(
        "groups.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="communications",
    )
    scheduled_for = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["kind", "status", "scheduled_for"])]

    def __str__(self):
        return self.title or f"{self.get_channel_display()} #{self.pk or 'new'}"

    @property
    def summary(self):
        """One line for a person's communication history."""
        if self.kind == self.Kind.TRANSACTIONAL:
            return self.title or "Automatic message"
        if self.channel == self.Channel.VOICE:
            return f"Phone blast '{self.title}'"
        if self.channel == self.Channel.EMAIL and self.subject:
            return f"'{self.subject}'"
        sender = self.created_by.get_full_name() or self.created_by.username if self.created_by else "staff"
        return f"{self.get_channel_display()} sent by {sender}"

    def delivery_counts(self):
        """{status: count} over this Communication's Deliveries."""
        from django.db.models import Count

        return {
            row["status"]: row["count"]
            for row in self.deliveries.values("status").annotate(count=Count("id"))
        }


class Delivery(models.Model):
    """One recipient's copy of a Communication (see GLOSSARY.md)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        ANSWERED = "answered", "Answered"
        NO_ANSWER = "no_answer", "No answer"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class SkipReason(models.TextChoices):
        OPTED_OUT = "opted_out", "Opted out"
        NO_ADDRESS = "no_address", "No phone or email on file"

    communication = models.ForeignKey(
        Communication, related_name="deliveries", on_delete=models.CASCADE
    )
    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deliveries",
    )
    address = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    skip_reason = models.CharField(max_length=20, choices=SkipReason.choices, blank=True)
    provider_id = models.CharField(max_length=64, blank=True, db_index=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["communication", "person"]
        verbose_name_plural = "deliveries"

    def __str__(self):
        return f"{self.person or self.address} for {self.communication}"

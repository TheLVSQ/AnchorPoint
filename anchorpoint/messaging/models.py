from django.conf import settings
from django.db import models


class SmsMessage(models.Model):
    class TargetType(models.TextChoices):
        PERSON = "person", "Individual person"
        GROUP = "group", "Group"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sms_messages",
    )
    body = models.TextField(help_text="Plain-text body sent to all recipients.")
    target_type = models.CharField(
        max_length=20, choices=TargetType.choices, default=TargetType.PERSON
    )
    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="direct_messages",
    )
    group = models.ForeignKey(
        "groups.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="group_messages",
    )
    scheduled_for = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"SMS #{self.pk or 'new'}"

    @property
    def is_scheduled(self):
        return bool(self.scheduled_for)


class SmsRecipient(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    message = models.ForeignKey(
        SmsMessage,
        related_name="recipients",
        on_delete=models.CASCADE,
    )
    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_messages",
    )
    phone_number = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    sent_at = models.DateTimeField(blank=True, null=True)
    twilio_sid = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["message", "person"]

    def __str__(self):
        return f"{self.person or self.phone_number} for SMS {self.message_id}"


class PhoneBlast(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="phone_blasts",
    )
    title = models.CharField(max_length=255)
    group = models.ForeignKey(
        "groups.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phone_blasts",
    )
    audio_file = models.FileField(upload_to="communications/phone_blasts/")
    notes = models.TextField(blank=True)
    scheduled_for = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Phone blast #{self.pk or 'new'}"

    @property
    def is_scheduled(self):
        return bool(self.scheduled_for)


class PhoneCall(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        NO_ANSWER = "no_answer", "No Answer"

    blast = models.ForeignKey(
        PhoneBlast,
        related_name="calls",
        on_delete=models.CASCADE,
    )
    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phone_calls",
    )
    phone_number = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    call_sid = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["blast", "person"]

    def __str__(self):
        return f"{self.person or self.phone_number} call"


class CommunicationLog(models.Model):
    class CommunicationType(models.TextChoices):
        SMS = "sms", "SMS"
        PHONE = "phone", "Phone Call"

    person = models.ForeignKey(
        "people.Person",
        related_name="communication_logs",
        on_delete=models.CASCADE,
    )
    communication_type = models.CharField(
        max_length=20, choices=CommunicationType.choices
    )
    summary = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    metadata = models.JSONField(blank=True, null=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="communication_logs",
    )
    sms_message = models.ForeignKey(
        SmsMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logs",
    )
    phone_blast = models.ForeignKey(
        PhoneBlast,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_communication_type_display()} log for {self.person}"

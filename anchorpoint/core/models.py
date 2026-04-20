from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        VOLUNTEER_ADMIN = "volunteer_admin", "Volunteer Admin"
        VOLUNTEER = "volunteer", "Volunteer"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.VOLUNTEER,
    )
    phone_number = models.CharField(max_length=50, blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    bio = models.TextField(blank=True)
    can_manage_communications = models.BooleanField(
        default=False,
        help_text="Allow this user to manage SMS and phone blast communications.",
    )

    def __str__(self):
        display_name = self.user.get_full_name() or self.user.username
        return f"{display_name} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def has_communications_access(self):
        return self.is_admin or self.can_manage_communications


User = get_user_model()


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    # Ensure every user has a profile so role checks never fail in templates.
    if created:
        UserProfile.objects.create(user=instance)
        # Send welcome email — import here to avoid circular imports
        from core.email_service import send_welcome_email
        send_welcome_email(instance)
    else:
        UserProfile.objects.get_or_create(user=instance)


class OrganizationSettings(models.Model):
    name = models.CharField(max_length=255, blank=True)
    logo = models.ImageField(upload_to="organization/logo/", blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    twilio_account_sid = models.CharField(max_length=64, blank=True)
    twilio_auth_token = models.CharField(max_length=64, blank=True)
    twilio_phone_number = models.CharField(max_length=30, blank=True)
    sms_blackout_start = models.TimeField(blank=True, null=True)
    sms_blackout_end = models.TimeField(blank=True, null=True)
    kiosk_pin = models.CharField(
        max_length=10,
        blank=True,
        help_text="Optional 4-6 digit code required to unlock kiosk mode.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Organization settings"

    def __str__(self):
        return self.name or "Organization Settings"

    @classmethod
    def load(cls):
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance

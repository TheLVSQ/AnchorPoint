from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import OrganizationSettings
from messaging.models import PhoneBlast, SmsMessage
from messaging.services import (
    TwilioConfigurationError,
    TwilioRequestError,
    deliver_phone_blast,
    deliver_sms_message,
)


class Command(BaseCommand):
    help = "Deliver any scheduled SMS messages or phone blasts that are due."

    def handle(self, *args, **options):
        settings_obj = OrganizationSettings.load()
        now = timezone.now()
        sms_queryset = SmsMessage.objects.filter(
            status=SmsMessage.Status.SCHEDULED,
            scheduled_for__lte=now,
        )
        phone_queryset = PhoneBlast.objects.filter(
            status=PhoneBlast.Status.SCHEDULED,
            scheduled_for__lte=now,
        )

        for sms in sms_queryset:
            try:
                deliver_sms_message(sms, settings_obj=settings_obj)
            except (TwilioConfigurationError, TwilioRequestError) as exc:
                self.stderr.write(f"Failed to deliver SMS #{sms.pk}: {exc}")
            else:
                self.stdout.write(f"Delivered SMS #{sms.pk}")

        for blast in phone_queryset:
            try:
                deliver_phone_blast(blast, settings_obj=settings_obj)
            except (TwilioConfigurationError, TwilioRequestError) as exc:
                self.stderr.write(f"Failed to deliver PhoneBlast #{blast.pk}: {exc}")
            else:
                self.stdout.write(f"Delivered PhoneBlast #{blast.pk}")

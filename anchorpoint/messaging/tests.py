from datetime import datetime, time, timedelta, timezone as dt_timezone
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import OrganizationSettings
from groups.models import Group, GroupMembership
from people.models import Person

from .forms import PhoneBlastForm, SmsMessageForm
from .models import PhoneBlast, PhoneCall, SmsMessage, SmsRecipient
from .services import deliver_phone_blast, deliver_sms_message


class SmsMessageFormTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()
        self.person = Person.objects.create(
            first_name="Test",
            last_name="Person",
            phone="+15555550100",
            phone_opt_in=True,
        )

    def test_blocked_when_inside_blackout_window(self):
        self.settings_obj.sms_blackout_start = time(0, 0)
        self.settings_obj.sms_blackout_end = time(23, 59)
        self.settings_obj.save()

        form = SmsMessageForm(
            data={
                "target_type": SmsMessage.TargetType.PERSON,
                "person": self.person.pk,
                "group": "",
                "body": "Hi there",
                "scheduled_for": "",
            },
            organization_settings=self.settings_obj,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("blackout", form.non_field_errors()[0])

    def test_group_recipient_selection(self):
        group = Group.objects.create(name="Students", category="other")
        GroupMembership.objects.create(group=group, person=self.person)

        future = datetime.now(dt_timezone.utc) + timedelta(days=1)
        form = SmsMessageForm(
            data={
                "target_type": SmsMessage.TargetType.GROUP,
                "person": "",
                "group": group.pk,
                "body": "Reminder",
                "scheduled_for": future.isoformat(),
            },
            organization_settings=self.settings_obj,
        )
        self.assertTrue(form.is_valid(), form.errors)
        recipients = form.get_recipients()
        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0], self.person)


class PhoneBlastFormTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()
        self.person = Person.objects.create(
            first_name="Call",
            last_name="Receiver",
            phone="+15555550123",
            phone_opt_in=True,
        )
        self.group = Group.objects.create(name="Leaders", category="volunteer")
        GroupMembership.objects.create(group=self.group, person=self.person)

    def test_prevents_blank_group(self):
        form = PhoneBlastForm(
            data={
                "title": "Voicemail",
                "group": "",
                "scheduled_for": "",
                "notes": "",
            },
            files={
                "audio_file": SimpleUploadedFile("note.mp3", b"data"),
            },
            organization_settings=self.settings_obj,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("group", form.errors)


class MessagingDeliveryTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.settings_obj = OrganizationSettings.load()
        self.settings_obj.twilio_account_sid = "AC123"
        self.settings_obj.twilio_auth_token = "token"
        self.settings_obj.twilio_phone_number = "+15551234567"
        self.settings_obj.save()
        self.user = get_user_model().objects.create_user(
            username="comm", password="password"
        )
        self.person = Person.objects.create(
            first_name="Recipient",
            last_name="One",
            phone="+15551112222",
            phone_opt_in=True,
        )

    def test_deliver_sms_updates_log(self):
        message = SmsMessage.objects.create(
            created_by=self.user,
            body="Test SMS",
            target_type=SmsMessage.TargetType.PERSON,
        )
        SmsRecipient.objects.create(
            message=message,
            person=self.person,
            phone_number=self.person.phone,
        )
        with patch("messaging.services.TwilioService.send_sms", return_value="SM123"):
            success, failure = deliver_sms_message(
                message, settings_obj=self.settings_obj
            )
        self.assertEqual(success, 1)
        self.assertEqual(failure, 0)
        recipient = message.recipients.first()
        self.assertEqual(recipient.status, SmsRecipient.Status.SENT)
        self.assertEqual(recipient.twilio_sid, "SM123")
        self.assertEqual(
            self.person.communication_logs.count(),
            1,
        )

    def test_deliver_phone_blast_tracks_calls(self):
        audio = SimpleUploadedFile("message.mp3", b"audio-bytes")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Weekly Update",
            audio_file=audio,
        )
        PhoneCall.objects.create(
            blast=blast,
            person=self.person,
            phone_number=self.person.phone,
        )
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA123"
        ):
            success, failure = deliver_phone_blast(
                blast, settings_obj=self.settings_obj
            )
        self.assertEqual(success, 1)
        self.assertEqual(failure, 0)
        call = blast.calls.first()
        self.assertEqual(call.status, PhoneCall.Status.COMPLETED)
        self.assertEqual(call.call_sid, "CA123")
        self.assertEqual(self.person.communication_logs.count(), 1)

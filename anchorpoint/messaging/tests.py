import base64
import hashlib
import hmac
import shutil
import tempfile
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

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
        self.assertEqual(call.status, PhoneCall.Status.PENDING)  # stays PENDING until webhook
        self.assertEqual(call.call_sid, "CA123")
        self.assertEqual(self.person.communication_logs.count(), 1)
        blast.refresh_from_db()
        self.assertEqual(blast.status, PhoneBlast.Status.PROCESSING)

    def test_deliver_phone_blast_passes_status_callback(self):
        """deliver_phone_blast passes the StatusCallback URL to initiate_call."""
        audio = SimpleUploadedFile("message.mp3", b"audio-bytes")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Callback Test",
            audio_file=audio,
        )
        PhoneCall.objects.create(
            blast=blast,
            person=self.person,
            phone_number=self.person.phone,
        )
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA999"
        ) as mock_call:
            deliver_phone_blast(
                blast,
                settings_obj=self.settings_obj,
                base_url="https://example.com",
            )
        mock_call.assert_called_once_with(
            self.person.phone,
            "https://example.com/media/message.mp3",
            status_callback_url="https://example.com/communications/phone-blast/webhook/call-status/",
        )


class PhoneCallWebhookTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()
        self.settings_obj.twilio_account_sid = "AC123"
        self.settings_obj.twilio_auth_token = "test_auth_token"
        self.settings_obj.twilio_phone_number = "+15551234567"
        self.settings_obj.save()
        self.user = get_user_model().objects.create_user(
            username="webhookuser", password="pw"
        )
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe", phone="+15559876543"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        self.blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Test Blast",
            audio_file=audio,
            status=PhoneBlast.Status.PROCESSING,
        )
        self.call = PhoneCall.objects.create(
            blast=self.blast,
            person=self.person,
            phone_number=self.person.phone,
            call_sid="CA_TEST_001",
            status=PhoneCall.Status.PENDING,
        )
        self.webhook_url = reverse("messaging:phone_call_status_webhook")

    def _make_signature(self, url, params):
        sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
        s = url + sorted_params
        mac = hmac.new(
            self.settings_obj.twilio_auth_token.encode("utf-8"),
            s.encode("utf-8"),
            hashlib.sha1,
        )
        return base64.b64encode(mac.digest()).decode()

    def _post_webhook(self, params, sign=True):
        url = "http://testserver" + self.webhook_url
        sig = self._make_signature(url, params) if sign else "invalidsignature"
        return self.client.post(
            self.webhook_url,
            data=params,
            HTTP_X_TWILIO_SIGNATURE=sig,
        )

    def test_completed_call_marks_completed(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.COMPLETED)

    def test_no_answer_marks_no_answer(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "no-answer"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.NO_ANSWER)

    def test_busy_marks_failed(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "busy"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.FAILED)

    def test_failed_marks_failed(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "failed"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.FAILED)

    def test_blast_marked_complete_when_last_call_settles(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        self._post_webhook(params)
        self.blast.refresh_from_db()
        self.assertEqual(self.blast.status, PhoneBlast.Status.COMPLETED)
        self.assertIsNotNone(self.blast.completed_at)

    def test_blast_stays_processing_while_calls_pending(self):
        # Add a second pending call
        PhoneCall.objects.create(
            blast=self.blast,
            person=self.person,
            phone_number="+15550001111",
            call_sid="CA_TEST_002",
            status=PhoneCall.Status.PENDING,
        )
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        self._post_webhook(params)
        self.blast.refresh_from_db()
        self.assertEqual(self.blast.status, PhoneBlast.Status.PROCESSING)

    def test_invalid_signature_returns_403(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        response = self._post_webhook(params, sign=False)
        self.assertEqual(response.status_code, 403)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.PENDING)

    def test_unknown_call_sid_returns_404(self):
        params = {"CallSid": "CA_UNKNOWN", "CallStatus": "completed"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 404)


class PhoneBlastDetailViewTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.user = get_user_model().objects.create_user(
            username="staffuser", password="pw"
        )
        self.user.profile.can_manage_communications = True
        self.user.profile.save()
        self.client.force_login(self.user)

        self.person = Person.objects.create(
            first_name="Test", last_name="Person", phone="+15551112222"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        self.blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Sunday Announcement",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=self.blast, person=self.person,
            phone_number=self.person.phone,
            call_sid="CA001", status=PhoneCall.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=self.blast, person=self.person,
            phone_number="+15550000001",
            call_sid="CA002", status=PhoneCall.Status.NO_ANSWER,
        )

    def test_detail_page_returns_200(self):
        response = self.client.get(
            reverse("messaging:phone_blast_detail", args=[self.blast.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sunday Announcement")

    def test_stats_partial_returns_counts(self):
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1")  # 1 answered, 1 no answer

    def test_stats_partial_includes_polling_when_processing(self):
        self.blast.status = PhoneBlast.Status.PROCESSING
        self.blast.save()
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        self.assertContains(response, "every 5s")

    def test_stats_partial_omits_polling_when_complete(self):
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        self.assertNotContains(response, "every 5s")


class MessagingHomeViewTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.user = get_user_model().objects.create_user(
            username="staffuser2", password="pw"
        )
        self.user.profile.can_manage_communications = True
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_home_shows_blast_stats_summary(self):
        person = Person.objects.create(
            first_name="A", last_name="B", phone="+15550001111"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Test Blast",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=blast, person=person,
            phone_number=person.phone,
            call_sid="CA01", status=PhoneCall.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=blast, person=person,
            phone_number="+15550002222",
            call_sid="CA02", status=PhoneCall.Status.NO_ANSWER,
        )
        response = self.client.get(reverse("messaging:home"))
        self.assertContains(response, "1 answered")
        self.assertContains(response, "1 no answer")

    def test_home_shows_sending_label_when_processing(self):
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="In Progress",
            audio_file=audio,
            status=PhoneBlast.Status.PROCESSING,
        )
        PhoneCall.objects.create(
            blast=blast, person=Person.objects.create(
                first_name="X", last_name="Y", phone="+15550003333"
            ),
            phone_number="+15550003333",
            status=PhoneCall.Status.PENDING,
        )
        response = self.client.get(reverse("messaging:home"))
        self.assertContains(response, "Sending")

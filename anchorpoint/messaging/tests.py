import base64
import hashlib
import hmac
import os
import shutil
import tempfile
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_timezone

from core.models import OrganizationSettings
from groups.models import Group, GroupMembership
from people.models import Person

from .forms import PhoneBlastForm, SmsMessageForm
from .models import PhoneBlast, PhoneCall, SmsMessage, SmsRecipient
from .services import (
    AudioProcessingError,
    TwilioConfigurationError,
    TwilioRequestError,
    TwilioService,
    deliver_phone_blast,
    deliver_sms_message,
    get_site_base_url,
    is_within_blackout_window,
)


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
        # Derive the expected audio URL from the stored file so the assertion is
        # robust to filename suffixing when the test media dir already holds a
        # file of the same name.
        mock_call.assert_called_once_with(
            self.person.phone,
            f"https://example.com{blast.audio_file.url}",
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


# ---------------------------------------------------------------------------
# Blackout window unit tests
# ---------------------------------------------------------------------------

@override_settings(TIME_ZONE="UTC")
class BlackoutWindowTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()

    def _moment(self, hour, minute=0):
        """UTC-aware datetime at the given hour/minute."""
        from django.utils import timezone as tz
        return tz.now().replace(hour=hour, minute=minute, second=0, microsecond=0)

    def test_no_blackout_configured_returns_false(self):
        self.settings_obj.sms_blackout_start = None
        self.settings_obj.sms_blackout_end = None
        self.settings_obj.save()
        self.assertFalse(is_within_blackout_window(self.settings_obj, self._moment(10)))

    def test_start_equals_end_returns_false(self):
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(22, 0)
        self.settings_obj.save()
        self.assertFalse(is_within_blackout_window(self.settings_obj, self._moment(22)))

    def test_inside_normal_window(self):
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(23, 0)
        self.settings_obj.save()
        self.assertTrue(is_within_blackout_window(self.settings_obj, self._moment(22, 30)))

    def test_outside_normal_window(self):
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(23, 0)
        self.settings_obj.save()
        self.assertFalse(is_within_blackout_window(self.settings_obj, self._moment(10)))

    def test_at_window_start_is_inside(self):
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(23, 0)
        self.settings_obj.save()
        self.assertTrue(is_within_blackout_window(self.settings_obj, self._moment(22, 0)))

    def test_at_window_end_is_outside(self):
        # End is exclusive
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(23, 0)
        self.settings_obj.save()
        self.assertFalse(is_within_blackout_window(self.settings_obj, self._moment(23, 0)))

    def test_inside_overnight_window_after_midnight(self):
        # 22:00 → 08:00; checking at 03:00
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(8, 0)
        self.settings_obj.save()
        self.assertTrue(is_within_blackout_window(self.settings_obj, self._moment(3)))

    def test_inside_overnight_window_before_midnight(self):
        # 22:00 → 08:00; checking at 23:00
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(8, 0)
        self.settings_obj.save()
        self.assertTrue(is_within_blackout_window(self.settings_obj, self._moment(23)))

    def test_outside_overnight_window(self):
        # 22:00 → 08:00; checking at 12:00
        self.settings_obj.sms_blackout_start = time(22, 0)
        self.settings_obj.sms_blackout_end = time(8, 0)
        self.settings_obj.save()
        self.assertFalse(is_within_blackout_window(self.settings_obj, self._moment(12)))


# ---------------------------------------------------------------------------
# TwilioService initialisation
# ---------------------------------------------------------------------------

class TwilioServiceInitTests(TestCase):
    def _settings(self, sid="AC123", token="token", phone="+15551234567"):
        s = OrganizationSettings.load()
        s.twilio_account_sid = sid
        s.twilio_auth_token = token
        s.twilio_phone_number = phone
        s.save()
        return s

    def test_raises_when_sid_missing(self):
        with self.assertRaises(TwilioConfigurationError):
            TwilioService(self._settings(sid=""))

    def test_raises_when_token_missing(self):
        with self.assertRaises(TwilioConfigurationError):
            TwilioService(self._settings(token=""))

    def test_raises_when_phone_missing(self):
        with self.assertRaises(TwilioConfigurationError):
            TwilioService(self._settings(phone=""))

    def test_no_error_when_all_configured(self):
        service = TwilioService(self._settings())
        self.assertEqual(service.account_sid, "AC123")
        self.assertEqual(service.from_number, "+15551234567")


# ---------------------------------------------------------------------------
# deliver_sms_message — failure and skip paths
# ---------------------------------------------------------------------------

class SmsDeliveryEdgeCaseTests(TestCase):
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
        self.user = get_user_model().objects.create_user(username="smsedge", password="pw")
        self.person = Person.objects.create(
            first_name="Edge", last_name="Case", phone="+15559990000", phone_opt_in=True
        )

    def _make_message(self):
        msg = SmsMessage.objects.create(
            created_by=self.user,
            body="Hello",
            target_type=SmsMessage.TargetType.PERSON,
        )
        SmsRecipient.objects.create(
            message=msg, person=self.person, phone_number=self.person.phone
        )
        return msg

    def test_twilio_error_marks_recipient_failed(self):
        msg = self._make_message()
        with patch(
            "messaging.services.TwilioService.send_sms",
            side_effect=TwilioRequestError("connection refused"),
        ):
            success, failure = deliver_sms_message(msg, settings_obj=self.settings_obj)
        self.assertEqual(success, 0)
        self.assertEqual(failure, 1)
        recipient = msg.recipients.first()
        self.assertEqual(recipient.status, SmsRecipient.Status.FAILED)
        self.assertIn("connection refused", recipient.error_message)

    def test_all_failed_marks_message_failed(self):
        msg = self._make_message()
        with patch(
            "messaging.services.TwilioService.send_sms",
            side_effect=TwilioRequestError("fail"),
        ):
            deliver_sms_message(msg, settings_obj=self.settings_obj)
        msg.refresh_from_db()
        self.assertEqual(msg.status, SmsMessage.Status.FAILED)

    def test_non_pending_recipient_is_skipped(self):
        msg = self._make_message()
        recipient = msg.recipients.first()
        recipient.status = SmsRecipient.Status.SENT
        recipient.save()
        with patch("messaging.services.TwilioService.send_sms", return_value="SM999") as mock_send:
            deliver_sms_message(msg, settings_obj=self.settings_obj)
        mock_send.assert_not_called()

    def test_failed_recipient_does_not_create_communication_log(self):
        msg = self._make_message()
        with patch(
            "messaging.services.TwilioService.send_sms",
            side_effect=TwilioRequestError("fail"),
        ):
            deliver_sms_message(msg, settings_obj=self.settings_obj)
        self.assertEqual(self.person.communication_logs.count(), 0)


# ---------------------------------------------------------------------------
# deliver_phone_blast — failure, skip, and URL fallback paths
# ---------------------------------------------------------------------------

class PhoneBlastDeliveryEdgeCaseTests(TestCase):
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
        self.user = get_user_model().objects.create_user(username="blstedge", password="pw")
        self.person = Person.objects.create(
            first_name="Blast", last_name="Edge", phone="+15558880000", phone_opt_in=True
        )

    def _make_blast(self):
        audio = SimpleUploadedFile("msg.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user, title="Edge Blast", audio_file=audio
        )
        call = PhoneCall.objects.create(
            blast=blast, person=self.person, phone_number=self.person.phone
        )
        return blast, call

    def test_no_audio_file_raises(self):
        blast = PhoneBlast.objects.create(created_by=self.user, title="No Audio")
        with self.assertRaises(TwilioRequestError):
            deliver_phone_blast(blast, settings_obj=self.settings_obj)

    def test_twilio_error_marks_call_failed(self):
        blast, call = self._make_blast()
        with patch(
            "messaging.services.TwilioService.initiate_call",
            side_effect=TwilioRequestError("timeout"),
        ):
            success, failure = deliver_phone_blast(blast, settings_obj=self.settings_obj)
        self.assertEqual(success, 0)
        self.assertEqual(failure, 1)
        call.refresh_from_db()
        self.assertEqual(call.status, PhoneCall.Status.FAILED)
        self.assertIn("timeout", call.error_message)

    def test_all_calls_failed_marks_blast_failed(self):
        blast, _ = self._make_blast()
        with patch(
            "messaging.services.TwilioService.initiate_call",
            side_effect=TwilioRequestError("fail"),
        ):
            deliver_phone_blast(blast, settings_obj=self.settings_obj)
        blast.refresh_from_db()
        self.assertEqual(blast.status, PhoneBlast.Status.FAILED)

    def test_non_pending_call_is_skipped(self):
        blast, call = self._make_blast()
        call.status = PhoneCall.Status.COMPLETED
        call.save()
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA999"
        ) as mock_call:
            deliver_phone_blast(blast, settings_obj=self.settings_obj)
        mock_call.assert_not_called()

    def test_audio_url_falls_back_to_website_setting(self):
        self.settings_obj.website = "https://church.example.com"
        self.settings_obj.save()
        blast, _ = self._make_blast()
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA123"
        ) as mock_call:
            deliver_phone_blast(blast, settings_obj=self.settings_obj)
        called_url = mock_call.call_args[0][1]
        self.assertTrue(called_url.startswith("https://church.example.com"))

    def test_failed_call_does_not_create_communication_log(self):
        blast, _ = self._make_blast()
        with patch(
            "messaging.services.TwilioService.initiate_call",
            side_effect=TwilioRequestError("fail"),
        ):
            deliver_phone_blast(blast, settings_obj=self.settings_obj)
        self.assertEqual(self.person.communication_logs.count(), 0)


# ---------------------------------------------------------------------------
# get_site_base_url resolution
# ---------------------------------------------------------------------------

class SiteBaseUrlTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()

    @override_settings(SITE_BASE_URL="https://from-setting.example/", CSRF_TRUSTED_ORIGINS=[])
    def test_prefers_site_base_url_setting(self):
        self.assertEqual(get_site_base_url(self.settings_obj), "https://from-setting.example")

    @override_settings(SITE_BASE_URL="", CSRF_TRUSTED_ORIGINS=[])
    def test_falls_back_to_website(self):
        self.settings_obj.website = "https://church.example/"
        self.settings_obj.save()
        self.assertEqual(get_site_base_url(self.settings_obj), "https://church.example")

    @override_settings(SITE_BASE_URL="", CSRF_TRUSTED_ORIGINS=["https://csrf.example"])
    def test_falls_back_to_csrf_origin(self):
        self.settings_obj.website = ""
        self.settings_obj.save()
        self.assertEqual(get_site_base_url(self.settings_obj), "https://csrf.example")

    @override_settings(SITE_BASE_URL="", CSRF_TRUSTED_ORIGINS=[])
    def test_returns_none_when_nothing_configured(self):
        self.settings_obj.website = ""
        self.settings_obj.save()
        self.assertIsNone(get_site_base_url(self.settings_obj))


# ---------------------------------------------------------------------------
# Scheduled delivery via process_communications (the live-bug fix)
# ---------------------------------------------------------------------------

class ProcessCommunicationsCommandTests(TestCase):
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
        self.settings_obj.website = "https://church.example"
        self.settings_obj.save()
        self.user = get_user_model().objects.create_user(username="sched", password="pw")
        self.person = Person.objects.create(
            first_name="Sched", last_name="Target", phone="+15557778888", phone_opt_in=True
        )

    @override_settings(SITE_BASE_URL="https://church.example")
    def test_due_scheduled_phone_blast_is_delivered_with_callback(self):
        audio = SimpleUploadedFile("msg.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Scheduled Blast",
            audio_file=audio,
            status=PhoneBlast.Status.SCHEDULED,
            scheduled_for=dj_timezone.now() - timedelta(minutes=1),
        )
        PhoneCall.objects.create(
            blast=blast, person=self.person, phone_number=self.person.phone
        )
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA_SCHED"
        ) as mock_call:
            call_command("process_communications")

        # The headless path must pass a StatusCallback so calls can settle.
        self.assertEqual(mock_call.call_count, 1)
        self.assertEqual(
            mock_call.call_args.kwargs["status_callback_url"],
            "https://church.example/communications/phone-blast/webhook/call-status/",
        )
        call = blast.calls.first()
        self.assertEqual(call.call_sid, "CA_SCHED")
        blast.refresh_from_db()
        self.assertEqual(blast.status, PhoneBlast.Status.PROCESSING)

    def test_future_scheduled_blast_is_not_delivered_yet(self):
        audio = SimpleUploadedFile("later.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Future Blast",
            audio_file=audio,
            status=PhoneBlast.Status.SCHEDULED,
            scheduled_for=dj_timezone.now() + timedelta(hours=2),
        )
        PhoneCall.objects.create(
            blast=blast, person=self.person, phone_number=self.person.phone
        )
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA_X"
        ) as mock_call:
            call_command("process_communications")
        mock_call.assert_not_called()
        blast.refresh_from_db()
        self.assertEqual(blast.status, PhoneBlast.Status.SCHEDULED)


# ---------------------------------------------------------------------------
# PhoneBlastForm.clean_audio_file validation
# ---------------------------------------------------------------------------

class PhoneBlastAudioValidationTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()
        self.person = Person.objects.create(
            first_name="V", last_name="A", phone="+15551110000", phone_opt_in=True
        )
        self.group = Group.objects.create(name="Vols", category="volunteer")
        GroupMembership.objects.create(group=self.group, person=self.person)

    def _form(self, audio):
        return PhoneBlastForm(
            data={"title": "T", "group": self.group.pk, "scheduled_for": "", "notes": ""},
            files={"audio_file": audio},
            organization_settings=self.settings_obj,
        )

    def test_rejects_unsupported_extension(self):
        form = self._form(SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain"))
        self.assertFalse(form.is_valid())
        self.assertIn("audio_file", form.errors)

    def test_rejects_oversized_file(self):
        with patch.object(PhoneBlastForm, "MAX_AUDIO_BYTES", 3):
            form = self._form(SimpleUploadedFile("big.mp3", b"way too big"))
            self.assertFalse(form.is_valid())
            self.assertIn("audio_file", form.errors)

    def test_accepts_valid_audio(self):
        form = self._form(SimpleUploadedFile("ok.mp3", b"audio-bytes"))
        self.assertTrue(form.is_valid(), form.errors)


# ---------------------------------------------------------------------------
# cleanup_audio management command
# ---------------------------------------------------------------------------

class CleanupAudioCommandTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.user = get_user_model().objects.create_user(username="cleanup", password="pw")

    def test_purges_aged_blast_audio(self):
        audio = SimpleUploadedFile("old.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Old Blast",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
            completed_at=dj_timezone.now() - timedelta(days=60),
        )
        file_path = blast.audio_file.path
        self.assertTrue(os.path.exists(file_path))

        call_command("cleanup_audio", days=30)

        blast.refresh_from_db()
        self.assertFalse(blast.audio_file)
        self.assertFalse(os.path.exists(file_path))

    def test_keeps_recent_blast_audio(self):
        audio = SimpleUploadedFile("recent.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Recent Blast",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
            completed_at=dj_timezone.now() - timedelta(days=1),
        )
        call_command("cleanup_audio", days=30)
        blast.refresh_from_db()
        self.assertTrue(blast.audio_file)

    def test_removes_orphaned_files(self):
        orphan_dir = os.path.join(self.temp_media, "communications", "phone_blasts")
        os.makedirs(orphan_dir, exist_ok=True)
        orphan_path = os.path.join(orphan_dir, "orphan.mp3")
        with open(orphan_path, "wb") as fh:
            fh.write(b"abandoned")
        self.assertTrue(os.path.exists(orphan_path))

        call_command("cleanup_audio", days=0)

        self.assertFalse(os.path.exists(orphan_path))

    def test_dry_run_keeps_files(self):
        orphan_dir = os.path.join(self.temp_media, "communications", "phone_blasts")
        os.makedirs(orphan_dir, exist_ok=True)
        orphan_path = os.path.join(orphan_dir, "keep.mp3")
        with open(orphan_path, "wb") as fh:
            fh.write(b"data")
        call_command("cleanup_audio", days=0, dry_run=True)
        self.assertTrue(os.path.exists(orphan_path))


# ---------------------------------------------------------------------------
# Audio transcoding + delivery-visualization polish
# ---------------------------------------------------------------------------

class TranscodeTests(TestCase):
    def test_raises_when_ffmpeg_missing(self):
        from messaging import services

        with patch.object(services.shutil, "which", return_value=None):
            with self.assertRaises(AudioProcessingError):
                services.transcode_to_mp3(SimpleUploadedFile("a.webm", b"x"))


class DeliveryVisualizationTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.user = get_user_model().objects.create_user(username="viz", password="pw")
        self.user.profile.can_manage_communications = True
        self.user.profile.save()
        self.client.force_login(self.user)
        self.person = Person.objects.create(
            first_name="Failed", last_name="Caller", phone="+15554443333"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        self.blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Viz Blast",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
        )

    def test_detail_shows_error_message_for_failed_call(self):
        PhoneCall.objects.create(
            blast=self.blast, person=self.person, phone_number=self.person.phone,
            status=PhoneCall.Status.FAILED, error_message="Carrier rejected the call",
        )
        response = self.client.get(
            reverse("messaging:phone_blast_detail", args=[self.blast.pk])
        )
        self.assertContains(response, "Carrier rejected the call")

    def test_stats_partial_shows_progress_percentage(self):
        PhoneCall.objects.create(
            blast=self.blast, person=self.person, phone_number=self.person.phone,
            status=PhoneCall.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=self.blast, phone_number="+15550009999",
            status=PhoneCall.Status.PENDING,
        )
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        # 1 of 2 settled → 50%
        self.assertContains(response, "50%")

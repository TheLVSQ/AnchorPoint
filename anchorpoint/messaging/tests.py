import base64
import hashlib
import hmac
import os
import shutil
import tempfile
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_timezone

from core.models import OrganizationSettings
from groups.models import Group, GroupMembership
from people.models import Person

from . import outbound
from .adapters import DeliveryError, FakeAdapter, TwilioSms, TwilioVoice
from .forms import PhoneBlastForm, SmsBroadcastForm
from .models import Communication, Delivery
from .services import AudioProcessingError, get_site_base_url
from .twilio_client import TwilioClient, TwilioConfigurationError

SMS = Communication.Channel.SMS
VOICE = Communication.Channel.VOICE


class MessagingTestCase(TestCase):
    """Fresh fake adapter + throwaway media dir + a consenting person."""

    def setUp(self):
        FakeAdapter.reset()
        self.addCleanup(FakeAdapter.reset)
        self.temp_media = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_media, ignore_errors=True))
        media_override = override_settings(MEDIA_ROOT=self.temp_media)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.settings_obj = OrganizationSettings.load()
        self.user = get_user_model().objects.create_user(username="comm", password="pw")
        self.person = Person.objects.create(
            first_name="Recipient", last_name="One", phone="+15551112222", phone_opt_in=True
        )
        self.group = Group.objects.create(name="Leaders", category="volunteer")
        GroupMembership.objects.create(group=self.group, person=self.person)

    def blackout_all_day(self):
        self.settings_obj.sms_blackout_start = time(0, 0)
        self.settings_obj.sms_blackout_end = time(23, 59, 59)
        self.settings_obj.save()

    def voice_broadcast(self, **kwargs):
        kwargs.setdefault("group", self.group)
        return outbound.broadcast(
            VOICE, created_by=self.user, title="Weekly Update",
            audio_file=ContentFile(b"audio", name="blast.mp3"), **kwargs
        )

    def make_blast(self, status=Communication.Status.COMPLETED, calls=()):
        """A voice Communication with Deliveries in the given statuses (for view tests)."""
        blast = Communication.objects.create(
            channel=VOICE, created_by=self.user, title="Sunday Announcement",
            audio_file=ContentFile(b"audio", name="blast.mp3"), status=status,
            target_type=Communication.TargetType.GROUP, group=self.group,
        )
        for i, (call_status, kwargs) in enumerate(calls):
            Delivery.objects.create(
                communication=blast, person=kwargs.pop("person", self.person),
                address=kwargs.pop("address", f"+1555000000{i}"),
                provider_id=kwargs.pop("provider_id", f"CA{i}"), status=call_status, **kwargs
            )
        return blast


# ---------------------------------------------------------------------------
# Compose-time checks (check_broadcast via the forms)
# ---------------------------------------------------------------------------

class SmsBroadcastFormTests(MessagingTestCase):
    def _form(self, **data):
        base = {"target_type": "person", "person": self.person.pk, "group": "",
                "body": "Hi there", "scheduled_for": ""}
        base.update(data)
        return SmsBroadcastForm(data=base)

    def test_valid_person_message(self):
        self.assertTrue(self._form().is_valid())

    def test_blocked_when_inside_blackout_window(self):
        self.blackout_all_day()
        form = self._form()
        self.assertFalse(form.is_valid())
        self.assertIn("blackout", form.non_field_errors()[0])

    def test_scheduled_time_inside_blackout_is_a_field_error(self):
        self.settings_obj.sms_blackout_start = time(1, 0)
        self.settings_obj.sms_blackout_end = time(2, 0)
        self.settings_obj.save()
        when = dj_timezone.localtime() + timedelta(days=1)
        when = when.replace(hour=1, minute=30)
        form = self._form(scheduled_for=when.strftime("%Y-%m-%dT%H:%M"))
        self.assertFalse(form.is_valid())
        self.assertIn("scheduled_for", form.errors)

    def test_past_schedule_rejected(self):
        past = dj_timezone.localtime() - timedelta(hours=1)
        form = self._form(scheduled_for=past.strftime("%Y-%m-%dT%H:%M"))
        self.assertFalse(form.is_valid())
        self.assertIn("scheduled_for", form.errors)

    def test_opted_out_person_rejected(self):
        self.person.phone_opt_in = False
        self.person.save()
        form = self._form()
        self.assertFalse(form.is_valid())
        self.assertIn("opted out", form.errors["person"][0])

    def test_person_without_phone_rejected(self):
        self.person.phone = ""
        self.person.save()
        form = self._form()
        self.assertFalse(form.is_valid())
        self.assertIn("phone number", form.errors["person"][0])

    def test_group_target(self):
        future = datetime.now(dt_timezone.utc) + timedelta(days=1)
        form = self._form(target_type="group", person="", group=self.group.pk,
                          scheduled_for=future.isoformat())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.target(), (None, self.group))

    def test_group_with_nobody_reachable_rejected(self):
        empty = Group.objects.create(name="Empty", category="other")
        form = self._form(target_type="group", person="", group=empty.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("Nobody in this group", form.non_field_errors()[0])

    def test_missing_person_selection(self):
        form = self._form(person="")
        self.assertFalse(form.is_valid())
        self.assertIn("person", form.errors)


class PhoneBlastFormTests(MessagingTestCase):
    def _form(self, audio=None, **data):
        base = {"target_type": "group", "title": "Voicemail", "group": self.group.pk,
                "person": "", "scheduled_for": "", "notes": ""}
        base.update(data)
        audio = audio or SimpleUploadedFile("note.mp3", b"data")
        return PhoneBlastForm(data=base, files={"audio_file": audio})

    def test_prevents_blank_group(self):
        form = self._form(group="")
        self.assertFalse(form.is_valid())
        self.assertIn("group", form.errors)

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

    def test_defaults_to_group(self):
        self.assertEqual(PhoneBlastForm()["target_type"].value(), "group")

    def test_person_target(self):
        form = self._form(target_type="person", person=self.person.pk, group="")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.target(), (self.person, None))

    def test_opted_out_person_rejected(self):
        self.person.phone_opt_in = False
        self.person.save()
        form = self._form(target_type="person", person=self.person.pk, group="")
        self.assertFalse(form.is_valid())
        self.assertIn("opted out", form.errors["person"][0])

    def test_missing_person_selection(self):
        form = self._form(target_type="person", person="")
        self.assertFalse(form.is_valid())
        self.assertIn("person", form.errors)


class CheckBroadcastTests(MessagingTestCase):
    def test_not_ready_channel_is_a_problem(self):
        FakeAdapter.is_ready = False
        problems = outbound.check_broadcast(SMS, person=self.person)
        self.assertTrue(any("Twilio" in p.message for p in problems))

    def test_no_target_is_a_problem(self):
        self.assertTrue(outbound.check_broadcast(SMS))

    def test_ok_returns_no_problems(self):
        self.assertEqual(outbound.check_broadcast(SMS, group=self.group), [])

    def test_broadcast_raises_on_problems(self):
        self.blackout_all_day()
        with self.assertRaises(outbound.BroadcastRejected):
            outbound.broadcast(SMS, created_by=self.user, person=self.person, body="x")
        self.assertFalse(Communication.objects.exists())


# ---------------------------------------------------------------------------
# broadcast() + dispatch_due(): the scheduler path every broadcast takes
# ---------------------------------------------------------------------------

class BroadcastTests(MessagingTestCase):
    def test_broadcast_queues_without_sending(self):
        comm = outbound.broadcast(SMS, created_by=self.user, group=self.group, body="Hello")
        self.assertEqual(comm.status, Communication.Status.SCHEDULED)
        self.assertEqual(comm.kind, Communication.Kind.BROADCAST)
        delivery = comm.deliveries.get()
        self.assertEqual(delivery.status, Delivery.Status.PENDING)
        self.assertEqual(delivery.address, self.person.phone)
        self.assertEqual(FakeAdapter.sent, [])

    def test_group_broadcast_only_includes_consenting_people_with_phones(self):
        no_consent = Person.objects.create(first_name="No", last_name="Consent",
                                           phone="+15550000001", phone_opt_in=False)
        no_phone = Person.objects.create(first_name="No", last_name="Phone", phone_opt_in=True)
        for p in (no_consent, no_phone):
            GroupMembership.objects.create(group=self.group, person=p)
        comm = outbound.broadcast(SMS, created_by=self.user, group=self.group, body="Hi")
        self.assertEqual([d.person for d in comm.deliveries.all()], [self.person])

    def test_send_now_goes_out_on_next_dispatch(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Now")
        report = outbound.dispatch_due()
        self.assertEqual(report.sent, [comm])
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.COMPLETED)
        delivery = comm.deliveries.get()
        self.assertEqual(delivery.status, Delivery.Status.SENT)
        self.assertTrue(delivery.provider_id.startswith("FAKE"))
        self.assertEqual(FakeAdapter.sent, [(SMS, self.person.phone, comm.pk)])

    def test_future_broadcast_waits(self):
        later = dj_timezone.now() + timedelta(hours=2)
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person,
                                  body="Later", scheduled_for=later)
        outbound.dispatch_due()
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.SCHEDULED)
        self.assertEqual(FakeAdapter.sent, [])
        outbound.dispatch_due(now=later + timedelta(minutes=1))
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.COMPLETED)

    def test_dispatch_is_idempotent(self):
        outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Once")
        outbound.dispatch_due()
        outbound.dispatch_due()
        self.assertEqual(len(FakeAdapter.sent), 1)

    def test_person_who_opts_out_after_scheduling_is_skipped(self):
        other = Person.objects.create(first_name="Still", last_name="In",
                                      phone="+15553334444", phone_opt_in=True)
        GroupMembership.objects.create(group=self.group, person=other)
        comm = outbound.broadcast(SMS, created_by=self.user, group=self.group, body="Hi")
        self.person.phone_opt_in = False
        self.person.save()

        outbound.dispatch_due()

        skipped = comm.deliveries.get(person=self.person)
        self.assertEqual(skipped.status, Delivery.Status.SKIPPED)
        self.assertEqual(skipped.skip_reason, Delivery.SkipReason.OPTED_OUT)
        self.assertEqual(comm.deliveries.get(person=other).status, Delivery.Status.SENT)
        self.assertEqual([s[1] for s in FakeAdapter.sent], [other.phone])

    def test_everyone_skipped_completes_rather_than_fails(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Hi")
        self.person.phone_opt_in = False
        self.person.save()
        outbound.dispatch_due()
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.COMPLETED)

    def test_removed_phone_number_is_skipped_as_no_address(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Hi")
        self.person.phone = ""
        self.person.save()
        outbound.dispatch_due()
        self.assertEqual(comm.deliveries.get().skip_reason, Delivery.SkipReason.NO_ADDRESS)

    def test_send_uses_the_current_phone_number(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Hi")
        self.person.phone = "+15559998888"
        self.person.save()
        outbound.dispatch_due()
        self.assertEqual(comm.deliveries.get().address, "+15559998888")

    def test_due_broadcast_waits_out_the_blackout_window(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Hi")
        self.blackout_all_day()
        report = outbound.dispatch_due()
        self.assertEqual(report.deferred, 1)
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.SCHEDULED)
        self.assertEqual(FakeAdapter.sent, [])

        self.settings_obj.sms_blackout_start = None
        self.settings_obj.save()
        outbound.dispatch_due()
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.COMPLETED)

    def test_send_failure_is_recorded_and_all_failed_marks_failed(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Hi")
        FakeAdapter.fail_with = "connection refused"
        report = outbound.dispatch_due()
        self.assertEqual(report.failed, [comm])
        delivery = comm.deliveries.get()
        self.assertEqual(delivery.status, Delivery.Status.FAILED)
        self.assertIn("connection refused", delivery.error_message)
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.FAILED)

    def test_channel_unconfigured_at_send_time_fails_the_broadcast(self):
        comm = outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Hi")
        FakeAdapter.is_ready = False
        outbound.dispatch_due()
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.FAILED)
        self.assertIn("Twilio", comm.deliveries.get().error_message)
        self.assertEqual(FakeAdapter.sent, [])

    def test_voice_broadcast_rings_until_status_callback(self):
        comm = self.voice_broadcast()
        outbound.dispatch_due()
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.SENDING)
        self.assertEqual(comm.deliveries.get().status, Delivery.Status.SENT)


class StaleCallTests(MessagingTestCase):
    """A call whose status callback never arrives must not leave a blast 'Sending' forever."""

    def setUp(self):
        super().setUp()
        self.comm = self.voice_broadcast()
        outbound.dispatch_due()
        self.delivery = self.comm.deliveries.get()

    def test_recent_call_keeps_ringing(self):
        outbound.dispatch_due(now=dj_timezone.now() + timedelta(minutes=30))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.SENT)

    def test_call_with_no_callback_after_two_hours_is_settled(self):
        report = outbound.dispatch_due(now=dj_timezone.now() + timedelta(hours=3))
        self.assertEqual(report.stale_calls, 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.FAILED)
        self.assertIn("No status received", self.delivery.error_message)
        self.comm.refresh_from_db()
        self.assertEqual(self.comm.status, Communication.Status.FAILED)

    def test_settles_to_completed_when_other_calls_answered(self):
        Delivery.objects.create(communication=self.comm, person=self.person, address="+15550001111",
                                provider_id="CA_OK", status=Delivery.Status.ANSWERED)
        outbound.dispatch_due(now=dj_timezone.now() + timedelta(hours=3))
        self.comm.refresh_from_db()
        self.assertEqual(self.comm.status, Communication.Status.COMPLETED)

    def test_runs_even_inside_blackout(self):
        self.blackout_all_day()
        outbound.dispatch_due(now=dj_timezone.now() + timedelta(hours=3))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.FAILED)


class RecordCallStatusTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.comm = self.voice_broadcast()
        outbound.dispatch_due()
        self.delivery = self.comm.deliveries.get()

    def test_settles_delivery_and_completes_communication(self):
        outbound.record_call_status(self.delivery.provider_id, "completed")
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.ANSWERED)
        self.comm.refresh_from_db()
        self.assertEqual(self.comm.status, Communication.Status.COMPLETED)
        self.assertIsNotNone(self.comm.completed_at)

    def test_mapping(self):
        for twilio_status, expected in [("no-answer", Delivery.Status.NO_ANSWER),
                                        ("busy", Delivery.Status.FAILED),
                                        ("failed", Delivery.Status.FAILED)]:
            outbound.record_call_status(self.delivery.provider_id, twilio_status)
            self.delivery.refresh_from_db()
            self.assertEqual(self.delivery.status, expected)

    def test_stays_sending_while_other_calls_ring(self):
        Delivery.objects.create(communication=self.comm, person=self.person,
                                address="+15550001111", provider_id="CA2",
                                status=Delivery.Status.SENT)
        outbound.record_call_status(self.delivery.provider_id, "completed")
        self.comm.refresh_from_db()
        self.assertEqual(self.comm.status, Communication.Status.SENDING)

    def test_unknown_id_returns_none(self):
        self.assertIsNone(outbound.record_call_status("CA_UNKNOWN", "completed"))
        self.assertIsNone(outbound.record_call_status("", "completed"))


# ---------------------------------------------------------------------------
# send_transactional()
# ---------------------------------------------------------------------------

class SendTransactionalTests(MessagingTestCase):
    def test_sends_immediately_and_records(self):
        comm = outbound.send_transactional(SMS, people=[self.person], body="Code ABCD",
                                           title="Check-in pickup code",
                                           metadata={"security_code": "ABCD"})
        self.assertEqual(comm.kind, Communication.Kind.TRANSACTIONAL)
        self.assertEqual(comm.status, Communication.Status.COMPLETED)
        self.assertEqual(comm.metadata["security_code"], "ABCD")
        self.assertEqual(comm.deliveries.get().status, Delivery.Status.SENT)
        self.assertEqual(len(FakeAdapter.sent), 1)

    def test_ignores_blackout(self):
        self.blackout_all_day()
        self.assertIsNotNone(outbound.send_transactional(SMS, people=[self.person], body="x"))
        self.assertEqual(len(FakeAdapter.sent), 1)

    def test_respects_opt_in(self):
        self.person.phone_opt_in = False
        self.person.save()
        self.assertIsNone(outbound.send_transactional(SMS, people=[self.person], body="x"))
        self.assertFalse(Communication.objects.exists())

    def test_unconfigured_channel_records_nothing(self):
        FakeAdapter.is_ready = False
        self.assertIsNone(outbound.send_transactional(SMS, people=[self.person], body="x"))
        self.assertFalse(Communication.objects.exists())

    def test_send_failure_recorded_not_raised(self):
        FakeAdapter.fail_with = "boom"
        comm = outbound.send_transactional(SMS, people=[self.person], body="x")
        self.assertEqual(comm.status, Communication.Status.FAILED)
        self.assertEqual(comm.deliveries.get().error_message, "boom")

    def test_duplicate_people_get_one_delivery(self):
        comm = outbound.send_transactional(SMS, people=[self.person, self.person], body="x")
        self.assertEqual(comm.deliveries.count(), 1)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class StaffViewTestCase(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.user.profile.can_manage_communications = True
        self.user.profile.save()
        self.client.force_login(self.user)


class ComposeViewTests(StaffViewTestCase):
    def test_sms_compose_queues_a_broadcast(self):
        resp = self.client.post(reverse("messaging:sms_compose"), {
            "target_type": "person", "person": self.person.pk, "group": "",
            "body": "Hello from staff", "scheduled_for": "",
        })
        self.assertRedirects(resp, reverse("messaging:home"))
        comm = Communication.objects.get()
        self.assertEqual((comm.channel, comm.status, comm.body),
                         (SMS, Communication.Status.SCHEDULED, "Hello from staff"))
        self.assertEqual(comm.created_by, self.user)
        self.assertEqual(FakeAdapter.sent, [])  # the scheduler sends it

    def test_sms_compose_has_no_full_person_dropdown(self):
        Person.objects.create(first_name="Unrelated", last_name="Zimmerman")
        resp = self.client.get(reverse("messaging:sms_compose"))
        self.assertNotContains(resp, "Zimmerman")
        self.assertContains(resp, reverse("person_pick"))

    def test_sms_compose_keeps_picked_person_on_error(self):
        resp = self.client.post(reverse("messaging:sms_compose"), {
            "target_type": "person", "person": self.person.pk, "body": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'value="{self.person.pk}" checked')
        self.assertFalse(Communication.objects.exists())

    def test_sms_compose_redirects_when_channel_not_ready(self):
        FakeAdapter.is_ready = False
        resp = self.client.post(reverse("messaging:sms_compose"), {
            "target_type": "person", "person": self.person.pk, "body": "x",
        })
        self.assertRedirects(resp, reverse("organization_settings"), fetch_redirect_response=False)
        self.assertFalse(Communication.objects.exists())

    def test_phone_blast_create_transcodes_and_queues(self):
        with patch("messaging.views.transcode_to_mp3",
                   return_value=ContentFile(b"mp3", name="x.mp3")) as transcode:
            resp = self.client.post(reverse("messaging:phone_blast_create"), {
                "target_type": "group", "title": "Snow day", "group": self.group.pk,
                "scheduled_for": "", "notes": "",
                "audio_file": SimpleUploadedFile("rec.webm", b"webm"),
            })
        self.assertRedirects(resp, reverse("messaging:home"))
        transcode.assert_called_once()
        comm = Communication.objects.get()
        self.assertEqual((comm.channel, comm.title), (VOICE, "Snow day"))
        self.assertTrue(comm.audio_file.name.endswith(".mp3"))
        self.assertEqual(comm.deliveries.count(), 1)

    def test_phone_blast_to_one_person(self):
        other = Person.objects.create(first_name="Other", last_name="Member",
                                      phone="+15553334444", phone_opt_in=True)
        GroupMembership.objects.create(group=self.group, person=other)
        with patch("messaging.views.transcode_to_mp3",
                   return_value=ContentFile(b"mp3", name="x.mp3")):
            resp = self.client.post(reverse("messaging:phone_blast_create"), {
                "target_type": "person", "person": self.person.pk, "group": self.group.pk,
                "title": "Quick call", "audio_file": SimpleUploadedFile("rec.webm", b"webm"),
            })
        self.assertRedirects(resp, reverse("messaging:home"))
        comm = Communication.objects.get()
        self.assertEqual((comm.target_type, comm.person, comm.group),
                         (Communication.TargetType.PERSON, self.person, None))
        self.assertEqual([d.person for d in comm.deliveries.all()], [self.person])
        detail = self.client.get(reverse("messaging:phone_blast_detail", args=[comm.pk]))
        self.assertContains(detail, "Recipient One ·")

    def test_phone_blast_form_keeps_picked_person_on_error(self):
        resp = self.client.post(reverse("messaging:phone_blast_create"), {
            "target_type": "person", "person": self.person.pk, "title": "",
            "audio_file": SimpleUploadedFile("rec.webm", b"webm"),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'value="{self.person.pk}" checked')
        self.assertFalse(Communication.objects.exists())

    def test_phone_blast_audio_error_shows_on_form(self):
        with patch("messaging.views.transcode_to_mp3",
                   side_effect=AudioProcessingError("could not process")):
            resp = self.client.post(reverse("messaging:phone_blast_create"), {
                "target_type": "group", "title": "Snow day", "group": self.group.pk,
                "audio_file": SimpleUploadedFile("rec.webm", b"webm"),
            })
        self.assertContains(resp, "could not process")
        self.assertFalse(Communication.objects.exists())


class PhoneBlastDetailViewTests(StaffViewTestCase):
    def setUp(self):
        super().setUp()
        self.blast = self.make_blast(calls=[
            (Delivery.Status.ANSWERED, {}), (Delivery.Status.NO_ANSWER, {}),
        ])

    def test_detail_page_returns_200(self):
        resp = self.client.get(reverse("messaging:phone_blast_detail", args=[self.blast.pk]))
        self.assertContains(resp, "Sunday Announcement")
        self.assertContains(resp, "Answered")

    def test_sms_pk_is_not_a_phone_blast(self):
        sms = Communication.objects.create(channel=SMS, created_by=self.user, body="x")
        resp = self.client.get(reverse("messaging:phone_blast_detail", args=[sms.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_stats_partial_includes_polling_when_sending(self):
        self.blast.status = Communication.Status.SENDING
        self.blast.save()
        resp = self.client.get(reverse("messaging:phone_blast_stats", args=[self.blast.pk]))
        self.assertContains(resp, "every 5s")

    def test_stats_partial_omits_polling_when_complete(self):
        resp = self.client.get(reverse("messaging:phone_blast_stats", args=[self.blast.pk]))
        self.assertNotContains(resp, "every 5s")

    def test_stats_partial_shows_progress_percentage(self):
        blast = self.make_blast(calls=[(Delivery.Status.ANSWERED, {}), (Delivery.Status.SENT, {})])
        resp = self.client.get(reverse("messaging:phone_blast_stats", args=[blast.pk]))
        self.assertContains(resp, "50%")  # 1 of 2 settled

    def test_detail_shows_error_and_skip_reason(self):
        blast = self.make_blast(calls=[
            (Delivery.Status.FAILED, {"error_message": "Carrier rejected the call"}),
            (Delivery.Status.SKIPPED, {"skip_reason": Delivery.SkipReason.OPTED_OUT}),
        ])
        resp = self.client.get(reverse("messaging:phone_blast_detail", args=[blast.pk]))
        self.assertContains(resp, "Carrier rejected the call")
        self.assertContains(resp, "Opted out")


class MessagingHomeViewTests(StaffViewTestCase):
    def test_home_shows_blast_stats_summary(self):
        self.make_blast(calls=[(Delivery.Status.ANSWERED, {}), (Delivery.Status.NO_ANSWER, {})])
        resp = self.client.get(reverse("messaging:home"))
        self.assertContains(resp, "1 answered")
        self.assertContains(resp, "1 no answer")

    def test_home_shows_sending_label(self):
        self.make_blast(status=Communication.Status.SENDING, calls=[(Delivery.Status.SENT, {})])
        self.assertContains(self.client.get(reverse("messaging:home")), "Sending")

    def test_queued_text_shows_queued(self):
        outbound.broadcast(SMS, created_by=self.user, person=self.person, body="Soon")
        self.assertContains(self.client.get(reverse("messaging:home")), "Queued")

    def test_transactional_texts_are_not_listed(self):
        outbound.send_transactional(SMS, people=[self.person], body="Pickup code ZZZZ")
        self.assertNotContains(self.client.get(reverse("messaging:home")), "ZZZZ")


class PhoneCallWebhookTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.settings_obj.twilio_auth_token = "test_auth_token"
        self.settings_obj.save()
        self.blast = self.make_blast(status=Communication.Status.SENDING, calls=[
            (Delivery.Status.SENT, {"provider_id": "CA_TEST_001"}),
        ])
        self.call = self.blast.deliveries.get()
        self.url = reverse("messaging:phone_call_status_webhook")

    def _post(self, params, sign=True, signed_url=None):
        full = signed_url or ("http://testserver" + self.url)
        payload = full + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        mac = hmac.new(b"test_auth_token", payload.encode(), hashlib.sha1)
        sig = base64.b64encode(mac.digest()).decode() if sign else "invalidsignature"
        return self.client.post(self.url, data=params, HTTP_X_TWILIO_SIGNATURE=sig)

    def test_completed_call_settles_blast(self):
        resp = self._post({"CallSid": "CA_TEST_001", "CallStatus": "completed"})
        self.assertEqual(resp.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, Delivery.Status.ANSWERED)
        self.blast.refresh_from_db()
        self.assertEqual(self.blast.status, Communication.Status.COMPLETED)

    def test_invalid_signature_returns_403(self):
        resp = self._post({"CallSid": "CA_TEST_001", "CallStatus": "completed"}, sign=False)
        self.assertEqual(resp.status_code, 403)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, Delivery.Status.SENT)

    @override_settings(SITE_BASE_URL="https://anchorpoint.example")
    def test_accepts_signature_for_the_registered_public_url(self):
        # Behind Cloudflare Tunnel the request arrives as plain http on an internal
        # host, but Twilio signs the public https callback URL we registered.
        public = "https://anchorpoint.example/communications/phone-blast/webhook/call-status/"
        resp = self._post({"CallSid": "CA_TEST_001", "CallStatus": "completed"},
                          signed_url=public)
        self.assertEqual(resp.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, Delivery.Status.ANSWERED)

    @override_settings(SITE_BASE_URL="https://anchorpoint.example")
    def test_rejects_signature_for_some_other_url(self):
        resp = self._post({"CallSid": "CA_TEST_001", "CallStatus": "completed"},
                          signed_url="https://evil.example/communications/phone-blast/webhook/call-status/")
        self.assertEqual(resp.status_code, 403)

    def test_unknown_call_sid_returns_404(self):
        resp = self._post({"CallSid": "CA_UNKNOWN", "CallStatus": "completed"})
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Blackout window
# ---------------------------------------------------------------------------

@override_settings(TIME_ZONE="UTC")
class BlackoutWindowTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()

    def _check(self, start, end, hour, minute=0):
        self.settings_obj.sms_blackout_start = start
        self.settings_obj.sms_blackout_end = end
        moment = dj_timezone.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        return outbound.is_within_blackout_window(self.settings_obj, moment)

    def test_cases(self):
        cases = [
            (None, None, 10, 0, False),                      # not configured
            (time(22, 0), time(22, 0), 22, 0, False),        # start == end
            (time(22, 0), time(23, 0), 22, 30, True),        # inside
            (time(22, 0), time(23, 0), 10, 0, False),        # outside
            (time(22, 0), time(23, 0), 22, 0, True),         # start inclusive
            (time(22, 0), time(23, 0), 23, 0, False),        # end exclusive
            (time(22, 0), time(8, 0), 3, 0, True),           # overnight, after midnight
            (time(22, 0), time(8, 0), 23, 0, True),          # overnight, before midnight
            (time(22, 0), time(8, 0), 12, 0, False),         # overnight, midday
        ]
        for start, end, hour, minute, expected in cases:
            with self.subTest(start=start, end=end, at=(hour, minute)):
                self.assertEqual(self._check(start, end, hour, minute), expected)


# ---------------------------------------------------------------------------
# Twilio adapters + client (the real provider side of the seam)
# ---------------------------------------------------------------------------

class TwilioAdapterTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.settings_obj.twilio_account_sid = "AC123"
        self.settings_obj.twilio_auth_token = "token"
        self.settings_obj.twilio_phone_number = "+15551234567"
        self.settings_obj.save()

    def _delivery(self, channel, **comm_kwargs):
        comm = Communication.objects.create(channel=channel, created_by=self.user, **comm_kwargs)
        return Delivery.objects.create(communication=comm, person=self.person,
                                       address=self.person.phone)

    def test_ready_requires_all_three_credentials(self):
        self.assertTrue(TwilioSms(self.settings_obj).ready())
        self.settings_obj.twilio_phone_number = ""
        self.assertFalse(TwilioSms(self.settings_obj).ready())
        self.assertFalse(TwilioVoice(self.settings_obj).ready())

    def test_client_raises_when_unconfigured(self):
        self.settings_obj.twilio_account_sid = ""
        with self.assertRaises(TwilioConfigurationError):
            TwilioClient(self.settings_obj)

    def test_sms_adapter_posts_body(self):
        with patch.object(TwilioClient, "_post", return_value={"sid": "SM1"}) as post:
            sid = TwilioSms(self.settings_obj).send(self._delivery(SMS, body="Hello"))
        self.assertEqual(sid, "SM1")
        data = post.call_args.kwargs["data"]
        self.assertEqual((data["To"], data["From"], data["Body"]),
                         (self.person.phone, "+15551234567", "Hello"))

    @override_settings(SITE_BASE_URL="https://church.example")
    def test_voice_adapter_uses_absolute_audio_and_status_callback(self):
        delivery = self._delivery(VOICE, title="T",
                                  audio_file=ContentFile(b"a", name="blast.mp3"))
        with patch.object(TwilioClient, "_post", return_value={"sid": "CA1"}) as post:
            TwilioVoice(self.settings_obj).send(delivery)
        data = post.call_args.kwargs["data"]
        audio_url = f"https://church.example{delivery.communication.audio_file.url}"
        self.assertIn(f"<Play>{audio_url}</Play>", data["Twiml"])
        self.assertEqual(data["StatusCallback"],
                         "https://church.example/communications/phone-blast/webhook/call-status/")

    def test_voice_adapter_without_audio_raises_delivery_error(self):
        with self.assertRaises(DeliveryError):
            TwilioVoice(self.settings_obj).send(self._delivery(VOICE, title="No audio"))

    def test_provider_error_becomes_delivery_error(self):
        from .twilio_client import TwilioRequestError

        with patch.object(TwilioClient, "_post", side_effect=TwilioRequestError("timeout")):
            with self.assertRaisesMessage(DeliveryError, "timeout"):
                TwilioSms(self.settings_obj).send(self._delivery(SMS, body="x"))


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
# Management commands
# ---------------------------------------------------------------------------

class ProcessCommunicationsCommandTests(MessagingTestCase):
    def test_sends_due_broadcasts(self):
        comm = self.voice_broadcast()
        call_command("process_communications")
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.SENDING)
        self.assertEqual(len(FakeAdapter.sent), 1)


class CleanupAudioCommandTests(MessagingTestCase):
    def test_purges_aged_blast_audio(self):
        blast = self.make_blast()
        blast.completed_at = dj_timezone.now() - timedelta(days=60)
        blast.save()
        path = blast.audio_file.path
        self.assertTrue(os.path.exists(path))
        call_command("cleanup_audio", days=30)
        blast.refresh_from_db()
        self.assertFalse(blast.audio_file)
        self.assertFalse(os.path.exists(path))

    def test_keeps_recent_blast_audio(self):
        blast = self.make_blast()
        blast.completed_at = dj_timezone.now() - timedelta(days=1)
        blast.save()
        call_command("cleanup_audio", days=30)
        blast.refresh_from_db()
        self.assertTrue(blast.audio_file)

    def _orphan(self, name):
        orphan_dir = os.path.join(self.temp_media, "communications", "phone_blasts")
        os.makedirs(orphan_dir, exist_ok=True)
        path = os.path.join(orphan_dir, name)
        with open(path, "wb") as fh:
            fh.write(b"abandoned")
        return path

    def test_removes_orphaned_files(self):
        path = self._orphan("orphan.mp3")
        call_command("cleanup_audio", days=0)
        self.assertFalse(os.path.exists(path))

    def test_dry_run_keeps_files(self):
        path = self._orphan("keep.mp3")
        call_command("cleanup_audio", days=0, dry_run=True)
        self.assertTrue(os.path.exists(path))


class TranscodeTests(TestCase):
    def test_raises_when_ffmpeg_missing(self):
        from messaging import services

        with patch.object(services.shutil, "which", return_value=None):
            with self.assertRaises(AudioProcessingError):
                services.transcode_to_mp3(SimpleUploadedFile("a.webm", b"x"))


class MergeKeepsHistoryTests(MessagingTestCase):
    def test_merging_people_moves_deliveries_to_the_survivor(self):
        from people.services.merge import merge_persons

        dupe = Person.objects.create(first_name="Recipient", last_name="One",
                                     phone="+15551112222", phone_opt_in=True)
        outbound.send_transactional(SMS, people=[dupe], body="Pickup code ABCD")
        merge_persons(self.person, dupe)
        self.assertEqual(Delivery.objects.get().person, self.person)

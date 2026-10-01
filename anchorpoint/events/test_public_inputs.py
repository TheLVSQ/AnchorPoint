"""Public registration abuse guards + formula-safe CSV exports."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.csv_safe import safe_cell
from core.models import UserProfile
from events.models import Event, EventOccurrence, EventRegistration
from people.models import Person


def _payload(first="Casey"):
    return {
        "contact-first_name": "Taylor",
        "contact-last_name": "Reed",
        "contact-email": "taylor@example.com",
        "contact-phone": "555-555-0000",
        "contact-liability_release_signature": "Taylor Reed",
        "contact-accept_liability": "on",
        "contact-accept_media": "on",
        "contact-media_release_signature": "Taylor Reed",
        "attendee-TOTAL_FORMS": "1",
        "attendee-INITIAL_FORMS": "0",
        "attendee-MIN_NUM_FORMS": "1",
        "attendee-MAX_NUM_FORMS": "1000",
        "attendee-0-first_name": first,
        "attendee-0-last_name": "Reed",
        "attendee-0-email": "casey@example.com",
        "attendee-0-phone": "555-111-2222",
    }


@mock.patch("core.email_service.send_staff_registration_notification")
@mock.patch("core.email_service.send_registration_confirmation")
class PublicRegistrationGuardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="ev", password="pw")
        self.event = Event.objects.create(
            title="Picnic", summary="s", description="d", created_by=self.user,
        )
        EventOccurrence.objects.create(
            event=self.event,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=2),
        )
        self.url = reverse("event_register", args=[self.event.registration_token])

    def test_honeypot_discards_submission_silently(self, confirm, notify):
        data = _payload()
        data["website"] = "http://spam.example"
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(EventRegistration.objects.count(), 0)
        confirm.assert_not_called()
        notify.assert_not_called()

    def test_spoofed_forwarded_for_does_not_bypass_rate_limit(self, confirm, notify):
        for i in range(12):
            self.client.post(self.url, _payload(first=f"Kid{i}"),
                             HTTP_CF_CONNECTING_IP="198.51.100.20",
                             HTTP_X_FORWARDED_FOR=f"10.1.1.{i}")
        self.assertEqual(EventRegistration.objects.count(), 8)

    def test_garbage_forwarded_for_is_not_a_500(self, confirm, notify):
        resp = self.client.post(self.url, _payload(), HTTP_X_FORWARDED_FOR="not-an-ip")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(EventRegistration.objects.count(), 1)

    def test_release_ip_is_real_client_ip(self, confirm, notify):
        self.client.post(self.url, _payload(), HTTP_CF_CONNECTING_IP="203.0.113.44",
                         HTTP_X_FORWARDED_FOR="1.1.1.1")
        self.assertEqual(EventRegistration.objects.get().liability_release_ip, "203.0.113.44")


class CsvFormulaInjectionTests(TestCase):
    def test_safe_cell(self):
        for raw in ("=HYPERLINK(\"x\")", "+1", "-2", "@SUM(A1)", "\tx", "\rx"):
            with self.subTest(raw=raw):
                self.assertEqual(safe_cell(raw), "'" + raw)
        self.assertEqual(safe_cell("Casey"), "Casey")
        self.assertEqual(safe_cell(5), 5)

    def test_report_export_neutralizes_formula_names(self):
        staff = get_user_model().objects.create_user(username="st", password="pw")
        staff.profile.role = UserProfile.Role.STAFF
        staff.profile.save()
        self.client.force_login(staff)
        Person.objects.create(first_name='=HYPERLINK("http://x.test","Click")',
                              last_name="Evil")
        resp = self.client.get(reverse("reporting:export", args=["missing-data"]))
        body = resp.content.decode()
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn(",=HYPERLINK", body)


class PublicEventListTests(TestCase):
    def test_recurring_event_shows_next_upcoming_date_not_a_past_one(self):
        e = Event.objects.create(title="Small Group", summary="s", description="d", is_published=True)
        past = timezone.now() - timedelta(days=30)
        future = timezone.now() + timedelta(days=5)
        EventOccurrence.objects.create(event=e, starts_at=past, ends_at=past + timedelta(hours=1))
        EventOccurrence.objects.create(event=e, starts_at=future, ends_at=future + timedelta(hours=1))
        resp = self.client.get(reverse("events:public_list"))
        self.assertEqual(resp.context["events"][0].next_start, future)
        self.assertContains(resp, timezone.localtime(future).strftime("%A, %B %-d"))


@mock.patch("core.email_service.send_staff_registration_notification")
@mock.patch("core.email_service.send_registration_confirmation")
class RequireAttendeeDetailsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.event = Event.objects.create(title="BKiDS Night Out", summary="s", description="d",
                                          require_attendee_details=True)
        EventOccurrence.objects.create(event=self.event, starts_at=timezone.now() + timedelta(days=2),
                                       ends_at=timezone.now() + timedelta(days=2, hours=2))
        self.url = reverse("event_register", args=[self.event.registration_token])

    def test_child_without_birthdate_or_grade_is_rejected(self, *_):
        resp = self.client.post(self.url, _payload())
        self.assertEqual(EventRegistration.objects.count(), 0)
        self.assertContains(resp, "This field is required", count=2)

    def test_child_with_birthdate_and_grade_is_accepted_and_listed(self, *_):
        data = _payload()
        data.update({"attendee-0-birthdate": "2017-03-04", "attendee-0-grade": "3"})
        self.client.post(self.url, data)
        self.assertEqual(EventRegistration.objects.count(), 1)
        staff = get_user_model().objects.create_user(username="st2", password="pw")
        staff.profile.role = UserProfile.Role.STAFF
        staff.profile.save()
        self.client.force_login(staff)
        resp = self.client.get(reverse("events:registrations", args=[self.event.pk]))
        self.assertContains(resp, "Casey Reed")
        self.assertContains(resp, "Mar 4, 2017")
        self.assertContains(resp, "3rd Grade")

    def test_off_by_default_keeps_birthdate_optional(self, *_):
        self.event.require_attendee_details = False
        self.event.save()
        self.client.post(self.url, _payload())
        self.assertEqual(EventRegistration.objects.count(), 1)

    def test_form_says_children_when_on(self, *_):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Add another child")
        self.assertContains(resp, 'data-noun="Child"')


@mock.patch("core.email_service.send_staff_registration_notification")
@mock.patch("core.email_service.send_registration_confirmation")
class PartialExtraChildTests(TestCase):
    def test_partly_filled_second_child_is_validated_blank_one_ignored(self, *_):
        cache.clear()
        event = Event.objects.create(title="Kids", summary="s", description="d", require_attendee_details=True)
        EventOccurrence.objects.create(event=event, starts_at=timezone.now() + timedelta(days=2),
                                       ends_at=timezone.now() + timedelta(days=2, hours=2))
        url = reverse("event_register", args=[event.registration_token])
        data = _payload()
        data.update({"attendee-0-birthdate": "2016-01-01", "attendee-0-grade": "4",
                     "attendee-TOTAL_FORMS": "3",
                     "attendee-1-first_name": "Second", "attendee-1-last_name": "Reed"})
        resp = self.client.post(url, data)  # child 2 lacks birthdate/grade; child 3 blank
        self.assertEqual(EventRegistration.objects.count(), 0)
        self.assertContains(resp, "This field is required", count=2)
        data.update({"attendee-1-birthdate": "2018-05-05", "attendee-1-grade": "1"})
        self.client.post(url, data)
        reg = EventRegistration.objects.get()
        self.assertEqual(reg.attendees.count(), 2)
        self.assertEqual(reg.number_of_attendees, 2)

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

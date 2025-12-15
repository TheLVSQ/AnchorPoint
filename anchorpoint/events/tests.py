from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Event, EventOccurrence, EventRegistration


class EventModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="eventtester", password="password123"
        )

    def _create_event(self, **kwargs):
        defaults = {
            "title": "Test Gathering",
            "summary": "A moment for our community.",
            "description": "Details here.",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        event = Event.objects.create(**defaults)
        EventOccurrence.objects.create(
            event=event,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=2),
        )
        return event

    def test_slug_generated_when_blank(self):
        event = self._create_event()
        self.assertTrue(event.slug.startswith("test-gathering"))

    def test_can_register_respects_capacity_and_attendee_count(self):
        event = self._create_event(registration_capacity=5)
        EventRegistration.objects.create(
            event=event,
            first_name="Sam",
            last_name="Lee",
            email="sam@example.com",
            number_of_attendees=3,
        )
        self.assertTrue(event.can_register())
        EventRegistration.objects.create(
            event=event,
            first_name="J",
            last_name="Doe",
            email="j@example.com",
            number_of_attendees=3,
        )
        self.assertFalse(event.can_register())

    def test_display_cost_handles_free_and_paid(self):
        free_event = self._create_event(is_free=True)
        paid_event = self._create_event(is_free=False, cost_amount=25)
        self.assertEqual(free_event.display_cost, "Free")
        self.assertEqual(paid_event.display_cost, "$25.00")

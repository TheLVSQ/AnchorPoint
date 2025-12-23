from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from groups.models import GroupMembership
from people.models import Person

from .forms import EventRegistrationContactForm
from .models import (
    Event,
    EventOccurrence,
    EventRegistration,
    EventRegistrationAttendee,
    ReleaseDocument,
)
from .services import match_registration_attendees


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
        paid_event = self._create_event(
            is_free=False,
            cost_amount=25,
            cost_type=Event.COST_TYPE_PER_FAMILY,
        )
        self.assertEqual(free_event.display_cost, "Free")
        self.assertEqual(paid_event.display_cost, "$25.00 per family")

    def test_liability_release_link_prefers_custom(self):
        event = self._create_event()
        doc_file = SimpleUploadedFile("standard.pdf", b"pdf")
        release = ReleaseDocument.objects.create(
            name="Standard Release",
            category=ReleaseDocument.CATEGORY_LIABILITY,
            file=doc_file,
        )
        event.liability_release_document = release
        event.save()
        url, name = event.liability_release_link()
        self.assertIn("standard.pdf", url)
        self.assertEqual(name, "Standard Release")
        custom_file = SimpleUploadedFile("custom.pdf", b"custom")
        event.liability_release_custom.save("custom.pdf", custom_file, save=True)
        url, name = event.liability_release_link()
        self.assertIn("custom.pdf", url)
        self.assertIn("Liability Release", name)

    def test_registration_page_shows_release_link(self):
        event = self._create_event()
        doc_file = SimpleUploadedFile("liability.pdf", b"doc")
        release = ReleaseDocument.objects.create(
            name="Release Doc",
            category=ReleaseDocument.CATEGORY_LIABILITY,
            file=doc_file,
        )
        event.liability_release_document = release
        event.save()
        response = self.client.get(
            reverse("event_register", args=[event.registration_token])
        )
        self.assertContains(response, "View Release Doc")

    def test_public_registration_creates_attendees(self):
        event = self._create_event()
        url = reverse("event_register", args=[event.registration_token])
        post_data = {
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
            "attendee-0-first_name": "Casey",
            "attendee-0-last_name": "Reed",
            "attendee-0-email": "casey@example.com",
            "attendee-0-phone": "555-111-2222",
            "attendee-0-is_minor": "on",
            "attendee-0-parent_guardian_name": "Taylor Reed",
            "attendee-0-parent_guardian_phone": "555-555-0000",
            "attendee-0-parent_guardian_email": "taylor@example.com",
            "attendee-0-emergency_contact_name": "Taylor Reed",
            "attendee-0-emergency_contact_phone": "555-555-0000",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EventRegistration.objects.count(), 1)
        registration = EventRegistration.objects.first()
        self.assertEqual(registration.number_of_attendees, 1)
        attendees = EventRegistrationAttendee.objects.filter(
            registration=registration
        )
        self.assertEqual(attendees.count(), 1)
        attendee = attendees.first()
        self.assertEqual(attendee.first_name, "Casey")
        self.assertTrue(attendee.is_minor)
        self.assertIsNone(attendee.person)
        self.assertEqual(
            attendee.match_status,
            EventRegistrationAttendee.MATCH_STATUS_PENDING,
        )


class EventRegistrationFormTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Form Test",
            summary="Summary",
            description="Desc",
        )

    def _base_form_data(self):
        return {
            "first_name": "Alex",
            "last_name": "Morgan",
            "email": "alex@example.com",
            "phone": "555-999-8888",
            "accept_liability": True,
            "liability_release_signature": "Alex Morgan",
        }

    def test_media_release_signature_required_when_accepting(self):
        data = self._base_form_data()
        data["accept_media"] = True
        form = EventRegistrationContactForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Type your name to sign the photo/media release.",
            form.errors.get("media_release_signature", []),
        )

    def test_apply_release_metadata_sets_fields(self):
        data = self._base_form_data()
        form = EventRegistrationContactForm(data=data)
        self.assertTrue(form.is_valid())
        registration = EventRegistration(
            event=self.event,
            first_name="Alex",
            last_name="Morgan",
            email="alex@example.com",
            phone="555-999-8888",
        )
        form.apply_release_metadata(
            registration,
            ip_address="127.0.0.1",
            user_agent="UnitTest",
        )
        self.assertIsNotNone(registration.liability_release_accepted_at)
        self.assertEqual(registration.liability_release_name, "Alex Morgan")
        self.assertEqual(registration.liability_release_ip, "127.0.0.1")


class RegistrationMatchingServiceTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Camp",
            summary="Summary",
            description="Desc",
        )

    def test_attendee_links_to_existing_person(self):
        person = Person.objects.create(
            first_name="Casey",
            last_name="Reed",
            email="casey@example.com",
        )
        registration = EventRegistration.objects.create(
            event=self.event,
            first_name="Taylor",
            last_name="Reed",
            email="taylor@example.com",
        )
        attendee = EventRegistrationAttendee.objects.create(
            registration=registration,
            event=self.event,
            first_name="Casey",
            last_name="Reed",
            email="casey@example.com",
        )
        match_registration_attendees(registration)
        attendee.refresh_from_db()
        self.assertEqual(attendee.person, person)
        event = Event.objects.get(pk=self.event.pk)
        self.assertIsNotNone(event.registration_group)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=event.registration_group,
                person=person,
            ).exists()
        )

    def test_match_service_leaves_pending_without_existing_person(self):
        registration = EventRegistration.objects.create(
            event=self.event,
            first_name="Taylor",
            last_name="Reed",
            email="taylor@example.com",
            phone="555-000-0000",
            address_line1="123 Main",
            city="City",
            state="ST",
        )
        attendee = EventRegistrationAttendee.objects.create(
            registration=registration,
            event=self.event,
            first_name="Jordan",
            last_name="Reed",
            is_minor=True,
            parent_guardian_name="Taylor Reed",
            parent_guardian_email="taylor@example.com",
            parent_guardian_phone="555-000-0000",
        )
        match_registration_attendees(registration)
        attendee.refresh_from_db()
        self.assertIsNone(attendee.person)
        self.assertEqual(
            attendee.match_status,
            EventRegistrationAttendee.MATCH_STATUS_PENDING,
        )


class RegistrationQueueViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="manager",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )
        self.event = Event.objects.create(
            title="Queue Event",
            summary="Summary",
            description="Desc",
        )
        self.registration = EventRegistration.objects.create(
            event=self.event,
            first_name="Taylor",
            last_name="Reed",
            email="taylor@example.com",
        )
        self.attendee = EventRegistrationAttendee.objects.create(
            registration=self.registration,
            event=self.event,
            first_name="Jordan",
            last_name="Reed",
            parent_guardian_email="taylor@example.com",
            is_minor=True,
        )

    def test_queue_assigns_existing_person(self):
        person = Person.objects.create(
            first_name="Jordan",
            last_name="Reed",
            email="jordan@example.com",
        )
        self.client.force_login(self.user)
        url = reverse("events:registration_queue")
        response = self.client.post(
            url,
            {
                "attendee_id": self.attendee.id,
                "person": person.id,
                "action": "assign",
                "notes": "Matched manually",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.attendee.refresh_from_db()
        self.assertEqual(self.attendee.person, person)
        self.assertEqual(
            self.attendee.match_status,
            EventRegistrationAttendee.MATCH_STATUS_MATCHED,
        )
        self.assertEqual(self.attendee.match_notes, "Matched manually")
        event = Event.objects.get(pk=self.event.pk)
        self.assertIsNotNone(event.registration_group)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=event.registration_group,
                person=person,
            ).exists()
        )

    def test_queue_creates_person(self):
        self.client.force_login(self.user)
        url = reverse("events:registration_queue")
        response = self.client.post(
            url,
            {
                "attendee_id": self.attendee.id,
                "action": "create",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.attendee.refresh_from_db()
        self.assertIsNotNone(self.attendee.person)
        self.assertEqual(
            self.attendee.match_status,
            EventRegistrationAttendee.MATCH_STATUS_MATCHED,
        )
        event = Event.objects.get(pk=self.event.pk)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=event.registration_group,
                person=self.attendee.person,
            ).exists()
        )


class EventRosterViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rosteruser",
            password="password123",
            is_staff=True,
        )
        self.event = Event.objects.create(
            title="Retreat",
            summary="Summary",
            description="Desc",
        )
        registration = EventRegistration.objects.create(
            event=self.event,
            first_name="Taylor",
            last_name="Reed",
            email="taylor@example.com",
        )
        self.registration = registration
        self.attendee = EventRegistrationAttendee.objects.create(
            registration=registration,
            event=self.event,
            first_name="Casey",
            last_name="Reed",
            email="casey@example.com",
        )

    def test_roster_view_lists_attendees(self):
        self.client.force_login(self.user)
        url = reverse("events:roster", args=[self.event.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Casey Reed")
        # Ensure the group exists even before matches
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.registration_group)
        self.registration.liability_release_accepted_at = timezone.now()
        self.registration.save()
        response = self.client.get(url)
        self.assertContains(response, "Liability Signed")

    def test_roster_export_returns_csv(self):
        self.client.force_login(self.user)
        url = reverse("events:roster_export", args=[self.event.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("Casey Reed", response.content.decode())

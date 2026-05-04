from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import (
    CheckIn, CheckInConfiguration, CheckInSession, CheckInWindow, Room,
)
from core.models import OrganizationSettings
from households.models import Household, HouseholdMember
from people.models import Person


class KioskFlowTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(
            name="Sunday Kids",
            welcome_message="Welcome!",
            location_name="Main Building",
            min_age=3,
            max_age=12,
        )
        self.room = Room.objects.create(name="Room 100")
        self.config.rooms.add(self.room)

        now = timezone.localtime()
        self.window = CheckInWindow.objects.create(
            configuration=self.config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=now.weekday(),
            checkin_opens=(now - timedelta(hours=1)).time(),
            event_starts=now.time(),
            checkin_closes=(now + timedelta(hours=1)).time(),
            event_ends=(now + timedelta(hours=2)).time(),
        )

        self.household = Household.objects.create(name="Johnson Family", phone="555-123-4567")
        self.parent = Person.objects.create(
            first_name="Mark", last_name="Johnson",
            birthdate=date.today() - timedelta(days=365 * 35),
        )
        self.child = Person.objects.create(
            first_name="Emma", last_name="Johnson",
            birthdate=date.today() - timedelta(days=365 * 8),
            allergies="Peanuts",
        )
        HouseholdMember.objects.create(
            household=self.household, person=self.parent,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        HouseholdMember.objects.create(
            household=self.household, person=self.child,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )

        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def test_unlock_with_correct_pin(self):
        response = self.client.post(
            reverse("checkin:kiosk_unlock"), {"pin": "1234"}
        )
        self.assertRedirects(response, reverse("checkin:kiosk_lookup"))

    def test_unlock_with_wrong_pin(self):
        response = self.client.post(
            reverse("checkin:kiosk_unlock"), {"pin": "9999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect PIN")

    def test_lookup_requires_pin(self):
        response = self.client.get(reverse("checkin:kiosk_lookup"))
        self.assertRedirects(response, reverse("checkin:kiosk_unlock"))

    def test_lookup_finds_family_by_name(self):
        self._unlock()
        response = self.client.get(
            reverse("checkin:kiosk_lookup"), {"query": "Johnson"}
        )
        self.assertContains(response, "Johnson Family")

    def test_family_select_shows_eligible_child(self):
        self._unlock()
        # Hit lookup first to create session in kiosk session
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        response = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.household.pk])
        )
        self.assertContains(response, "Emma Johnson")

    def test_checkin_creates_records(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        response = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.child.pk}": "on",
                f"room_{self.child.pk}": str(self.room.pk),
            },
        )
        self.assertRedirects(response, reverse("checkin:kiosk_confirmation"))
        self.assertTrue(CheckIn.objects.filter(person=self.child).exists())

    def test_checkin_security_code_is_4_chars(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.child.pk}": "on",
                f"room_{self.child.pk}": str(self.room.pk),
            },
        )
        checkin = CheckIn.objects.get(person=self.child)
        self.assertEqual(len(checkin.security_code), 4)

    def test_family_select_without_session_redirects_to_lookup(self):
        self._unlock()
        # Don't hit lookup first — no session_id set
        response = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.household.pk])
        )
        self.assertRedirects(response, reverse("checkin:kiosk_lookup"))


class QuickRegistrationViewTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(name="Open Check-In")
        self.room = Room.objects.create(name="Room A")
        self.config.rooms.add(self.room)
        now = timezone.localtime()
        CheckInWindow.objects.create(
            configuration=self.config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=now.weekday(),
            checkin_opens=(now - timedelta(hours=1)).time(),
            event_starts=now.time(),
            checkin_closes=(now + timedelta(hours=1)).time(),
            event_ends=(now + timedelta(hours=2)).time(),
        )
        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def test_quick_register_creates_family(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"))
        response = self.client.post(
            reverse("checkin:kiosk_quick_register"),
            {
                "parent_first_name": "Sarah",
                "parent_last_name": "Martinez",
                "parent_phone": "5551234567",
                "parent_email": "sarah@test.com",
                "phone_opt_in": "on",
                "child_count": "1",
                "child_0-first_name": "Mia",
                "child_0-last_name": "Martinez",
                "child_0-birthdate": "2019-05-15",
            },
        )
        self.assertTrue(Person.objects.filter(first_name="Sarah", last_name="Martinez").exists())
        self.assertTrue(Person.objects.filter(first_name="Mia", last_name="Martinez").exists())
        from households.models import Household
        self.assertTrue(Household.objects.filter(name="Martinez Family").exists())
        household = Household.objects.get(name="Martinez Family")
        self.assertRedirects(
            response,
            reverse("checkin:kiosk_family_select", args=[household.pk]),
        )

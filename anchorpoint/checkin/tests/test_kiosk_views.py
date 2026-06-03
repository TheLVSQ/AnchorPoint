from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from unittest import mock

from checkin.models import (
    CheckIn, CheckInConfiguration, CheckInSession, CheckInWindow, Room,
    generate_unique_security_code,
)
from core.models import OrganizationSettings
from households.models import Household, HouseholdMember
from people.models import Person
from django.contrib.auth import get_user_model
from core.models import UserProfile


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
            day_of_week=(now.weekday() + 1) % 7,
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

    def test_checked_out_child_can_check_in_again(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        post_data = {
            f"select_{self.child.pk}": "on",
            f"room_{self.child.pk}": str(self.room.pk),
        }
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]), post_data
        )
        first = CheckIn.objects.get(person=self.child)
        first.checkout()

        # Re-running the flow for a checked-out child must produce a fresh
        # active check-in (not silently no-op), and surface it on confirmation.
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]), post_data
        )
        active = CheckIn.objects.filter(
            person=self.child, checked_out_at__isnull=True
        )
        self.assertEqual(active.count(), 1)
        self.assertEqual(
            self.client.session.get("kiosk_checkin_ids"),
            [active.first().pk],
        )

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
            day_of_week=(now.weekday() + 1) % 7,
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


class StandaloneSessionFallbackTests(TestCase):
    def setUp(self):
        self.household = Household.objects.create(name="Anderson Family", phone="555-222-1111")
        self.child = Person.objects.create(
            first_name="Noah",
            last_name="Anderson",
            birthdate=date.today() - timedelta(days=365 * 9),
        )
        HouseholdMember.objects.create(
            household=self.household,
            person=self.child,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        self.room = Room.objects.create(name="Room B")
        self.session = CheckInSession.objects.create(
            name="Standalone Session",
            date=timezone.localdate(),
            checkin_opens=(timezone.localtime() - timedelta(hours=1)).time(),
            checkin_closes=(timezone.localtime() + timedelta(hours=1)).time(),
            event_starts=timezone.localtime().time(),
            event_ends=(timezone.localtime() + timedelta(hours=2)).time(),
            is_active=True,
        )
        self.session.rooms.add(self.room)
        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def test_lookup_uses_standalone_session_when_no_open_configs(self):
        self._unlock()
        response = self.client.get(reverse("checkin:kiosk_lookup"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["session"].pk, self.session.pk)

    def test_stale_session_from_previous_day_is_not_reused(self):
        # A session id left in the kiosk cookie from yesterday must not be used
        # to check anyone in today.
        self._unlock()
        stale = CheckInSession.objects.create(
            name="Yesterday",
            date=timezone.localdate() - timedelta(days=1),
            checkin_opens=(timezone.localtime() - timedelta(hours=1)).time(),
            checkin_closes=(timezone.localtime() + timedelta(hours=1)).time(),
            event_starts=timezone.localtime().time(),
            event_ends=(timezone.localtime() + timedelta(hours=2)).time(),
            is_active=True,
        )
        kiosk_sess = self.client.session
        kiosk_sess["kiosk_session_id"] = stale.pk
        kiosk_sess.save()

        response = self.client.get(reverse("checkin:kiosk_lookup"))
        self.assertEqual(response.status_code, 200)
        # Falls back to today's standalone session, never the stale one.
        self.assertEqual(response.context["session"].pk, self.session.pk)

    def test_family_select_allows_checkin_for_standalone_session(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"))
        response = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.child.pk}": "on",
                f"room_{self.child.pk}": str(self.room.pk),
            },
        )
        self.assertRedirects(response, reverse("checkin:kiosk_confirmation"))
        self.assertTrue(
            CheckIn.objects.filter(session=self.session, person=self.child).exists()
        )


class SecurityCodeUniquenessTests(TestCase):
    """A shared security code must never collide with another *active* family
    in the same session, or checkout would surface the wrong children."""

    def setUp(self):
        self.session = CheckInSession.objects.create(
            name="Codes Session",
            date=timezone.localdate(),
            checkin_opens=(timezone.localtime() - timedelta(hours=1)).time(),
            checkin_closes=(timezone.localtime() + timedelta(hours=1)).time(),
            event_starts=timezone.localtime().time(),
            event_ends=(timezone.localtime() + timedelta(hours=2)).time(),
            is_active=True,
        )
        self.person = Person.objects.create(first_name="A", last_name="B")

    def test_skips_code_already_active_in_session(self):
        CheckIn.objects.create(
            session=self.session, person=self.person, security_code="ABCD",
        )
        # Force the raw generator to return the taken code once, then a free one.
        with mock.patch(
            "checkin.models.generate_security_code",
            side_effect=["ABCD", "WXYZ"],
        ):
            code = generate_unique_security_code(self.session)
        self.assertEqual(code, "WXYZ")

    def test_reuses_code_freed_by_checkout(self):
        ci = CheckIn.objects.create(
            session=self.session, person=self.person, security_code="ABCD",
        )
        ci.checkout()  # now checked out — code is free to reuse
        with mock.patch(
            "checkin.models.generate_security_code", side_effect=["ABCD"],
        ):
            code = generate_unique_security_code(self.session)
        self.assertEqual(code, "ABCD")


class SessionStatsAccessControlTests(TestCase):
    def setUp(self):
        self.session = CheckInSession.objects.create(
            name="Stats Session",
            date=timezone.localdate(),
            checkin_opens=(timezone.localtime() - timedelta(hours=1)).time(),
            checkin_closes=(timezone.localtime() + timedelta(hours=1)).time(),
            event_starts=timezone.localtime().time(),
            event_ends=(timezone.localtime() + timedelta(hours=2)).time(),
            is_active=True,
        )
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staff@example.com",
            email="staff@example.com",
            password="pass1234",
        )
        self.staff_user.profile.role = UserProfile.Role.STAFF
        self.staff_user.profile.save(update_fields=["role"])

        self.volunteer_user = user_model.objects.create_user(
            username="vol@example.com",
            email="vol@example.com",
            password="pass1234",
        )
        self.volunteer_user.profile.role = UserProfile.Role.VOLUNTEER
        self.volunteer_user.profile.save(update_fields=["role"])

    def test_stats_requires_login(self):
        response = self.client.get(
            reverse("checkin:api_session_stats", args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_stats_denies_non_staff_user(self):
        self.client.login(username="vol@example.com", password="pass1234")
        response = self.client.get(
            reverse("checkin:api_session_stats", args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_stats_allows_staff_user(self):
        self.client.login(username="staff@example.com", password="pass1234")
        response = self.client.get(
            reverse("checkin:api_session_stats", args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("checked_in", response.json())

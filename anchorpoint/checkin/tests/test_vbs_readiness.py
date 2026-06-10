"""Tests for the VBS-readiness work: kiosk bug fixes, SMS pickup codes, and
the live session stats partial."""

from datetime import date, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import (
    CheckIn, CheckInConfiguration, CheckInSession, CheckInWindow, PrintAgent,
    Room,
)
from checkin.services.checkin_sms import send_security_code_sms
from core.models import OrganizationSettings, UserProfile
from households.models import Household, HouseholdMember
from messaging.models import CommunicationLog
from people.models import Person


def _open_window(config):
    # Fixed all-day times: relative `now ± 1h` times wrap past midnight when the
    # suite runs late in the day, silently closing every window.
    now = timezone.localtime()
    return CheckInWindow.objects.create(
        configuration=config,
        schedule_type=CheckInWindow.TYPE_WEEKLY,
        day_of_week=(now.weekday() + 1) % 7,
        checkin_opens=time(0, 0),
        event_starts=time(0, 5),
        checkin_closes=time(23, 50),
        event_ends=time(23, 55),
    )


class KioskFixtureMixin:
    """Open config + window, one household with an adult and two kids."""

    def setUp(self):
        super().setUp()
        self.config = CheckInConfiguration.objects.create(
            name="VBS", min_age=3, max_age=12
        )
        self.room_a = Room.objects.create(name="Room A", capacity=10)
        self.room_b = Room.objects.create(name="Room B", capacity=10)
        self.config.rooms.add(self.room_a, self.room_b)
        self.window = _open_window(self.config)

        self.household = Household.objects.create(name="Walker Family")
        self.parent = Person.objects.create(
            first_name="Pat", last_name="Walker",
            birthdate=date.today() - timedelta(days=365 * 35),
            phone="+15551230001", phone_opt_in=True,
        )
        self.kid1 = Person.objects.create(
            first_name="Ava", last_name="Walker",
            birthdate=date.today() - timedelta(days=365 * 7),
        )
        self.kid2 = Person.objects.create(
            first_name="Ben", last_name="Walker",
            birthdate=date.today() - timedelta(days=365 * 9),
        )
        HouseholdMember.objects.create(
            household=self.household, person=self.parent,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        for kid in (self.kid1, self.kid2):
            HouseholdMember.objects.create(
                household=self.household, person=kid,
                relationship_type=HouseholdMember.RelationshipType.CHILD,
            )

        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()
        self._unlock()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def _start_kiosk_session(self):
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Walker"})


class RoomSelectionTests(KioskFixtureMixin, TestCase):
    """Bug 1a: partial-family check-in must work, with visible errors."""

    def test_radios_render_without_required_attribute(self):
        self._start_kiosk_session()
        response = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.household.pk])
        )
        self.assertNotContains(response, "required>")

    def test_selected_member_without_room_gets_form_error(self):
        self._start_kiosk_session()
        response = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {f"select_{self.kid1.pk}": "on"},  # no room chosen
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "choose a room for Ava")
        self.assertFalse(CheckIn.objects.filter(person=self.kid1).exists())

    def test_partial_family_checkin_succeeds(self):
        self._start_kiosk_session()
        response = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.kid1.pk}": "on",
                f"room_{self.kid1.pk}": str(self.room_a.pk),
                # kid2 not selected, no room for them either
            },
        )
        self.assertRedirects(response, reverse("checkin:kiosk_confirmation"))
        self.assertTrue(CheckIn.objects.filter(person=self.kid1).exists())
        self.assertFalse(CheckIn.objects.filter(person=self.kid2).exists())

    def test_single_room_session_preselects_room(self):
        config = CheckInConfiguration.objects.create(name="One Room", min_age=3, max_age=12)
        only_room = Room.objects.create(name="Only Room")
        config.rooms.add(only_room)
        self.window.delete()
        self.config.is_active = False
        self.config.save()
        _open_window(config)

        self._start_kiosk_session()
        response = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.household.pk])
        )
        self.assertContains(response, "checked>")

    def test_roomless_session_still_checks_in(self):
        config = CheckInConfiguration.objects.create(name="No Rooms", min_age=3, max_age=12)
        self.window.delete()
        self.config.is_active = False
        self.config.save()
        _open_window(config)

        self._start_kiosk_session()
        response = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {f"select_{self.kid1.pk}": "on"},
        )
        self.assertRedirects(response, reverse("checkin:kiosk_confirmation"))
        checkin = CheckIn.objects.get(person=self.kid1)
        self.assertIsNone(checkin.room)


class QuickRegisterRemoveTests(KioskFixtureMixin, TestCase):
    """Bug 1b: removing a child mid-form must not break registration."""

    def _post_register(self, data):
        base = {
            "parent_first_name": "New",
            "parent_last_name": "Family",
            "parent_phone": "+15559990000",
            "parent_email": "",
        }
        base.update(data)
        return self.client.post(reverse("checkin:kiosk_quick_register"), base)

    def test_gap_in_child_prefixes_registers_remaining_children(self):
        # Parent added 3 kids then removed the middle one: child_1 is absent
        # but child_count stays at its high-water mark of 3.
        response = self._post_register({
            "child_count": "3",
            "child_0-first_name": "First",
            "child_0-birthdate": "2018-01-01",
            "child_2-first_name": "Third",
            "child_2-birthdate": "2016-05-05",
        })
        self.assertEqual(response.status_code, 302)
        family = Household.objects.get(name="Family Family")
        kids = family.memberships.filter(
            relationship_type=HouseholdMember.RelationshipType.CHILD
        )
        self.assertEqual(kids.count(), 2)
        self.assertEqual(
            {m.person.first_name for m in kids}, {"First", "Third"}
        )

    def test_bogus_child_count_does_not_crash(self):
        response = self._post_register({
            "child_count": "banana",
            "child_0-first_name": "Solo",
            "child_0-birthdate": "2018-01-01",
        })
        self.assertEqual(response.status_code, 302)

    def test_no_children_present_shows_error(self):
        response = self._post_register({"child_count": "3"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least one child")

    def test_invalid_child_field_shows_error_banner(self):
        response = self._post_register({
            "child_count": "1",
            "child_0-first_name": "NoBirthdate",
            "child_0-birthdate": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "highlighted child fields")


class PrintPathTests(KioskFixtureMixin, TestCase):
    """Bug 1c: agent-queued labels must suppress the direct-print fallback."""

    def _check_in_kid(self):
        self._start_kiosk_session()
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.kid1.pk}": "on",
                f"room_{self.kid1.pk}": str(self.room_a.pk),
            },
        )

    def test_direct_print_skipped_when_agent_queued(self):
        with mock.patch(
            "checkin.views.enqueue_checkin_labels", return_value=2
        ), mock.patch(
            "checkin.views.PrintService"
        ) as mock_service:
            self._check_in_kid()
            response = self.client.get(reverse("checkin:kiosk_confirmation"))
        mock_service.return_value.print_checkins.assert_not_called()
        self.assertContains(response, "Labels are printing now")

    def test_direct_print_attempted_when_no_agent(self):
        with mock.patch(
            "checkin.views.enqueue_checkin_labels", return_value=0
        ), mock.patch("checkin.views.PrintService") as mock_service:
            mock_service.return_value.print_checkins.return_value = False
            self._check_in_kid()
            self.client.get(reverse("checkin:kiosk_confirmation"))
        mock_service.return_value.print_checkins.assert_called_once()


class LookupGuardrailTests(KioskFixtureMixin, TestCase):
    """Bug 1d: minimum query length and a result cap."""

    def test_one_char_query_rejected(self):
        self._start_kiosk_session()
        response = self.client.get(reverse("checkin:kiosk_lookup"), {"query": "w"})
        self.assertContains(response, "at least 2 characters")
        self.assertEqual(len(response.context["households"]), 0)

    def test_results_capped_at_25(self):
        for i in range(30):
            household = Household.objects.create(name=f"Smithson {i} Family")
            person = Person.objects.create(
                first_name=f"P{i}", last_name="Smithson"
            )
            HouseholdMember.objects.create(
                household=household, person=person,
                relationship_type=HouseholdMember.RelationshipType.ADULT,
            )
        self._start_kiosk_session()
        response = self.client.get(
            reverse("checkin:kiosk_lookup"), {"query": "Smithson"}
        )
        self.assertEqual(len(response.context["households"]), 25)
        self.assertTrue(response.context["results_capped"])
        self.assertContains(response, "first 25 matches")


class CheckinSmsTests(KioskFixtureMixin, TestCase):
    """Part 2: pickup-code SMS to opted-in household adults."""

    def setUp(self):
        super().setUp()
        org = OrganizationSettings.load()
        org.twilio_account_sid = "AC123"
        org.twilio_auth_token = "token"
        org.twilio_phone_number = "+15551234567"
        org.save()
        self.session = CheckInSession.objects.create(
            name="VBS Day 1", date=timezone.localdate(),
            checkin_opens=time(0, 0), event_starts=time(0, 5),
            checkin_closes=time(23, 50), event_ends=time(23, 55),
        )
        self.checkin = CheckIn.objects.create(
            session=self.session, person=self.kid1,
            room=self.room_a, security_code="ABCD",
        )

    def test_sends_to_opted_in_adult_and_logs(self):
        with mock.patch(
            "messaging.services.TwilioService.send_sms", return_value="SM1"
        ) as mock_send:
            sent = send_security_code_sms(
                self.household, [self.checkin], "ABCD", self.session
            )
        self.assertEqual(sent, 1)
        mock_send.assert_called_once()
        self.assertIn("ABCD", mock_send.call_args[0][1])
        self.assertIn("Ava", mock_send.call_args[0][1])
        log = CommunicationLog.objects.get(person=self.parent)
        self.assertEqual(log.summary, "Check-in pickup code")
        self.assertEqual(log.metadata["security_code"], "ABCD")

    def test_no_send_without_opt_in(self):
        self.parent.phone_opt_in = False
        self.parent.save()
        with mock.patch(
            "messaging.services.TwilioService.send_sms"
        ) as mock_send:
            sent = send_security_code_sms(
                self.household, [self.checkin], "ABCD", self.session
            )
        self.assertEqual(sent, 0)
        mock_send.assert_not_called()

    def test_no_send_without_twilio_config(self):
        org = OrganizationSettings.load()
        org.twilio_account_sid = ""
        org.save()
        sent = send_security_code_sms(
            self.household, [self.checkin], "ABCD", self.session
        )
        self.assertEqual(sent, 0)

    def test_twilio_error_does_not_raise(self):
        from messaging.services import TwilioRequestError

        with mock.patch(
            "messaging.services.TwilioService.send_sms",
            side_effect=TwilioRequestError("boom"),
        ):
            sent = send_security_code_sms(
                self.household, [self.checkin], "ABCD", self.session
            )
        self.assertEqual(sent, 0)
        self.assertEqual(CommunicationLog.objects.count(), 0)

    def test_kiosk_flow_sends_sms_and_shows_note(self):
        self._start_kiosk_session()
        with mock.patch(
            "messaging.services.TwilioService.send_sms", return_value="SM2"
        ):
            self.client.post(
                reverse("checkin:kiosk_family_select", args=[self.household.pk]),
                {
                    f"select_{self.kid2.pk}": "on",
                    f"room_{self.kid2.pk}": str(self.room_a.pk),
                },
            )
            response = self.client.get(reverse("checkin:kiosk_confirmation"))
        self.assertContains(response, "Code texted to your phone")
        self.assertTrue(
            CommunicationLog.objects.filter(person=self.parent).exists()
        )


class SessionStatsTests(TestCase):
    """Part 3: live stats partial + secured JSON endpoint."""

    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="vbsstaff", password="pw"
        )
        self.staff.profile.role = UserProfile.Role.STAFF
        self.staff.profile.save()

        self.room = Room.objects.create(name="Oak Room", capacity=2)
        self.session = CheckInSession.objects.create(
            name="VBS Stats", date=timezone.localdate(),
            checkin_opens=time(0, 0), event_starts=time(0, 5),
            checkin_closes=time(23, 50), event_ends=time(23, 55),
            is_active=True,
        )
        self.session.rooms.add(self.room)
        kid = Person.objects.create(first_name="Stat", last_name="Kid")
        CheckIn.objects.create(
            session=self.session, person=kid,
            room=self.room, security_code="WXYZ",
        )

    def test_stats_partial_requires_staff(self):
        response = self.client.get(
            reverse("checkin:session_stats", args=[self.session.pk])
        )
        self.assertNotEqual(response.status_code, 200)

    def test_stats_partial_shows_counts_and_rooms(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("checkin:session_stats", args=[self.session.pk])
        )
        self.assertContains(response, "Here Now")
        self.assertContains(response, "Oak Room")
        self.assertContains(response, "1 / 2")

    def test_stats_partial_polls_while_open(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("checkin:session_stats", args=[self.session.pk])
        )
        self.assertContains(response, "every 5s")

    def test_stats_partial_omits_polling_when_closed(self):
        self.session.is_active = False
        self.session.save()
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("checkin:session_stats", args=[self.session.pk])
        )
        self.assertNotContains(response, "every 5s")

    def test_full_room_flagged(self):
        for i in range(2):
            kid = Person.objects.create(first_name=f"Full{i}", last_name="Kid")
            CheckIn.objects.create(
                session=self.session, person=kid,
                room=self.room, security_code=f"FU{i}L",
            )
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("checkin:session_stats", args=[self.session.pk])
        )
        self.assertContains(response, "Full")

    def test_agent_badge_shown_when_paired(self):
        agent = PrintAgent.objects.create(name="Lobby Pi", token_hash="abc123")
        agent.last_seen_at = timezone.now()
        agent.save()
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("checkin:session_stats", args=[self.session.pk])
        )
        self.assertContains(response, "Lobby Pi online")

    def test_api_session_stats_requires_staff(self):
        response = self.client.get(
            reverse("checkin:api_session_stats", args=[self.session.pk])
        )
        self.assertNotEqual(response.status_code, 200)

    def test_api_session_stats_returns_counts(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("checkin:api_session_stats", args=[self.session.pk])
        )
        data = response.json()
        self.assertEqual(data["checked_in"], 1)
        self.assertEqual(data["rooms"][0]["name"], "Oak Room")

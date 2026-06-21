from datetime import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession, PrintAgent, PrintJob, Room
from core.models import UserProfile
from people.models import Person


def _session():
    return CheckInSession.objects.create(
        name="Sunday AM", date=timezone.localdate(),
        checkin_opens=time(0, 0), checkin_closes=time(23, 50),
        event_starts=time(0, 5), event_ends=time(23, 55), is_active=True,
    )


class CheckinManagerTests(TestCase):
    def setUp(self):
        self.vol = get_user_model().objects.create_user(username="vol", password="pw")
        self.vol.profile.role = UserProfile.Role.VOLUNTEER  # lowest tier
        self.vol.profile.save()
        self.session = _session()
        self.room = Room.objects.create(name="Gym A")
        self.session.rooms.add(self.room)
        self.present = Person.objects.create(first_name="Pat", last_name="Present", grade="3")
        self.expected = Person.objects.create(first_name="Xena", last_name="Expected")
        CheckIn.objects.create(session=self.session, person=self.present, room=self.room,
                               security_code="AAAA", arrived_at=timezone.now())
        CheckIn.objects.create(session=self.session, person=self.expected, room=self.room,
                               security_code="BBBB", arrived_at=None)

    def test_volunteer_can_access_present_and_expected(self):
        self.client.force_login(self.vol)
        resp = self.client.get(reverse("checkin:checkin_manager", args=[self.session.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pat Present")
        self.assertContains(resp, "3rd Grade")        # grade rendered
        # Pat is present; Xena (pre-staged) shows in the Expected section.
        self.assertContains(resp, "Xena")
        self.assertEqual(resp.context["stats"]["checked_in"], 1)
        self.assertEqual(resp.context["stats"]["expected"], 1)

    def test_requires_login(self):
        resp = self.client.get(reverse("checkin:checkin_manager", args=[self.session.id]))
        self.assertEqual(resp.status_code, 302)

    def test_roster_partial_polls_itself(self):
        self.client.force_login(self.vol)
        resp = self.client.get(reverse("checkin:checkin_manager_roster", args=[self.session.id]))
        self.assertContains(resp, "Pat Present")
        self.assertContains(resp, 'id="manager-roster"')  # self-replacing poll target

    def test_reprint_queues_when_agent_online(self):
        self.client.force_login(self.vol)
        agent = PrintAgent.objects.create(name="Desk")
        agent.complete_pairing()
        ci = CheckIn.objects.get(person=self.present)
        resp = self.client.post(reverse("checkin:checkin_reprint", args=[self.session.id, ci.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PrintJob.objects.filter(agent=agent).exists())

    def test_reprint_requires_post(self):
        self.client.force_login(self.vol)
        ci = CheckIn.objects.get(person=self.present)
        resp = self.client.get(reverse("checkin:checkin_reprint", args=[self.session.id, ci.id]))
        self.assertEqual(resp.status_code, 405)


class NoShowTests(TestCase):
    def setUp(self):
        self.vol = get_user_model().objects.create_user(username="nsvol", password="pw")
        self.vol.profile.role = UserProfile.Role.VOLUNTEER
        self.vol.profile.save()
        self.client.force_login(self.vol)
        self.session = _session()
        self.kid = Person.objects.create(first_name="Xena", last_name="Expected", grade="2")
        # pre-staged (expected): arrived_at None
        self.ci = CheckIn.objects.create(
            session=self.session, person=self.kid, security_code="BBBB", arrived_at=None,
        )

    def test_expected_shows_in_manager(self):
        resp = self.client.get(reverse("checkin:checkin_manager", args=[self.session.id]))
        self.assertContains(resp, "Expected")
        self.assertContains(resp, "Xena")
        self.assertEqual(resp.context["stats"]["expected"], 1)
        self.assertEqual(resp.context["stats"]["no_show"], 0)

    def test_mark_noshow(self):
        self.client.post(reverse("checkin:checkin_mark_noshow", args=[self.session.id, self.ci.id]))
        self.ci.refresh_from_db()
        self.assertTrue(self.ci.no_show)
        self.assertFalse(self.ci.is_expected)
        resp = self.client.get(reverse("checkin:checkin_manager", args=[self.session.id]))
        self.assertEqual(resp.context["stats"]["expected"], 0)
        self.assertEqual(resp.context["stats"]["no_show"], 1)

    def test_clear_all_expected(self):
        other = Person.objects.create(first_name="Yan", last_name="Two")
        CheckIn.objects.create(session=self.session, person=other, security_code="CCCC", arrived_at=None)
        self.client.post(reverse("checkin:checkin_clear_expected", args=[self.session.id]))
        self.assertEqual(
            self.session.checkins.filter(no_show=True).count(), 2
        )

    def test_noshow_not_counted_as_present(self):
        self.ci.no_show = True
        self.ci.save()
        resp = self.client.get(reverse("checkin:checkin_manager", args=[self.session.id]))
        self.assertEqual(resp.context["stats"]["checked_in"], 0)

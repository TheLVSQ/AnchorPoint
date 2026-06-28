from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession, Room
from core.models import UserProfile
from people.models import Person


def _make_session(name, date, opens=time(0, 0), closes=time(23, 50), active=True):
    return CheckInSession.objects.create(
        name=name, date=date,
        checkin_opens=opens, checkin_closes=closes,
        event_starts=time(0, 5), event_ends=time(23, 55), is_active=active,
    )


class SessionHasEndedTests(TestCase):
    """has_ended reflects the actual date/time window, not the manual is_active flag."""

    def test_past_date_has_ended(self):
        s = _make_session("Yesterday", timezone.localdate() - timedelta(days=1))
        self.assertTrue(s.has_ended)

    def test_future_date_not_ended(self):
        s = _make_session("Tomorrow", timezone.localdate() + timedelta(days=1))
        self.assertFalse(s.has_ended)

    def test_today_within_window_not_ended(self):
        s = _make_session("Now", timezone.localdate(),
                          opens=time(0, 0), closes=time(23, 59))
        self.assertFalse(s.has_ended)

    def test_today_past_close_has_ended(self):
        now = timezone.localtime()
        # Guard the rare midnight edge so subtracting a minute doesn't roll to
        # yesterday's clock time and invert the comparison.
        if now.time() <= time(0, 5):
            self.skipTest("too close to midnight for a deterministic past-close window")
        s = _make_session("Closed", now.date(),
                          opens=time(0, 0), closes=(now - timedelta(minutes=1)).time())
        self.assertTrue(s.has_ended)


class SessionListViewTests(TestCase):
    def setUp(self):
        staff = get_user_model().objects.create_user(username="staff", password="pw")
        staff.profile.role = UserProfile.Role.STAFF
        staff.profile.save()
        self.client.force_login(staff)

    def test_attended_count_excludes_no_shows_and_expected(self):
        session = _make_session("Counting", timezone.localdate())
        room = Room.objects.create(name="R1")
        session.rooms.add(room)
        # 2 actually arrived (one present, one checked out) -> counted.
        p1 = Person.objects.create(first_name="A", last_name="Arrived")
        p2 = Person.objects.create(first_name="B", last_name="Bye")
        CheckIn.objects.create(session=session, person=p1, room=room,
                               security_code="AAAA", arrived_at=timezone.now())
        CheckIn.objects.create(session=session, person=p2, room=room,
                               security_code="BBBB", arrived_at=timezone.now(),
                               checked_out_at=timezone.now())
        # 1 pre-staged expected + 1 no-show -> NOT counted (arrived_at IS NULL).
        p3 = Person.objects.create(first_name="C", last_name="Coming")
        p4 = Person.objects.create(first_name="D", last_name="Didnt")
        CheckIn.objects.create(session=session, person=p3, room=room,
                               security_code="CCCC", arrived_at=None)
        CheckIn.objects.create(session=session, person=p4, room=room,
                               security_code="DDDD", arrived_at=None, no_show=True)

        resp = self.client.get(reverse("checkin:session_list"))
        self.assertEqual(resp.status_code, 200)
        listed = {s.name: s for s in resp.context["sessions"]}
        self.assertEqual(listed["Counting"].attended_count, 2)
        self.assertContains(resp, "2 check-ins")
        self.assertNotContains(resp, "4 check-ins")

    def test_past_session_shows_ended_not_active(self):
        _make_session("OldVBS", timezone.localdate() - timedelta(days=2), active=True)
        resp = self.client.get(reverse("checkin:session_list"))
        self.assertContains(resp, ">Ended<")
        self.assertNotContains(resp, ">Active<")

    def test_current_active_session_shows_active(self):
        _make_session("Today", timezone.localdate(),
                      opens=time(0, 0), closes=time(23, 59), active=True)
        resp = self.client.get(reverse("checkin:session_list"))
        self.assertContains(resp, ">Active<")
        self.assertNotContains(resp, ">Ended<")

    def test_requires_staff(self):
        self.client.logout()
        resp = self.client.get(reverse("checkin:session_list"))
        self.assertEqual(resp.status_code, 302)

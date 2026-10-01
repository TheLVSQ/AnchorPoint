"""Dashboard: live data, scoped by role."""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession
from core.models import UserProfile
from events.models import Event, EventOccurrence, EventRegistration, EventRegistrationAttendee
from people.models import Person


def _user(username, role):
    u = get_user_model().objects.create_user(username=username, password="pw")
    u.profile.role = role
    u.profile.save()
    return u


class DashboardTests(TestCase):
    def setUp(self):
        self.kid = Person.objects.create(first_name="Zara", last_name="Dashkid")
        self.session = CheckInSession.objects.create(
            name="Sunday AM", date=timezone.localdate(), is_active=True,
            checkin_opens=time(8, 0), checkin_closes=time(12, 0),
            event_starts=time(9, 0), event_ends=time(11, 0),
        )
        CheckIn.objects.create(session=self.session, person=self.kid, security_code="AB12",
                               arrived_at=timezone.now())
        self.event = Event.objects.create(title="Fall Fest", summary="s", description="d",
                                          is_published=True)
        EventOccurrence.objects.create(event=self.event, starts_at=timezone.now() + timedelta(days=3),
                                       ends_at=timezone.now() + timedelta(days=3, hours=2))
        reg = EventRegistration.objects.create(event=self.event, first_name="Pat", last_name="Reg")
        EventRegistrationAttendee.objects.create(registration=reg, event=self.event,
                                                 first_name="Unmatched", last_name="Kid")

    def test_staff_sees_live_sections(self):
        self.client.force_login(_user("st", UserProfile.Role.STAFF))
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        for text in ("Sunday AM", "Fall Fest", "1 registration", "Pat Reg",
                     "registration to match", "Zara Dashkid"):
            self.assertContains(resp, text)

    def test_volunteer_sees_sessions_but_no_people(self):
        self.client.force_login(_user("vo", UserProfile.Role.VOLUNTEER))
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Sunday AM")
        self.assertContains(resp, reverse("checkin:checkin_manager", args=[self.session.pk]))
        for text in ("Zara Dashkid", "Pat Reg", "Fall Fest", "registration to match"):
            self.assertNotContains(resp, text)

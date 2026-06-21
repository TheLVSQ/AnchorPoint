from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession, Room
from checkin.services.eligibility import match_room
from core.models import UserProfile
from people.models import Person


def _age(years):
    return date.today() - timedelta(days=365 * years + 10)


class RoomMatchTests(TestCase):
    def setUp(self):
        self.tots = Room.objects.create(name="Tots", sort_order=1, min_age=0, max_age=4)
        self.k4 = Room.objects.create(name="252", sort_order=2, min_grade="k", max_grade="4")
        self.comm = Room.objects.create(name="Community Kids", sort_order=3, min_grade="5", max_grade="6")
        self.overflow = Room.objects.create(name="Overflow", sort_order=4)  # no band
        self.rooms = [self.tots, self.k4, self.comm, self.overflow]

    def test_age_routes_to_tots(self):
        p = Person.objects.create(first_name="Bea", last_name="X", birthdate=_age(3))
        self.assertEqual(match_room(p, self.rooms), self.tots)

    def test_grade_routes_to_252(self):
        p = Person.objects.create(first_name="Cy", last_name="X", grade="3")
        self.assertEqual(match_room(p, self.rooms), self.k4)

    def test_grade_routes_to_community(self):
        p = Person.objects.create(first_name="Di", last_name="X", grade="6")
        self.assertEqual(match_room(p, self.rooms), self.comm)

    def test_unbanded_room_never_matches(self):
        p = Person.objects.create(first_name="No", last_name="Info")  # no age/grade
        self.assertIsNone(match_room(p, self.rooms))

    def test_out_of_range_returns_none(self):
        p = Person.objects.create(first_name="Hi", last_name="Schooler", grade="12")
        self.assertIsNone(match_room(p, self.rooms))

    def test_grade_beats_overlapping_age_band(self):
        # 252 also covers age 5-10; a 5th-grader who is 10 must still go to
        # Community (by grade), not get grabbed by 252's age band.
        self.k4.min_age, self.k4.max_age = 5, 10
        self.k4.save()
        p = Person.objects.create(first_name="Ten", last_name="Fifth", grade="5",
                                  birthdate=_age(10))
        self.assertEqual(match_room(p, self.rooms), self.comm)

    def test_ageonly_kid_routes_by_age_when_no_grade(self):
        self.k4.min_age, self.k4.max_age = 5, 10
        self.k4.save()
        p = Person.objects.create(first_name="Sev", last_name="NoGrade", birthdate=_age(7))
        self.assertEqual(match_room(p, self.rooms), self.k4)


class PreprintAutoRouteTests(TestCase):
    def setUp(self):
        u = get_user_model().objects.create_user(username="pp", password="pw")
        u.profile.role = UserProfile.Role.STAFF
        u.profile.save()
        self.client.force_login(u)
        self.session = CheckInSession.objects.create(
            name="Sunday", date=timezone.localdate(), checkin_opens=time(0, 0),
            checkin_closes=time(23, 50), event_starts=time(0, 5), event_ends=time(23, 55),
        )
        self.tots = Room.objects.create(name="Tots", sort_order=1, min_age=0, max_age=4)
        self.k4 = Room.objects.create(name="252", sort_order=2, min_grade="k", max_grade="4")
        self.session.rooms.set([self.tots, self.k4])
        self.kid = Person.objects.create(first_name="Gus", last_name="Grade3", grade="3")

    def test_preprint_auto_assigns_matched_room_when_none_chosen(self):
        # Select the child but submit NO room — should auto-route to 252 by grade.
        self.client.post(reverse("checkin:session_preprint", args=[self.session.pk]),
                         {f"select_{self.kid.pk}": "on", f"room_{self.kid.pk}": ""})
        ci = CheckIn.objects.get(session=self.session, person=self.kid)
        self.assertEqual(ci.room, self.k4)

    def test_preprint_honors_explicit_room_over_routing(self):
        self.client.post(reverse("checkin:session_preprint", args=[self.session.pk]),
                         {f"select_{self.kid.pk}": "on", f"room_{self.kid.pk}": str(self.tots.pk)})
        ci = CheckIn.objects.get(session=self.session, person=self.kid)
        self.assertEqual(ci.room, self.tots)  # explicit choice wins

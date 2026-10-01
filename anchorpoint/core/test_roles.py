"""Role scope: Volunteer Admins do check-in work only (no staff powers)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from people.models import Person


def _user(username, role):
    user = get_user_model().objects.create_user(username=username, password="pw")
    user.profile.role = role
    user.profile.save()
    return user


class VolunteerAdminScopeTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(
            first_name="Kid", last_name="Example", birthdate=date(2016, 1, 1)
        )
        self.client.force_login(_user("va", UserProfile.Role.VOLUNTEER_ADMIN))

    def test_no_access_to_people_directory_or_custody_notes(self):
        for url in (
            reverse("people_list"),
            reverse("people_detail", args=[self.person.pk]),
            reverse("households:family_list"),
            reverse("groups:list"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_cannot_bulk_delete_people(self):
        resp = self.client.post(reverse("people_bulk_delete"), {
            "ids": [self.person.pk], "action": "confirm",
        })
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Person.objects.filter(pk=self.person.pk).exists())

    def test_cannot_export_reports(self):
        resp = self.client.get(
            reverse("reporting:export", args=["birthday-postcards"]), {"month": 1}
        )
        self.assertEqual(resp.status_code, 403)

    def test_keeps_checkin_admin_pages(self):
        for url in (
            reverse("checkin:session_list"),
            reverse("checkin:room_list"),
            reverse("checkin:configuration_list"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class StaffScopeUnchangedTests(TestCase):
    def test_staff_still_reach_people_and_checkin(self):
        self.client.force_login(_user("st", UserProfile.Role.STAFF))
        for url in (reverse("people_list"), reverse("checkin:session_list")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_plain_volunteer_still_blocked_from_checkin_admin(self):
        self.client.force_login(_user("vo", UserProfile.Role.VOLUNTEER))
        self.assertEqual(self.client.get(reverse("checkin:session_list")).status_code, 403)

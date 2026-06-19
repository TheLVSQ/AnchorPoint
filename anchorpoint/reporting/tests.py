from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession, Room
from core.models import UserProfile
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person


def _staff(username="repstaff"):
    u = get_user_model().objects.create_user(username=username, password="pw")
    u.profile.role = UserProfile.Role.STAFF
    u.profile.save()
    return u


class ReportAccessTests(TestCase):
    def test_index_requires_staff(self):
        self.assertEqual(self.client.get(reverse("reporting:list")).status_code, 302)

    def test_staff_sees_both_reports(self):
        self.client.force_login(_staff())
        resp = self.client.get(reverse("reporting:list"))
        self.assertContains(resp, "Group Roster")
        self.assertContains(resp, "Session Attendance")


class GroupRosterReportTests(TestCase):
    def setUp(self):
        self.client.force_login(_staff())
        self.group = Group.objects.create(name="VBS 2026", category="event")
        self.fam = Household.objects.create(name="Reed Family")
        self.mom = Person.objects.create(
            first_name="Mara", last_name="Reed", phone="+15551230000",
            email="mara@example.com", birthdate=date(1985, 1, 1),
        )
        self.fam.primary_adult = self.mom
        self.fam.save()
        HouseholdMember.objects.create(
            household=self.fam, person=self.mom,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        self.kid = Person.objects.create(
            first_name="Remy", last_name="Reed", birthdate=date(2017, 5, 1),
            allergies="Bees", custody_flag=True, custody_notes="Court order on file",
            photo_consent=True,
        )
        HouseholdMember.objects.create(
            household=self.fam, person=self.kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        GroupMembership.objects.create(group=self.group, person=self.kid)

    def _enroll(self, first):
        p = Person.objects.create(first_name=first, last_name="Reed")
        HouseholdMember.objects.create(
            household=self.fam, person=p,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        GroupMembership.objects.create(group=self.group, person=p)
        return p

    def test_detail_preview_shows_kid(self):
        resp = self.client.get(reverse("reporting:detail", args=["group-roster"]),
                               {"group": self.group.pk})
        self.assertContains(resp, "Remy")
        self.assertContains(resp, "Bees")

    def test_column_selection_limits_csv(self):
        resp = self.client.get(
            reverse("reporting:export", args=["group-roster"]),
            {"group": self.group.pk, "cols": ["first_name", "last_name"]},
        )
        body = resp.content.decode()
        header = body.splitlines()[0]
        self.assertEqual(header.strip(), "First Name,Last Name")
        self.assertNotIn("Guardian Phone", body)
        self.assertNotIn("Photo OK", body)

    def test_sort_orders_rows(self):
        self._enroll("Aaron")  # should sort before "Remy"
        asc = self.client.get(
            reverse("reporting:export", args=["group-roster"]),
            {"group": self.group.pk, "sort": "first_name", "dir": "asc"},
        ).content.decode().splitlines()
        data_first = [ln.split(",")[0] for ln in asc[1:]]
        self.assertEqual(data_first, ["Aaron", "Remy"])

        desc = self.client.get(
            reverse("reporting:export", args=["group-roster"]),
            {"group": self.group.pk, "sort": "first_name", "dir": "desc"},
        ).content.decode().splitlines()
        data_first = [ln.split(",")[0] for ln in desc[1:]]
        self.assertEqual(data_first, ["Remy", "Aaron"])

    def test_detail_export_link_bypasses_hx_boost(self):
        resp = self.client.get(reverse("reporting:detail", args=["group-roster"]),
                               {"group": self.group.pk})
        # The download link must opt out of hx-boost or htmx renders the CSV inline.
        self.assertContains(resp, 'hx-boost="false"')

    def test_invalid_cols_falls_back_to_all(self):
        # Unknown column keys are ignored and selection falls back to all,
        # so the report still renders rather than coming back empty.
        resp = self.client.get(
            reverse("reporting:detail", args=["group-roster"]),
            {"group": self.group.pk, "cols": ["bogus"]},
        )
        self.assertContains(resp, "Remy")
        self.assertContains(resp, "Guardian Phone")

    def test_csv_export_has_headers_and_data(self):
        resp = self.client.get(reverse("reporting:export", args=["group-roster"]),
                               {"group": self.group.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])
        body = resp.content.decode()
        self.assertIn("Guardian Phone", body)
        self.assertIn("Photo OK", body)
        # The kid's row carries guardian phone, allergy, custody note, photo=Yes
        self.assertIn("Remy", body)
        self.assertIn("+15551230000", body)
        self.assertIn("Bees", body)
        self.assertIn("Court order on file", body)
        line = [ln for ln in body.splitlines() if "Remy" in ln][0]
        self.assertIn("Yes", line)  # photo consent granted

    def test_export_without_params_404s(self):
        resp = self.client.get(reverse("reporting:export", args=["group-roster"]))
        self.assertEqual(resp.status_code, 404)


class SessionAttendanceReportTests(TestCase):
    def setUp(self):
        self.client.force_login(_staff("attstaff"))
        self.room = Room.objects.create(name="Oak")
        self.session = CheckInSession.objects.create(
            name="VBS Day 1", date=timezone.localdate(),
            checkin_opens=time(0, 0), event_starts=time(0, 5),
            checkin_closes=time(23, 50), event_ends=time(23, 55),
        )
        present = Person.objects.create(first_name="Pat", last_name="Present")
        expected = Person.objects.create(first_name="Xena", last_name="Expected")
        CheckIn.objects.create(session=self.session, person=present, room=self.room,
                               security_code="AAAA", arrived_at=timezone.now())
        CheckIn.objects.create(session=self.session, person=expected, room=self.room,
                               security_code="BBBB", arrived_at=None)

    def test_csv_reflects_states(self):
        resp = self.client.get(reverse("reporting:export", args=["session-attendance"]),
                               {"session": self.session.pk})
        body = resp.content.decode()
        present_line = [ln for ln in body.splitlines() if "Present" in ln and "Pat" in ln]
        expected_line = [ln for ln in body.splitlines() if "Expected" in ln and "Xena" in ln]
        self.assertTrue(present_line)
        self.assertTrue(expected_line)

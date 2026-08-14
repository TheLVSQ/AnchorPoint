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
            photo_consent="granted",
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
        self.assertNotIn("Photo Consent", body)

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
        self.assertIn("Photo Consent", body)
        # The kid's row carries guardian phone, allergy, custody note, photo state
        self.assertIn("Remy", body)
        self.assertIn("+15551230000", body)
        self.assertIn("Bees", body)
        self.assertIn("Court order on file", body)
        line = [ln for ln in body.splitlines() if "Remy" in ln][0]
        self.assertIn("Granted", line)  # photo consent granted

    def test_export_without_params_404s(self):
        resp = self.client.get(reverse("reporting:export", args=["group-roster"]))
        self.assertEqual(resp.status_code, 404)


class BirthdayPostcardReportTests(TestCase):
    def setUp(self):
        self.client.force_login(_staff("bdaystaff"))
        self.fam = Household.objects.create(
            name="Cole Family", address_line1="12 Elm St", city="Dover",
            state="NH", postal_code="03820",
        )
        self.dad = Person.objects.create(
            first_name="Ed", last_name="Cole", birthdate=date(1980, 6, 2),
        )
        self.fam.primary_adult = self.dad
        self.fam.save()
        HouseholdMember.objects.create(
            household=self.fam, person=self.dad,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        self.june_kid = Person.objects.create(
            first_name="Junie", last_name="Cole", birthdate=date(2018, 6, 14),
        )
        self.march_kid = Person.objects.create(
            first_name="Marchy", last_name="Cole", birthdate=date(2019, 3, 3),
        )
        for kid in (self.june_kid, self.march_kid):
            HouseholdMember.objects.create(
                household=self.fam, person=kid,
                relationship_type=HouseholdMember.RelationshipType.CHILD,
            )

    def _export(self, month):
        return self.client.get(
            reverse("reporting:export", args=["birthday-postcards"]),
            {"month": month},
        ).content.decode()

    def test_only_kids_with_birthday_in_month(self):
        body = self._export(6)
        self.assertIn("Junie", body)
        self.assertNotIn("Marchy", body)   # wrong month
        self.assertNotIn("Ed,Cole", body)  # adult with a June birthday

    def test_address_falls_back_to_household(self):
        line = [ln for ln in self._export(6).splitlines() if "Junie" in ln][0]
        self.assertIn("12 Elm St", line)
        self.assertIn("Dover", line)
        self.assertIn("03820", line)

    def test_own_address_wins_over_household(self):
        self.june_kid.address_line1 = "99 Oak Ave"
        self.june_kid.city = "Lee"
        self.june_kid.save()
        line = [ln for ln in self._export(6).splitlines() if "Junie" in ln][0]
        self.assertIn("99 Oak Ave", line)
        self.assertNotIn("12 Elm St", line)

    def test_birthday_and_guardian_columns(self):
        line = [ln for ln in self._export(6).splitlines() if "Junie" in ln][0]
        self.assertIn("June 14", line)
        self.assertIn("Ed Cole", line)


class GroupMailingListReportTests(TestCase):
    def setUp(self):
        self.client.force_login(_staff("mailstaff"))
        self.group = Group.objects.create(name="VBS 2026 Participants", category="event")
        self.fam = Household.objects.create(
            name="Hale Family", address_line1="7 Pine Rd", city="Durham",
            state="NH", postal_code="03824",
        )
        self.mom = Person.objects.create(
            first_name="Nora", last_name="Hale", birthdate=date(1988, 2, 1),
        )
        self.fam.primary_adult = self.mom
        self.fam.save()
        HouseholdMember.objects.create(
            household=self.fam, person=self.mom,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        self.kid = Person.objects.create(
            first_name="Theo", last_name="Hale", birthdate=date(2016, 9, 9),
        )
        HouseholdMember.objects.create(
            household=self.fam, person=self.kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        GroupMembership.objects.create(group=self.group, person=self.kid)

    def test_csv_has_address_birthdate_guardian(self):
        body = self.client.get(
            reverse("reporting:export", args=["group-mailing-list"]),
            {"group": self.group.pk},
        ).content.decode()
        line = [ln for ln in body.splitlines() if "Theo" in ln][0]
        self.assertIn("2016-09-09", line)
        self.assertIn("Nora Hale", line)
        self.assertIn("7 Pine Rd", line)
        self.assertIn("Durham", line)
        self.assertNotIn("Nora,Hale", body)  # only enrolled people, not the guardian


class MissingDataReportTests(TestCase):
    def setUp(self):
        self.client.force_login(_staff("gapstaff"))

    def _export(self):
        return self.client.get(
            reverse("reporting:export", args=["missing-data"])
        ).content.decode()

    def test_complete_adult_not_listed(self):
        Person.objects.create(
            first_name="Whole", last_name="Adult", birthdate=date(1975, 1, 1),
            email="whole@example.com", phone="+15550001111",
            address_line1="1 Main St", city="Dover",
        )
        self.assertNotIn("Whole", self._export())

    def test_adult_missing_contact_and_address(self):
        Person.objects.create(
            first_name="Gappy", last_name="Adult", birthdate=date(1975, 1, 1),
        )
        line = [ln for ln in self._export().splitlines() if "Gappy" in ln][0]
        self.assertIn("address", line)
        self.assertIn("email", line)
        self.assertIn("phone", line)
        self.assertNotIn("grade", line)  # child-only checks don't apply

    def test_child_missing_child_fields(self):
        fam = Household.objects.create(name="Solo Family")
        kid = Person.objects.create(
            first_name="Loney", last_name="Kid", birthdate=date(2018, 4, 4),
        )
        HouseholdMember.objects.create(
            household=fam, person=kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        line = [ln for ln in self._export().splitlines() if "Loney" in ln][0]
        self.assertIn("Child", line)
        self.assertIn("grade", line)
        self.assertIn("guardian", line)
        self.assertIn("emergency contact phone", line)
        self.assertIn("photo consent", line)
        self.assertNotIn("email", line)  # adult-only checks don't apply

    def test_guardian_phone_satisfies_emergency_contact(self):
        fam = Household.objects.create(
            name="Set Family", address_line1="2 Oak St", city="Lee",
        )
        mom = Person.objects.create(
            first_name="Prim", last_name="Set", phone="+15559998888",
            email="prim@example.com", birthdate=date(1985, 5, 5),
        )
        fam.primary_adult = mom
        fam.save()
        HouseholdMember.objects.create(
            household=fam, person=mom,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        kid = Person.objects.create(
            first_name="Covered", last_name="Set", birthdate=date(2017, 7, 7),
            grade="1", photo_consent="granted",
        )
        HouseholdMember.objects.create(
            household=fam, person=kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        body = self._export()
        # Kid inherits household address + guardian phone; everything else set.
        self.assertNotIn("Covered", body)

    def test_inactive_people_excluded(self):
        Person.objects.create(first_name="Ghost", last_name="Gone", status="inactive")
        self.assertNotIn("Ghost", self._export())

    def test_missing_data_renders_without_params(self):
        Person.objects.create(first_name="Gappy", last_name="Row")
        resp = self.client.get(reverse("reporting:detail", args=["missing-data"]))
        self.assertContains(resp, "Gappy")


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

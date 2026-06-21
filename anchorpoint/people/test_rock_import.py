"""Tests for the Rock RMS person-export importer."""

import csv
import io
from datetime import date

from django.test import TestCase
from django.urls import reverse

from households.models import Household, HouseholdMember
from people.models import Person
from people.services.rock_import import RockImportError, parse_csv, run_rock_import

COLS = [
    "Email", "Gender", "Last Name", "Nick Name", "Name", "Birth Date",
    "Connection Status", "Id", "Is Deceased", "Marital Status",
    "Primary Family Id", "Family Name", "Record Status", "Record Type",
    "Allergy", "Legal Notes", "Home Address - Street 1", "Home Address - City",
    "Home Address - State", "Home Address - Postal Code", "Age", "Phone Number",
    "Custody Notes", "Emergency Contact: Name", "Emergency Contact: Phone Number",
    "Emergency Contact: Relationship",
]


def _csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in COLS})
    return buf.getvalue()


def _person(**kw):
    base = {"Record Type": "Person", "Is Deceased": "False"}
    base.update(kw)
    return base


# A family: one adult (no DOB), one child (DOB → minor).
FAMILY = [
    _person(Id="10", **{
        "Nick Name": "Maria", "Last Name": "Ruiz", "Gender": "Female",
        "Marital Status": "Married", "Connection Status": "Member",
        "Primary Family Id": "100", "Family Name": "Ruiz Family",
        "Phone Number": "540-555-0101", "Email": "maria@example.com",
        "Home Address - Street 1": "12 Oak St", "Home Address - City": "Bolivar",
        "Home Address - State": "MO", "Home Address - Postal Code": "65613",
    }),
    _person(Id="11", **{
        "Nick Name": "Leo", "Last Name": "Ruiz", "Gender": "Male",
        "Birth Date": "5/1/2017", "Connection Status": "Attendee",
        "Primary Family Id": "100", "Family Name": "Ruiz Family",
        "Allergy": "Peanuts", "Custody Notes": "Court order on file",
        "Emergency Contact: Name": "Aunt Jo", "Emergency Contact: Relationship": "Aunt",
        "Emergency Contact: Phone Number": "540-555-0199",
    }),
]


class RockImportTests(TestCase):
    def test_dry_run_writes_nothing(self):
        result = run_rock_import(parse_csv(_csv(FAMILY)), commit=False)
        self.assertEqual(Person.objects.count(), 0)
        self.assertEqual(Household.objects.count(), 0)
        self.assertFalse(result.committed)
        self.assertEqual(result.stats["people_created"], 2)

    def test_commit_creates_family(self):
        run_rock_import(parse_csv(_csv(FAMILY)), commit=True)
        self.assertEqual(Person.objects.count(), 2)
        hh = Household.objects.get(external_id="rock-fam:100")
        self.assertEqual(hh.name, "Ruiz Family")
        self.assertEqual(hh.address_line1, "12 Oak St")
        self.assertEqual(hh.city, "Bolivar")
        # Adult is primary; child linked as child.
        self.assertEqual(hh.primary_adult.first_name, "Maria")
        leo = Person.objects.get(first_name="Leo")
        self.assertEqual(
            HouseholdMember.objects.get(household=hh, person=leo).relationship_type,
            HouseholdMember.RelationshipType.CHILD,
        )

    def test_field_mapping(self):
        run_rock_import(parse_csv(_csv(FAMILY)), commit=True)
        maria = Person.objects.get(first_name="Maria")
        self.assertEqual(maria.gender, "female")
        self.assertEqual(maria.marital_status, "married")
        self.assertEqual(maria.status, "member")
        self.assertEqual(maria.external_id, "rock:10")
        leo = Person.objects.get(first_name="Leo")
        self.assertEqual(leo.birthdate, date(2017, 5, 1))
        self.assertEqual(leo.allergies, "Peanuts")
        self.assertTrue(leo.custody_flag)
        self.assertEqual(leo.custody_notes, "Court order on file")
        self.assertEqual(leo.status, "regular_attendee")  # "Attendee"
        self.assertIn("Aunt Jo", leo.notes)  # emergency contact captured

    def test_idempotent_rerun(self):
        run_rock_import(parse_csv(_csv(FAMILY)), commit=True)
        result = run_rock_import(parse_csv(_csv(FAMILY)), commit=True)
        self.assertEqual(Person.objects.count(), 2)       # no duplicates
        self.assertEqual(Household.objects.count(), 1)
        self.assertEqual(result.stats["people_matched"], 2)
        self.assertEqual(result.stats["people_created"], 0)

    def test_same_surname_different_family_stays_separate(self):
        rows = [
            _person(Id="1", **{"Nick Name": "Al", "Last Name": "Smith",
                               "Primary Family Id": "1", "Family Name": "Smith Family"}),
            _person(Id="2", **{"Nick Name": "Bo", "Last Name": "Smith",
                               "Primary Family Id": "2", "Family Name": "Smith Family"}),
        ]
        run_rock_import(parse_csv(_csv(rows)), commit=True)
        self.assertEqual(Household.objects.count(), 2)  # NOT merged by name

    def test_skips_restuser_deceased_and_stock(self):
        rows = [
            _person(Id="1", **{"Nick Name": "Real", "Last Name": "Person",
                               "Primary Family Id": "1", "Family Name": "Person Family"}),
            _person(Id="2", Record_Type="RestUser", **{
                "Record Type": "RestUser", "Nick Name": "Rest", "Last Name": "User",
                "Primary Family Id": "2", "Family Name": "x"}),
            _person(Id="3", **{"Nick Name": "Dead", "Last Name": "Guy",
                               "Is Deceased": "True", "Primary Family Id": "3",
                               "Family Name": "y"}),
            _person(Id="4", **{"Nick Name": "Admin", "Last Name": "Admin",
                               "Primary Family Id": "4", "Family Name": "Admin"}),
        ]
        result = run_rock_import(parse_csv(_csv(rows)), commit=True)
        self.assertEqual(Person.objects.count(), 1)
        self.assertEqual(result.stats["skipped"], 3)

    def test_family_name_normalized_to_family_suffix(self):
        rows = [_person(Id="50", **{"Nick Name": "Julia", "Last Name": "Abel",
                                    "Primary Family Id": "200", "Family Name": "Abel",
                                    "Age": "3"})]
        run_rock_import(parse_csv(_csv(rows)), commit=True)
        self.assertEqual(Household.objects.get(external_id="rock-fam:200").name, "Abel Family")

    def test_lone_child_is_not_primary_adult(self):
        # Julia is 3 (Age column, no birthdate) and the only member — she must
        # be a child and the family must have NO primary adult.
        rows = [_person(Id="50", **{"Nick Name": "Julia", "Last Name": "Abel",
                                    "Primary Family Id": "200", "Family Name": "Abel",
                                    "Age": "3"})]
        run_rock_import(parse_csv(_csv(rows)), commit=True)
        hh = Household.objects.get(external_id="rock-fam:200")
        self.assertIsNone(hh.primary_adult)
        julia = Person.objects.get(first_name="Julia")
        self.assertEqual(
            HouseholdMember.objects.get(household=hh, person=julia).relationship_type,
            HouseholdMember.RelationshipType.CHILD,
        )

    def test_age_column_used_when_no_birthdate(self):
        rows = [_person(Id="51", **{"Nick Name": "Kid", "Last Name": "Noage",
                                    "Primary Family Id": "201", "Family Name": "Noage Family",
                                    "Age": "10"})]
        run_rock_import(parse_csv(_csv(rows)), commit=True)
        kid = Person.objects.get(first_name="Kid")
        hh = Household.objects.get(external_id="rock-fam:201")
        self.assertEqual(
            HouseholdMember.objects.get(household=hh, person=kid).relationship_type,
            HouseholdMember.RelationshipType.CHILD,
        )

    def test_rerun_fixes_name_and_clears_bad_primary(self):
        # Simulate the already-imported bad state, then re-run the fixed import.
        hh = Household.objects.create(external_id="rock-fam:200", name="Abel")
        julia = Person.objects.create(external_id="rock:50", first_name="Julia", last_name="Abel")
        hh.primary_adult = julia
        hh.save()
        HouseholdMember.objects.create(household=hh, person=julia,
                                       relationship_type=HouseholdMember.RelationshipType.ADULT)
        rows = [_person(Id="50", **{"Nick Name": "Julia", "Last Name": "Abel",
                                    "Primary Family Id": "200", "Family Name": "Abel", "Age": "3"})]
        run_rock_import(parse_csv(_csv(rows)), commit=True)
        hh.refresh_from_db()
        self.assertEqual(hh.name, "Abel Family")   # renamed
        self.assertIsNone(hh.primary_adult)        # bad primary cleared

    def test_negative_allergy_custody_treated_as_empty(self):
        # Rock often stores "No"/"None" answers; they must not become a false
        # allergy ✚ or custody shield on the label.
        rows = [_person(Id="9", **{
            "Nick Name": "Sam", "Last Name": "Quirk", "Birth Date": "5/1/2017",
            "Primary Family Id": "9", "Family Name": "Quirk Family",
            "Allergy": "No", "Custody Notes": "None",
        })]
        run_rock_import(parse_csv(_csv(rows)), commit=True)
        sam = Person.objects.get(first_name="Sam")
        self.assertEqual(sam.allergies, "")
        self.assertFalse(sam.custody_flag)

    def test_merges_existing_person_without_rock_id(self):
        # An existing record (e.g. from the earlier VBS import) with no Rock id
        # must be matched (by name+birthdate), not duplicated, and gets claimed.
        existing = Person.objects.create(first_name="Leo", last_name="Ruiz",
                                         birthdate=date(2017, 5, 1))
        result = run_rock_import(parse_csv(_csv(FAMILY)), commit=True)
        self.assertEqual(Person.objects.filter(first_name="Leo").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.external_id, "rock:11")
        self.assertEqual(existing.allergies, "Peanuts")   # blank field filled
        self.assertGreaterEqual(result.stats["people_matched"], 1)

    def test_bad_headers_raise(self):
        with self.assertRaises(RockImportError):
            parse_csv("name,age\nA,7\n")


class RockImportPageTests(TestCase):
    """The web upload → preview → commit flow (shares run_rock_import)."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from core.models import UserProfile
        self.user = get_user_model().objects.create_user(username="rockstaff", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def _upload(self, action="preview"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        content = _csv(FAMILY).encode()
        return self.client.post(
            reverse("rock_import"),
            {"action": action, "csv_file": SimpleUploadedFile("rock.csv", content, content_type="text/csv")},
        )

    def test_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("rock_import")).status_code, 302)

    def test_volunteer_admin_forbidden(self):
        # Staff/admin only — volunteer admins (and volunteers) can't import a CMS.
        from django.contrib.auth import get_user_model
        from core.models import UserProfile
        va = get_user_model().objects.create_user(username="va", password="pw")
        va.profile.role = UserProfile.Role.VOLUNTEER_ADMIN
        va.profile.save()
        self.client.force_login(va)
        self.assertEqual(self.client.get(reverse("rock_import")).status_code, 403)

    def test_page_uses_generic_cms_wording(self):
        resp = self.client.get(reverse("rock_import"))
        self.assertContains(resp, "Other CMS import")

    def test_preview_writes_nothing(self):
        resp = self._upload()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Preview")
        self.assertEqual(Person.objects.count(), 0)

    def test_confirm_commits(self):
        self._upload()  # stashes in session
        resp = self.client.post(reverse("rock_import"), {"action": "commit"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Person.objects.count(), 2)
        self.assertTrue(Household.objects.filter(external_id="rock-fam:100").exists())

    def test_bad_headers_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("x.csv", b"name,age\nA,7\n", content_type="text/csv")
        resp = self.client.post(reverse("rock_import"), {"action": "preview", "csv_file": bad})
        self.assertContains(resp, "missing required columns")
        self.assertFalse(Person.objects.exists())

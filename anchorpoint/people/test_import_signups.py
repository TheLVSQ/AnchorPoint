"""Tests for the import_signups management command (VBS signup CSV import)."""

import csv
import io
import os
import tempfile
from datetime import date

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person

HEADERS = [
    "parent_first_name", "parent_last_name", "parent_phone", "parent_email",
    "phone_opt_in", "child_first_name", "child_last_name", "child_birthdate",
    "child_grade", "child_allergies", "custody_notes", "unauthorized_pickup",
]


def _write_csv(rows):
    """Write dict rows to a temp CSV; returns its path."""
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    writer = csv.DictWriter(fh, fieldnames=HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in HEADERS})
    fh.close()
    return fh.name


def _run(path, *flags):
    out = io.StringIO()
    call_command("import_signups", path, *flags, stdout=out)
    return out.getvalue()


def _family_rows():
    return [
        {
            "parent_first_name": "Sarah", "parent_last_name": "Smith",
            "parent_phone": "540-555-0101", "phone_opt_in": "yes",
            "child_first_name": "Emma", "child_birthdate": "2019-04-12",
            "child_grade": "1", "child_allergies": "Peanuts",
        },
        {
            "parent_first_name": "Sarah", "parent_last_name": "Smith",
            "parent_phone": "(540) 555-0101", "phone_opt_in": "yes",
            "child_first_name": "Jack", "child_birthdate": "09/30/2017",
            "child_grade": "3rd Grade",
        },
    ]


class ImportSignupsTests(TestCase):
    def tearDown(self):
        for f in getattr(self, "_csvs", []):
            os.unlink(f)

    def _csv(self, rows):
        path = _write_csv(rows)
        self._csvs = getattr(self, "_csvs", []) + [path]
        return path

    def test_same_phone_groups_into_one_family(self):
        out = _run(self._csv(_family_rows()), "--commit")
        self.assertEqual(Person.objects.filter(last_name="Smith").count(), 3)
        parent = Person.objects.get(first_name="Sarah")
        household = Household.objects.get(members=parent)
        kids = household.memberships.filter(
            relationship_type=HouseholdMember.RelationshipType.CHILD
        )
        self.assertEqual(kids.count(), 2)
        emma = Person.objects.get(first_name="Emma")
        self.assertEqual(emma.birthdate, date(2019, 4, 12))
        self.assertEqual(emma.allergies, "Peanuts")
        jack = Person.objects.get(first_name="Jack")
        self.assertEqual(jack.grade, "3")  # "3rd Grade" normalized
        self.assertIn("CREATE parent", out)

    def test_existing_parent_matched_not_duplicated(self):
        existing = Person.objects.create(
            first_name="Sarah", last_name="Smith",
            phone="+15405550101", phone_opt_in=False,
        )
        out = _run(self._csv(_family_rows()), "--commit")
        self.assertEqual(
            Person.objects.filter(first_name="Sarah", last_name="Smith").count(), 1
        )
        existing.refresh_from_db()
        # CSV said opt-in yes, but matched people keep their recorded consent.
        self.assertFalse(existing.phone_opt_in)
        self.assertIn("MATCHED parent", out)

    def test_existing_child_matched_and_empty_fields_filled(self):
        existing = Person.objects.create(
            first_name="Emma", last_name="Smith", birthdate=date(2019, 4, 12)
        )
        _run(self._csv(_family_rows()), "--commit")
        self.assertEqual(Person.objects.filter(first_name="Emma").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.allergies, "Peanuts")  # filled (was empty)

    def test_existing_child_data_never_overwritten(self):
        existing = Person.objects.create(
            first_name="Emma", last_name="Smith",
            birthdate=date(2019, 4, 12), allergies="Bees",
        )
        _run(self._csv(_family_rows()), "--commit")
        existing.refresh_from_db()
        self.assertEqual(existing.allergies, "Bees")

    def test_dry_run_writes_nothing(self):
        out = _run(self._csv(_family_rows()))
        self.assertEqual(Person.objects.count(), 0)
        self.assertEqual(Household.objects.count(), 0)
        self.assertIn("DRY RUN", out)
        # Report still shows the full plan
        self.assertIn("CREATE parent", out)

    def test_unparseable_birthdate_warns_but_still_imports(self):
        # birthdate is optional now; an unrecognized one warns and imports blank
        # rather than dropping the child.
        rows = _family_rows()
        rows[0]["child_birthdate"] = "tomorrow-ish"
        out = _run(self._csv(rows), "--commit")
        self.assertIn("unrecognized birthdate", out)
        emma = Person.objects.get(first_name="Emma")
        self.assertIsNone(emma.birthdate)
        self.assertTrue(Person.objects.filter(first_name="Jack").exists())

    def test_missing_birthdate_is_allowed(self):
        rows = _family_rows()
        rows[0]["child_birthdate"] = ""
        _run(self._csv(rows), "--commit")
        self.assertTrue(Person.objects.filter(first_name="Emma").exists())

    def test_group_enrollment_idempotent(self):
        path = self._csv(_family_rows())
        _run(path, "--commit", "--group", "VBS 2026")
        _run(path, "--commit", "--group", "VBS 2026")
        group = Group.objects.get(name="VBS 2026")
        self.assertEqual(group.category, "event")
        self.assertEqual(group.memberships.count(), 2)  # kids only, no dupes
        parent = Person.objects.get(first_name="Sarah")
        self.assertFalse(
            GroupMembership.objects.filter(group=group, person=parent).exists()
        )

    def test_rerun_is_fully_idempotent(self):
        path = self._csv(_family_rows())
        _run(path, "--commit")
        before = Person.objects.count()
        out = _run(path, "--commit")
        self.assertEqual(Person.objects.count(), before)
        self.assertIn("MATCHED parent", out)
        self.assertIn("MATCHED child", out)
        self.assertNotIn("CREATE parent", out)

    def test_custody_fields_set_flag(self):
        rows = [{
            "parent_first_name": "Mike", "parent_last_name": "Jones",
            "parent_phone": "5405550102",
            "child_first_name": "Lily", "child_last_name": "Jones-Carter",
            "child_birthdate": "2018-06-15",
            "custody_notes": "Mom has sole custody",
            "unauthorized_pickup": "John Carter",
        }]
        _run(self._csv(rows), "--commit")
        lily = Person.objects.get(first_name="Lily")
        self.assertTrue(lily.custody_flag)
        self.assertEqual(lily.unauthorized_pickup, "John Carter")

    def test_missing_headers_abort(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        fh.write("parent_first_name,child_first_name\nA,B\n")
        fh.close()
        self._csvs = getattr(self, "_csvs", []) + [fh.name]
        with self.assertRaises(CommandError):
            _run(fh.name, "--commit")
        self.assertEqual(Person.objects.count(), 0)

    def test_opt_out_respected_on_create(self):
        rows = _family_rows()
        for r in rows:
            r["phone_opt_in"] = "no"
        _run(self._csv(rows), "--commit")
        parent = Person.objects.get(first_name="Sarah")
        self.assertFalse(parent.phone_opt_in)


class SignupImportPageTests(TestCase):
    """The web upload → preview → confirm flow (shares run_import with the CLI)."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from core.models import UserProfile
        self.user = get_user_model().objects.create_user(username="impweb", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def _upload(self, action="preview", extra=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        content = (
            "parent_first_name,parent_last_name,parent_phone,child_first_name,child_birthdate\n"
            "Web,Tester,5405550000,Wynn,2018-04-04\n"
        ).encode()
        data = {"action": action, "csv_file": SimpleUploadedFile("signups.csv", content, content_type="text/csv")}
        if extra:
            data.update(extra)
        return self.client.post(reverse("signup_import"), data)

    def test_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("signup_import")).status_code, 302)

    def test_preview_writes_nothing(self):
        resp = self._upload(extra={"group": "VBS Web"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Preview")
        self.assertFalse(Person.objects.filter(first_name="Wynn").exists())  # not yet saved

    def test_confirm_commits(self):
        self._upload(extra={"group": "VBS Web"})  # stashes in session
        resp = self.client.post(reverse("signup_import"), {"action": "commit"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Person.objects.filter(first_name="Wynn").exists())
        from groups.models import Group
        self.assertTrue(Group.objects.filter(name="VBS Web").exists())

    def test_bad_headers_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("x.csv", b"name,age\nA,7\n", content_type="text/csv")
        resp = self.client.post(reverse("signup_import"), {"action": "preview", "csv_file": bad})
        self.assertContains(resp, "missing required columns")
        self.assertFalse(Person.objects.exists())

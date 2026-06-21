from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from messaging.models import CommunicationLog

from core.models import UserProfile
from .models import Person


class PeopleLookupViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester", password="password123"
        )
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        Person.objects.create(
            first_name="Casey",
            last_name="Jordan",
            email="casey@example.com",
            phone="555-111-2222",
        )
        Person.objects.create(
            first_name="Jamie",
            last_name="Stone",
            email="",
            phone="555-999-0000",
        )

    def test_lookup_requires_query(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("people_lookup"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"results": []})

    def test_lookup_returns_matching_people(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("people_lookup"), {"q": "case"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["email"], "casey@example.com")
        self.assertEqual(payload["results"][0]["phone"], "555-111-2222")


class PeopleDetailCommunicationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="viewer", password="password123"
        )
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.person = Person.objects.create(
            first_name="Jordan",
            last_name="Banks",
            phone="555-202-3030",
        )
        CommunicationLog.objects.create(
            person=self.person,
            communication_type=CommunicationLog.CommunicationType.SMS,
            summary="SMS sent",
            detail="Reminder note",
        )

    def test_logs_render_on_detail_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("people_detail", args=[self.person.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Communications History")
        self.assertContains(response, "SMS sent")


class PeopleSearchViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="searcher", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

        Person.objects.create(first_name="Alice", last_name="Smith", phone="+15550001111")
        Person.objects.create(first_name="Bob", last_name="Smith", phone="+15550002222")
        Person.objects.create(first_name="Carol", last_name="Jones", phone="+15550003333")

    def test_search_returns_200(self):
        response = self.client.get(reverse("people_search"), {"q": "Smith"})
        self.assertEqual(response.status_code, 200)

    def test_search_filters_by_first_name(self):
        response = self.client.get(reverse("people_search"), {"q": "Alice"})
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bob")

    def test_search_filters_by_last_name(self):
        response = self.client.get(reverse("people_search"), {"q": "Jones"})
        self.assertContains(response, "Carol")
        self.assertNotContains(response, "Alice")

    def test_search_empty_query_returns_all(self):
        response = self.client.get(reverse("people_search"), {"q": ""})
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")
        self.assertContains(response, "Carol")

    def test_search_returns_partial_with_results_div(self):
        response = self.client.get(reverse("people_search"), {"q": "Smith"})
        self.assertContains(response, 'id="people-results"')

    def test_search_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("people_search"), {"q": "Alice"})
        self.assertNotEqual(response.status_code, 200)

    def test_search_no_results_shows_empty_state(self):
        response = self.client.get(reverse("people_search"), {"q": "Zzznobody"})
        self.assertContains(response, "No people found")


class PeopleAddFamilyTests(TestCase):
    """The 'join an existing family' flow on Add Person (was silently broken)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="famadd", password="pw"
        )
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)
        from households.models import Household
        self.family = Household.objects.create(name="Greene Family")

    def _person_data(self, **extra):
        data = {
            "first_name": "Nora", "last_name": "Greene",
            "email": "", "phone": "", "birthdate": "", "gender": "",
            "grade": "", "marital_status": "", "address_line1": "",
            "address_line2": "", "city": "", "state": "", "postal_code": "",
            "salvation_date": "", "baptism_date": "", "first_visit_date": "",
            "allergies": "", "security_notes": "", "status": "guest", "notes": "",
            "household_action": "skip",
        }
        data.update(extra)
        return data

    def test_join_existing_family_creates_membership(self):
        from households.models import HouseholdMember
        response = self.client.post(
            reverse("people_add"),
            self._person_data(
                household_action="existing",
                household_id=str(self.family.pk),
                household_relationship="child",
            ),
        )
        self.assertEqual(response.status_code, 302)
        person = Person.objects.get(first_name="Nora")
        membership = HouseholdMember.objects.get(person=person)
        self.assertEqual(membership.household, self.family)
        self.assertEqual(membership.relationship_type, "child")

    def test_existing_without_selection_creates_nothing(self):
        response = self.client.post(
            reverse("people_add"),
            self._person_data(household_action="existing", household_id=""),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose which family")
        self.assertFalse(Person.objects.filter(first_name="Nora").exists())

    def test_bogus_household_id_creates_nothing(self):
        response = self.client.post(
            reverse("people_add"),
            self._person_data(household_action="existing", household_id="99999"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Person.objects.filter(first_name="Nora").exists())

    def test_add_form_lists_families_in_selector(self):
        response = self.client.get(reverse("people_add"))
        self.assertContains(response, "Greene Family")


class PeopleListTileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tiles", password="pw"
        )
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_tiles_show_age_status_and_family(self):
        from datetime import date, timedelta
        from households.models import Household, HouseholdMember
        person = Person.objects.create(
            first_name="Iva", last_name="Tiles",
            birthdate=date.today() - timedelta(days=365 * 9 + 5),
            status="regular_attendee",
        )
        family = Household.objects.create(name="Tiles Family")
        HouseholdMember.objects.create(household=family, person=person)

        response = self.client.get(reverse("people_list"))
        self.assertContains(response, "Age 9")
        self.assertContains(response, "Regular Attendee")  # not regular_attendee
        self.assertNotContains(response, "regular_attendee")
        self.assertContains(response, "Tiles Family")


class PeopleCountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cnt", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_overall_count_in_context(self):
        Person.objects.create(first_name="A", last_name="One")
        Person.objects.create(first_name="B", last_name="Two")
        resp = self.client.get(reverse("people_list"))
        self.assertEqual(resp.context["total_people"], 2)

    def test_count_is_unfiltered_during_search(self):
        Person.objects.create(first_name="Alice", last_name="One")
        Person.objects.create(first_name="Bob", last_name="Two")
        resp = self.client.get(reverse("people_list"), {"q": "Alice"})
        self.assertEqual(resp.context["total_people"], 2)  # overall, not the 1 match


class PeopleDeleteTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="del", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)
        self.person = Person.objects.create(first_name="Test", last_name="Dummy")

    def test_confirm_page_renders(self):
        resp = self.client.get(reverse("people_delete", args=[self.person.pk]))
        self.assertContains(resp, "Delete Test Dummy?")

    def test_post_deletes_and_redirects(self):
        resp = self.client.post(reverse("people_delete", args=[self.person.pk]))
        self.assertRedirects(resp, reverse("people_list"))
        self.assertFalse(Person.objects.filter(pk=self.person.pk).exists())

    def test_get_does_not_delete(self):
        self.client.get(reverse("people_delete", args=[self.person.pk]))
        self.assertTrue(Person.objects.filter(pk=self.person.pk).exists())

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.post(reverse("people_delete", args=[self.person.pk]))
        self.assertNotEqual(resp.status_code, 200)
        self.assertTrue(Person.objects.filter(pk=self.person.pk).exists())

    def test_delete_cascades_checkins_but_keeps_family(self):
        from datetime import time
        from django.utils import timezone
        from checkin.models import CheckIn, CheckInSession
        from households.models import Household, HouseholdMember
        fam = Household.objects.create(name="Dummy Family")
        HouseholdMember.objects.create(household=fam, person=self.person)
        session = CheckInSession.objects.create(
            name="S", date=timezone.localdate(), checkin_opens=time(0, 0),
            checkin_closes=time(23, 50), event_starts=time(0, 5), event_ends=time(23, 55),
        )
        CheckIn.objects.create(session=session, person=self.person, security_code="ZZZZ")
        self.client.post(reverse("people_delete", args=[self.person.pk]))
        self.assertFalse(CheckIn.objects.filter(person_id=self.person.pk).exists())
        self.assertTrue(Household.objects.filter(pk=fam.pk).exists())  # family kept


class PeopleDuplicatesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="dup", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse("people_duplicates")).status_code, 200)

    def test_flags_same_name(self):
        Person.objects.create(first_name="Jane", last_name="Doe")
        Person.objects.create(first_name="Jane", last_name="Doe")
        Person.objects.create(first_name="Unique", last_name="Person")
        resp = self.client.get(reverse("people_duplicates"))
        self.assertContains(resp, "Jane Doe")
        self.assertNotContains(resp, "Unique Person")  # single record, not flagged

    def test_flags_same_email_case_insensitive(self):
        Person.objects.create(first_name="A", last_name="X", email="dup@e.com")
        Person.objects.create(first_name="B", last_name="Y", email="DUP@e.com")
        resp = self.client.get(reverse("people_duplicates"))
        self.assertContains(resp, "dup@e.com")

    def test_phone_sharing_family_not_flagged(self):
        # Family members share a phone but have different names → not duplicates.
        Person.objects.create(first_name="Mom", last_name="Reed", phone="+15551112222")
        Person.objects.create(first_name="Kid", last_name="Reed", phone="+15551112222")
        resp = self.client.get(reverse("people_duplicates"))
        self.assertContains(resp, "No potential duplicates")


class PersonStatusDisplayTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="statuser", password="pw"
        )
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_detail_uses_status_display(self):
        person = Person.objects.create(
            first_name="Reg", last_name="Ular", status="regular_attendee"
        )
        response = self.client.get(reverse("people_detail", args=[person.pk]))
        self.assertContains(response, "Regular Attendee")
        self.assertNotContains(response, "regular_attendee")


class PhotoConsentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="photostaff", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_default_false(self):
        p = Person.objects.create(first_name="No", last_name="Consent")
        self.assertFalse(p.photo_consent)

    def test_person_form_sets_consent(self):
        from people.forms import PersonForm
        form = PersonForm(data={
            "first_name": "Pic", "last_name": "Kid", "status": "guest",
            "photo_consent": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        person = form.save()
        self.assertTrue(person.photo_consent)

    def test_detail_shows_consent_state(self):
        p = Person.objects.create(first_name="Yes", last_name="Photo", photo_consent=True)
        resp = self.client.get(reverse("people_detail", args=[p.pk]))
        self.assertContains(resp, "Granted")


class GenderFieldTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="genderstaff", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_add_form_renders_gender_field(self):
        resp = self.client.get(reverse("people_add"))
        self.assertContains(resp, 'name="gender"')

    def test_edit_persists_gender(self):
        person = Person.objects.create(first_name="Gen", last_name="Der")
        data = {
            "first_name": "Gen", "last_name": "Der", "email": "", "phone": "",
            "birthdate": "", "gender": "female", "grade": "", "marital_status": "",
            "address_line1": "", "address_line2": "", "city": "", "state": "",
            "postal_code": "", "salvation_date": "", "baptism_date": "",
            "first_visit_date": "", "allergies": "", "security_notes": "",
            "status": "guest", "notes": "",
        }
        resp = self.client.post(reverse("people_edit", args=[person.pk]), data)
        self.assertEqual(resp.status_code, 302)
        person.refresh_from_db()
        self.assertEqual(person.gender, "female")

    def test_detail_shows_gender_display(self):
        person = Person.objects.create(first_name="Gen", last_name="Der", gender="male")
        resp = self.client.get(reverse("people_detail", args=[person.pk]))
        self.assertContains(resp, "Male")


class EmergencyContactTests(TestCase):
    """A minor's detail page surfaces their guardians' phone numbers up top."""

    def setUp(self):
        from datetime import date, timedelta
        from households.models import Household, HouseholdMember

        self.user = get_user_model().objects.create_user(username="ecstaff", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

        self.fam = Household.objects.create(name="Hart Family")
        self.parent = Person.objects.create(
            first_name="Dana", last_name="Hart", phone="+15405551234",
            email="dana@example.com",
        )
        self.fam.primary_adult = self.parent
        self.fam.save()
        HouseholdMember.objects.create(
            household=self.fam, person=self.parent,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        self.kid = Person.objects.create(
            first_name="Quinn", last_name="Hart",
            birthdate=date.today() - timedelta(days=365 * 8),
        )
        HouseholdMember.objects.create(
            household=self.fam, person=self.kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )

    def test_minor_page_shows_guardian_phone_prominently(self):
        resp = self.client.get(reverse("people_detail", args=[self.kid.pk]))
        self.assertContains(resp, "Emergency Contact")
        self.assertContains(resp, "Dana Hart")
        self.assertContains(resp, "+15405551234")
        self.assertContains(resp, "Primary")

    def test_adult_page_has_no_emergency_card(self):
        resp = self.client.get(reverse("people_detail", args=[self.parent.pk]))
        self.assertNotContains(resp, "Emergency Contact")

    def test_age_unknown_child_member_still_shows_card(self):
        from households.models import HouseholdMember
        kid = Person.objects.create(first_name="Sam", last_name="Hart")  # no birthdate
        HouseholdMember.objects.create(
            household=self.fam, person=kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        resp = self.client.get(reverse("people_detail", args=[kid.pk]))
        self.assertContains(resp, "Emergency Contact")
        self.assertContains(resp, "+15405551234")

    def test_minor_without_guardian_shows_prompt(self):
        from datetime import date, timedelta
        lone = Person.objects.create(
            first_name="Lone", last_name="Kid",
            birthdate=date.today() - timedelta(days=365 * 7),
        )
        resp = self.client.get(reverse("people_detail", args=[lone.pk]))
        self.assertContains(resp, "Emergency Contact")
        self.assertContains(resp, "No guardian linked")


class ImportPhotoConsentTests(TestCase):
    def _csv(self, consent_value):
        import csv, tempfile, os
        headers = [
            "parent_first_name", "parent_last_name", "parent_phone", "parent_email",
            "phone_opt_in", "child_first_name", "child_last_name", "child_birthdate",
            "child_grade", "child_allergies", "custody_notes", "unauthorized_pickup",
            "photo_consent",
        ]
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8")
        w = csv.DictWriter(fh, fieldnames=headers)
        w.writeheader()
        w.writerow({
            "parent_first_name": "Pam", "parent_last_name": "Optin", "parent_phone": "5405559999",
            "child_first_name": "Kid", "child_birthdate": "2018-01-01", "photo_consent": consent_value,
        })
        fh.close()
        self.addCleanup(lambda: os.unlink(fh.name))
        return fh.name

    def test_import_sets_consent_when_yes(self):
        from django.core.management import call_command
        import io
        call_command("import_signups", self._csv("yes"), "--commit", stdout=io.StringIO())
        self.assertTrue(Person.objects.get(first_name="Kid").photo_consent)

    def test_import_consent_false_by_default(self):
        from django.core.management import call_command
        import io
        call_command("import_signups", self._csv("no"), "--commit", stdout=io.StringIO())
        self.assertFalse(Person.objects.get(first_name="Kid").photo_consent)

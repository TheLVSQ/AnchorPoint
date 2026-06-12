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

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from messaging.models import CommunicationLog

from .models import Person


class PeopleLookupViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester", password="password123"
        )
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

from datetime import date

from django.test import TestCase

from checkin.services.quick_registration import register_new_family
from households.models import Household, HouseholdMember
from people.models import Person


class QuickRegistrationTests(TestCase):
    def test_creates_parent_and_child(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            parent_email="sarah@example.com",
            phone_opt_in=True,
            children=[
                {
                    "first_name": "Mia",
                    "last_name": "Martinez",
                    "birthdate": date(2019, 5, 15),
                    "allergies": "Peanuts",
                    "custody_flag": False,
                    "custody_notes": "",
                    "unauthorized_pickup": "",
                },
            ],
        )
        self.assertIsInstance(result["household"], Household)
        self.assertIsInstance(result["parent"], Person)
        self.assertEqual(len(result["children"]), 1)

    def test_parent_fields_populated(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            parent_email="sarah@example.com",
            phone_opt_in=True,
            children=[
                {"first_name": "Mia", "last_name": "Martinez", "birthdate": date(2019, 5, 15)},
            ],
        )
        parent = result["parent"]
        self.assertEqual(parent.first_name, "Sarah")
        self.assertEqual(parent.last_name, "Martinez")
        # normalized_phone strips non-digits — "5551234567" stays "5551234567"
        self.assertEqual(parent.normalized_phone, "5551234567")
        self.assertEqual(parent.email, "sarah@example.com")
        self.assertTrue(parent.phone_opt_in)

    def test_child_fields_populated(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            children=[
                {
                    "first_name": "Mia",
                    "last_name": "Martinez",
                    "birthdate": date(2019, 5, 15),
                    "allergies": "Tree nuts",
                    "custody_flag": True,
                    "custody_notes": "Mother has sole custody",
                    "unauthorized_pickup": "James Martinez",
                },
            ],
        )
        child = result["children"][0]
        self.assertEqual(child.allergies, "Tree nuts")
        self.assertTrue(child.custody_flag)
        self.assertIn("sole custody", child.custody_notes)

    def test_household_created_with_members(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            children=[
                {"first_name": "Mia", "last_name": "Martinez", "birthdate": date(2019, 5, 15)},
                {"first_name": "Leo", "last_name": "Martinez", "birthdate": date(2021, 3, 10)},
            ],
        )
        household = result["household"]
        self.assertEqual(household.name, "Martinez Family")
        self.assertEqual(household.primary_adult, result["parent"])
        self.assertEqual(household.members.count(), 3)  # parent + 2 children

    def test_multiple_children(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            children=[
                {"first_name": "Mia", "last_name": "Martinez", "birthdate": date(2019, 5, 15)},
                {"first_name": "Leo", "last_name": "Martinez", "birthdate": date(2021, 3, 10)},
            ],
        )
        self.assertEqual(len(result["children"]), 2)

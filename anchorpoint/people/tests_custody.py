from datetime import date, timedelta

from django.test import TestCase

from people.models import Person


class PersonCustodyFieldTests(TestCase):
    def test_custody_flag_defaults_false(self):
        person = Person.objects.create(first_name="Test", last_name="Child")
        self.assertFalse(person.custody_flag)

    def test_custody_fields_save_and_retrieve(self):
        person = Person.objects.create(
            first_name="Test",
            last_name="Child",
            birthdate=date.today() - timedelta(days=365 * 7),
            custody_flag=True,
            custody_notes="Parents divorced, mother has primary custody.",
            unauthorized_pickup="John Doe - biological father",
        )
        person.refresh_from_db()
        self.assertTrue(person.custody_flag)
        self.assertIn("primary custody", person.custody_notes)
        self.assertIn("John Doe", person.unauthorized_pickup)

    def test_custody_fields_blank_by_default(self):
        person = Person.objects.create(first_name="Test", last_name="Child")
        self.assertEqual(person.custody_notes, "")
        self.assertEqual(person.unauthorized_pickup, "")

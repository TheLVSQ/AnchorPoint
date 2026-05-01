from datetime import date, timedelta

from django.test import TestCase

from checkin.models import CheckInConfiguration
from checkin.services.eligibility import is_person_eligible
from groups.models import Group, GroupMembership
from people.models import Person


class EligibilityTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(name="Test Config")

    def test_no_filters_everyone_eligible(self):
        person = Person.objects.create(first_name="John", last_name="Doe")
        self.assertTrue(is_person_eligible(person, self.config))

    def test_age_filter_match(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        child = Person.objects.create(
            first_name="Emma", last_name="Smith",
            birthdate=date.today() - timedelta(days=365 * 7),
        )
        self.assertTrue(is_person_eligible(child, self.config))

    def test_age_filter_no_match(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        adult = Person.objects.create(
            first_name="Mark", last_name="Smith",
            birthdate=date.today() - timedelta(days=365 * 35),
        )
        self.assertFalse(is_person_eligible(adult, self.config))

    def test_grade_filter_match(self):
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        child = Person.objects.create(
            first_name="Liam", last_name="Smith", grade="3",
        )
        self.assertTrue(is_person_eligible(child, self.config))

    def test_grade_filter_no_match(self):
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        teen = Person.objects.create(
            first_name="Tyler", last_name="Smith", grade="9",
        )
        self.assertFalse(is_person_eligible(teen, self.config))

    def test_group_filter_match(self):
        group = Group.objects.create(name="Volunteers", category="volunteer")
        self.config.groups.add(group)
        person = Person.objects.create(first_name="Sarah", last_name="Jones")
        GroupMembership.objects.create(group=group, person=person)
        self.assertTrue(is_person_eligible(person, self.config))

    def test_group_filter_no_match(self):
        group = Group.objects.create(name="Volunteers", category="volunteer")
        self.config.groups.add(group)
        person = Person.objects.create(first_name="Bob", last_name="Jones")
        self.assertFalse(is_person_eligible(person, self.config))

    def test_or_logic_age_miss_grade_hit(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        # 4-year-old in kindergarten — outside age but matches grade
        child = Person.objects.create(
            first_name="Mia", last_name="Lee",
            birthdate=date.today() - timedelta(days=365 * 4),
            grade="k",
        )
        self.assertTrue(is_person_eligible(child, self.config))

    def test_or_logic_group_hit_age_miss(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        group = Group.objects.create(name="Helpers", category="volunteer")
        self.config.groups.add(group)
        adult = Person.objects.create(
            first_name="Dan", last_name="Lee",
            birthdate=date.today() - timedelta(days=365 * 40),
        )
        GroupMembership.objects.create(group=group, person=adult)
        self.assertTrue(is_person_eligible(adult, self.config))

    def test_person_without_birthdate_skips_age_check(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        person = Person.objects.create(first_name="Unknown", last_name="Age")
        self.assertFalse(is_person_eligible(person, self.config))

    def test_person_without_grade_skips_grade_check(self):
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        person = Person.objects.create(first_name="No", last_name="Grade")
        self.assertFalse(is_person_eligible(person, self.config))

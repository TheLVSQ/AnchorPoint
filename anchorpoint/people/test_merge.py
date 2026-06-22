"""Tests for the duplicate Person/Household merge service."""

from datetime import date, time

from django.test import TestCase

from checkin.models import CheckInSession, CheckIn
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person
from people.services.merge import merge_persons, merge_households


class MergePersonsTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="VBS 2026", category="event")
        self.fam_a = Household.objects.create(name="Price A")
        self.fam_b = Household.objects.create(name="Price B")
        self.session = CheckInSession.objects.create(
            name="VBS", date=date(2026, 6, 22),
            checkin_opens=time(9, 0), checkin_closes=time(12, 0),
            event_starts=time(9, 30), event_ends=time(11, 30),
        )

    def test_merge_repoints_and_fills_and_deletes(self):
        survivor = Person.objects.create(first_name="Pete", last_name="Price")  # no grade
        dup = Person.objects.create(
            first_name="Pete", last_name="Price", grade="3", allergies="Bees",
        )
        HouseholdMember.objects.create(
            household=self.fam_a, person=survivor,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        HouseholdMember.objects.create(
            household=self.fam_b, person=dup,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        GroupMembership.objects.create(group=self.group, person=dup)
        CheckIn.objects.create(session=self.session, person=dup, security_code="DUP1")

        merge_persons(survivor, dup)

        self.assertFalse(Person.objects.filter(pk=dup.pk).exists())   # dup gone
        survivor.refresh_from_db()
        self.assertEqual(survivor.grade, "3")                          # filled from dup
        self.assertEqual(survivor.allergies, "Bees")
        # In both households now, in the group, owns the check-in.
        self.assertEqual(set(survivor.households.all()), {self.fam_a, self.fam_b})
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=survivor).exists())
        self.assertEqual(CheckIn.objects.get(security_code="DUP1").person, survivor)

    def test_unique_membership_deduped_not_errored(self):
        survivor = Person.objects.create(first_name="Lisa", last_name="Derr")
        dup = Person.objects.create(first_name="Lisa", last_name="Derr")
        # Both in the SAME household and SAME group → re-point must dedup, not crash.
        for p in (survivor, dup):
            HouseholdMember.objects.create(
                household=self.fam_a, person=p,
                relationship_type=HouseholdMember.RelationshipType.ADULT,
            )
            GroupMembership.objects.create(group=self.group, person=p)

        merge_persons(survivor, dup)

        self.assertEqual(
            HouseholdMember.objects.filter(household=self.fam_a, person=survivor).count(), 1
        )
        self.assertEqual(
            GroupMembership.objects.filter(group=self.group, person=survivor).count(), 1
        )
        self.assertFalse(Person.objects.filter(pk=dup.pk).exists())

    def test_does_not_overwrite_survivor_values(self):
        survivor = Person.objects.create(first_name="Amy", last_name="K", grade="2")
        dup = Person.objects.create(first_name="Amy", last_name="K", grade="5")
        merge_persons(survivor, dup)
        survivor.refresh_from_db()
        self.assertEqual(survivor.grade, "2")  # survivor's own value kept

    def test_repoints_primary_adult(self):
        survivor = Person.objects.create(first_name="Mom", last_name="X")
        dup = Person.objects.create(first_name="Mom", last_name="X")
        self.fam_a.primary_adult = dup
        self.fam_a.save()
        merge_persons(survivor, dup)
        self.fam_a.refresh_from_db()
        self.assertEqual(self.fam_a.primary_adult, survivor)


class MergeHouseholdsTests(TestCase):
    def test_moves_members_and_deletes_duplicate(self):
        canonical = Household.objects.create(name="Kline")
        dup = Household.objects.create(name="Kline")
        dad = Person.objects.create(first_name="Matthew", last_name="Kline")
        kid = Person.objects.create(first_name="Joshua", last_name="Kline")
        HouseholdMember.objects.create(
            household=canonical, person=dad,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        canonical.primary_adult = dad
        canonical.save()
        HouseholdMember.objects.create(
            household=dup, person=kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )

        merge_households(canonical, dup)

        self.assertFalse(Household.objects.filter(pk=dup.pk).exists())
        self.assertEqual(set(canonical.members.all()), {dad, kid})
        self.assertEqual(canonical.primary_adult, dad)

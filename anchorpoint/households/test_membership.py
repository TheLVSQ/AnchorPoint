"""Family membership rules: primary adult upkeep, roles, naming, moves, guardian links."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from households import membership
from households.models import FamilyConflictFlag, Household, HouseholdMember
from people.models import Person

ADULT, CHILD = HouseholdMember.RelationshipType.ADULT, HouseholdMember.RelationshipType.CHILD


def _p(first, last="Walker"):
    return Person.objects.create(first_name=first, last_name=last)


class PrimaryAdultTests(TestCase):
    def setUp(self):
        self.sue, self.tom, self.ava = _p("Sue"), _p("Tom"), _p("Ava")
        self.fam = membership.create_family(adult=self.sue)

    def primary(self):
        self.fam.refresh_from_db()
        return self.fam.primary_adult

    def test_create_family_names_and_sets_primary(self):
        self.assertEqual(self.fam.name, "Walker Family")
        self.assertEqual(self.primary(), self.sue)

    def test_first_adult_becomes_primary_when_none(self):
        fam = membership.create_family(name="Kids First")
        membership.add_member(fam, self.ava, CHILD)
        fam.refresh_from_db()
        self.assertIsNone(fam.primary_adult)  # no adult yet: allowed
        membership.add_member(fam, self.tom, ADULT)
        fam.refresh_from_db()
        self.assertEqual(fam.primary_adult, self.tom)

    def test_adding_another_adult_keeps_primary(self):
        membership.add_member(self.fam, self.tom, ADULT)
        self.assertEqual(self.primary(), self.sue)

    def test_removing_primary_promotes_longest_standing_adult(self):
        membership.add_member(self.fam, self.ava, CHILD)
        membership.add_member(self.fam, self.tom, ADULT)
        membership.remove_member(self.fam, self.sue)
        self.assertEqual(self.primary(), self.tom)

    def test_removing_last_adult_blanks_primary(self):
        membership.add_member(self.fam, self.ava, CHILD)
        membership.remove_member(self.fam, self.sue)
        self.assertIsNone(self.primary())

    def test_moving_primary_out_repairs_source(self):
        other = membership.create_family(name="Other Family")
        membership.add_member(self.fam, self.tom, ADULT)
        self.assertTrue(membership.move_member(self.sue, self.fam, other))
        self.assertEqual(self.primary(), self.tom)
        other.refresh_from_db()
        self.assertEqual(other.primary_adult, self.sue)  # first adult of target

    def test_copy_keeps_source(self):
        membership.add_member(self.fam, self.ava, CHILD)
        other = membership.create_family(name="Other Family")
        membership.move_member(self.ava, self.fam, other, role=CHILD, keep_in_source=True)
        self.assertEqual(set(self.ava.households.all()), {self.fam, other})

    def test_move_into_family_already_joined_changes_nothing(self):
        other = membership.create_family(adult=self.sue, name="Also Sue's")
        self.assertFalse(membership.move_member(self.sue, self.fam, other))
        self.assertTrue(HouseholdMember.objects.filter(household=self.fam, person=self.sue).exists())

    def test_demoting_primary_hands_over(self):
        membership.add_member(self.fam, self.tom, ADULT)
        membership.set_role(self.fam, self.sue, CHILD)
        self.assertEqual(self.primary(), self.tom)

    def test_child_cannot_be_primary(self):
        membership.add_member(self.fam, self.ava, CHILD)
        with self.assertRaises(membership.MembershipError):
            membership.set_primary(self.fam, self.ava)
        self.assertEqual(self.primary(), self.sue)

    def test_non_member_cannot_be_primary(self):
        with self.assertRaises(membership.MembershipError):
            membership.set_primary(self.fam, self.tom)

    def test_role_is_required(self):
        with self.assertRaises(membership.MembershipError):
            membership.add_member(self.fam, self.ava, "")
        self.assertFalse(HouseholdMember.objects.filter(person=self.ava).exists())


class NamingTests(TestCase):
    def test_family_surname_prefers_primary_then_adults(self):
        fam = membership.create_family(name="Custom Name")
        membership.add_member(fam, _p("Ava", "Kidname"), CHILD)
        membership.add_member(fam, _p("Sue", "Parent"), ADULT)
        self.assertEqual(membership.family_surname(fam), "Parent")

    def test_family_surname_from_name_when_empty(self):
        self.assertEqual(membership.family_surname(Household.objects.create(name="Reed Household")), "Reed")


class LinkGuardianTests(TestCase):
    def setUp(self):
        self.sue, self.ava = _p("Sue"), _p("Ava")

    def test_creates_guardian_family_named_family(self):
        fam = membership.link_guardian(self.sue, self.ava)
        self.assertEqual(fam.name, "Walker Family")
        self.assertEqual(fam.primary_adult, self.sue)
        self.assertEqual(
            HouseholdMember.objects.get(household=fam, person=self.ava).relationship_type, CHILD
        )

    def test_child_in_another_family_is_linked_and_flagged(self):
        other = membership.create_family(adult=_p("Dad", "Reed"))
        membership.add_member(other, self.ava, CHILD)
        with mock.patch("households.family_flags._email_recipients"):
            fam = membership.link_guardian(self.sue, self.ava)
        self.assertIn(fam, self.ava.households.all())
        flag = FamilyConflictFlag.objects.get(child=self.ava)
        self.assertTrue(flag.added_membership)

    def test_bulk_import_does_not_flag(self):
        other = membership.create_family(adult=_p("Dad", "Reed"))
        membership.add_member(other, self.ava, CHILD)
        membership.link_guardian(self.sue, self.ava, raise_flag=False)
        self.assertFalse(FamilyConflictFlag.objects.exists())

    def test_same_person_is_no_op(self):
        self.assertIsNone(membership.link_guardian(self.sue, self.sue))


class ViewsKeepTheRulesTests(TestCase):
    """The person-page remove/move paths used to leave a stale primary adult."""

    def setUp(self):
        user = get_user_model().objects.create_user(username="staff", password="pw")
        user.profile.role = UserProfile.Role.STAFF
        user.profile.save()
        self.client.force_login(user)
        self.sue, self.tom = _p("Sue"), _p("Tom")
        self.fam = membership.create_family(adult=self.sue)
        membership.add_member(self.fam, self.tom, ADULT)

    def test_person_page_remove_repairs_primary(self):
        self.client.post(reverse("people_household_remove", args=[self.sue.pk, self.fam.pk]))
        self.fam.refresh_from_db()
        self.assertEqual(self.fam.primary_adult, self.tom)

    def test_person_page_move_repairs_primary(self):
        other = membership.create_family(name="Other Family")
        self.client.post(reverse("people_household_move", args=[self.sue.pk, self.fam.pk]),
                         {"target_household": other.pk, "move_action": "move"})
        self.fam.refresh_from_db()
        self.assertEqual(self.fam.primary_adult, self.tom)

    def test_add_person_as_child_to_new_family_is_not_primary(self):
        resp = self.client.post(reverse("people_add"), {
            "first_name": "Ava", "last_name": "Walker", "status": "guest",
            "photo_consent": "unknown", "household_action": "new",
            "household_relationship": CHILD,
        })
        ava = Person.objects.get(first_name="Ava")
        fam = ava.households.get()
        self.assertIsNone(fam.primary_adult, resp)

    def test_family_page_refuses_child_as_primary(self):
        ava = _p("Ava")
        membership.add_member(self.fam, ava, CHILD)
        self.client.post(reverse("households:family_set_primary", args=[self.fam.pk]),
                         {"person_id": ava.pk})
        self.fam.refresh_from_db()
        self.assertEqual(self.fam.primary_adult, self.sue)

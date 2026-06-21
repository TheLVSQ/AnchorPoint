from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from people.models import Person

from .models import Household, HouseholdMember


def _staff(username="famstaff"):
    user = get_user_model().objects.create_user(username=username, password="pw")
    user.profile.role = UserProfile.Role.STAFF
    user.profile.save()
    return user


class FamilyPagesTests(TestCase):
    def setUp(self):
        self.user = _staff()
        self.client.force_login(self.user)

        self.mom = Person.objects.create(
            first_name="Sue", last_name="Walker",
            birthdate=date(1988, 5, 1), status="member",
        )
        self.kid = Person.objects.create(
            first_name="Tess", last_name="Walker", birthdate=date(2018, 2, 2),
        )
        self.family = Household.objects.create(name="Walker Family", primary_adult=self.mom)
        HouseholdMember.objects.create(
            household=self.family, person=self.mom,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        HouseholdMember.objects.create(
            household=self.family, person=self.kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )

    # --- access control -----------------------------------------------------
    def test_anonymous_is_redirected(self):
        self.client.logout()
        for url in (
            reverse("households:family_list"),
            reverse("households:family_detail", args=[self.family.pk]),
            reverse("households:family_edit", args=[self.family.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 302)

    # --- list ----------------------------------------------------------------
    def test_list_shows_family(self):
        response = self.client.get(reverse("households:family_list"))
        self.assertContains(response, "Walker Family")
        self.assertContains(response, "2 members")

    def test_list_search_by_member_last_name(self):
        Household.objects.create(name="Other Family")
        response = self.client.get(reverse("households:family_list"), {"q": "walker"})
        self.assertContains(response, "Walker Family")
        self.assertNotContains(response, "Other Family")

    # --- detail ---------------------------------------------------------------
    def test_detail_shows_members_roles_and_primary(self):
        response = self.client.get(
            reverse("households:family_detail", args=[self.family.pk])
        )
        self.assertContains(response, "Sue Walker")
        self.assertContains(response, "Tess Walker")
        self.assertContains(response, "Primary")

    def test_member_search_excludes_existing_members(self):
        Person.objects.create(first_name="New", last_name="Walkerton")
        response = self.client.get(
            reverse("households:family_detail", args=[self.family.pk]),
            {"member_q": "walker"},
        )
        self.assertContains(response, "Walkerton")
        # Existing member should not appear as an addable candidate
        candidates = response.context["candidates"]
        self.assertNotIn(self.mom, candidates)

    # --- edit ------------------------------------------------------------------
    def test_edit_renames_family(self):
        response = self.client.post(
            reverse("households:family_edit", args=[self.family.pk]),
            {
                "name": "Walker-Smith Family",
                "phone": "", "address_line1": "", "address_line2": "",
                "city": "", "state": "", "postal_code": "",
                "primary_adult": self.mom.pk,
            },
        )
        self.assertRedirects(
            response, reverse("households:family_detail", args=[self.family.pk])
        )
        self.family.refresh_from_db()
        self.assertEqual(self.family.name, "Walker-Smith Family")

    def test_edit_primary_adult_limited_to_members(self):
        outsider = Person.objects.create(first_name="Out", last_name="Sider")
        response = self.client.post(
            reverse("households:family_edit", args=[self.family.pk]),
            {
                "name": "Walker Family",
                "phone": "", "address_line1": "", "address_line2": "",
                "city": "", "state": "", "postal_code": "",
                "primary_adult": outsider.pk,
            },
        )
        self.assertEqual(response.status_code, 200)  # re-rendered with error
        self.family.refresh_from_db()
        self.assertEqual(self.family.primary_adult, self.mom)

    # --- member operations -------------------------------------------------------
    def test_add_member(self):
        dad = Person.objects.create(first_name="Tom", last_name="Walker")
        self.client.post(
            reverse("households:family_member_add", args=[self.family.pk]),
            {"person_id": str(dad.pk), "relationship_type": "adult"},
        )
        self.assertTrue(
            HouseholdMember.objects.filter(household=self.family, person=dad).exists()
        )

    def test_add_member_is_idempotent(self):
        self.client.post(
            reverse("households:family_member_add", args=[self.family.pk]),
            {"person_id": str(self.mom.pk), "relationship_type": "child"},
        )
        membership = HouseholdMember.objects.get(household=self.family, person=self.mom)
        # No duplicate, and the original role wasn't clobbered
        self.assertEqual(membership.relationship_type, "adult")

    def test_remove_member_clears_primary(self):
        membership = HouseholdMember.objects.get(household=self.family, person=self.mom)
        self.client.post(
            reverse(
                "households:family_member_remove",
                args=[self.family.pk, membership.pk],
            )
        )
        self.family.refresh_from_db()
        self.assertIsNone(self.family.primary_adult)
        self.assertTrue(Person.objects.filter(pk=self.mom.pk).exists())  # person kept

    def test_change_role(self):
        membership = HouseholdMember.objects.get(household=self.family, person=self.kid)
        self.client.post(
            reverse(
                "households:family_member_role",
                args=[self.family.pk, membership.pk],
            ),
            {"relationship_type": "student"},
        )
        membership.refresh_from_db()
        self.assertEqual(membership.relationship_type, "student")

    def test_set_primary_requires_membership(self):
        outsider = Person.objects.create(first_name="Out", last_name="Sider")
        self.client.post(
            reverse("households:family_set_primary", args=[self.family.pk]),
            {"person_id": str(outsider.pk)},
        )
        self.family.refresh_from_db()
        self.assertEqual(self.family.primary_adult, self.mom)


class FamilyDeleteTests(TestCase):
    def setUp(self):
        self.user = _staff("delstaff")
        self.client.force_login(self.user)
        self.mom = Person.objects.create(first_name="Sue", last_name="Walker")
        self.kid = Person.objects.create(first_name="Tess", last_name="Walker")
        self.family = Household.objects.create(name="Walker Family", primary_adult=self.mom)
        HouseholdMember.objects.create(
            household=self.family, person=self.mom,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        HouseholdMember.objects.create(
            household=self.family, person=self.kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        self.url = reverse("households:family_delete", args=[self.family.pk])

    def test_detail_has_delete_link(self):
        resp = self.client.get(reverse("households:family_detail", args=[self.family.pk]))
        self.assertContains(resp, self.url)

    def test_confirm_page_lists_members_and_blocks(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "still has 2 members")
        self.assertContains(resp, "Tess")
        self.assertContains(resp, "empty it first")  # final delete disabled

    def test_delete_blocked_while_members_remain(self):
        resp = self.client.post(self.url, {"action": "delete_family"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Household.objects.filter(pk=self.family.pk).exists())

    def test_move_member_to_other_family(self):
        other = Household.objects.create(name="Stone Family")
        kid_membership = HouseholdMember.objects.get(household=self.family, person=self.kid)
        self.client.post(self.url, {
            "action": "move", "member_pk": str(kid_membership.pk),
            "target_household": str(other.pk),
        })
        self.assertFalse(
            HouseholdMember.objects.filter(household=self.family, person=self.kid).exists()
        )
        self.assertTrue(
            HouseholdMember.objects.filter(household=other, person=self.kid).exists()
        )
        self.assertTrue(Person.objects.filter(pk=self.kid.pk).exists())  # person kept

    def test_moving_primary_clears_primary(self):
        other = Household.objects.create(name="Stone Family")
        mom_membership = HouseholdMember.objects.get(household=self.family, person=self.mom)
        self.client.post(self.url, {
            "action": "move", "member_pk": str(mom_membership.pk),
            "target_household": str(other.pk),
        })
        self.family.refresh_from_db()
        self.assertIsNone(self.family.primary_adult)

    def test_delete_person_removes_profile_and_membership(self):
        kid_membership = HouseholdMember.objects.get(household=self.family, person=self.kid)
        self.client.post(self.url, {
            "action": "delete_person", "member_pk": str(kid_membership.pk),
        })
        self.assertFalse(Person.objects.filter(pk=self.kid.pk).exists())
        self.assertFalse(HouseholdMember.objects.filter(pk=kid_membership.pk).exists())

    def test_deleting_primary_person_clears_primary(self):
        mom_membership = HouseholdMember.objects.get(household=self.family, person=self.mom)
        self.client.post(self.url, {
            "action": "delete_person", "member_pk": str(mom_membership.pk),
        })
        self.family.refresh_from_db()
        self.assertIsNone(self.family.primary_adult)

    def test_delete_succeeds_once_empty(self):
        self.family.memberships.all().delete()
        self.family.primary_adult = None
        self.family.save()
        resp = self.client.post(self.url, {"action": "delete_family"})
        self.assertRedirects(resp, reverse("households:family_list"))
        self.assertFalse(Household.objects.filter(pk=self.family.pk).exists())

    def test_empty_confirm_page_offers_delete(self):
        self.family.memberships.all().delete()
        self.family.primary_adult = None
        self.family.save()
        resp = self.client.get(self.url)
        self.assertContains(resp, "no members")
        self.assertNotContains(resp, "empty it first")

    def test_requires_staff(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertRedirects(resp, "/login/", fetch_redirect_response=False)


class HouseholdSelectorLabelTests(TestCase):
    """selector_label() disambiguates same-surname families in dropdowns."""

    def _morris(self, name, adult_first, kid_first, **hh_kwargs):
        adult = Person.objects.create(
            first_name=adult_first, last_name="Morris", birthdate=date(1985, 3, 3)
        )
        kid = Person.objects.create(
            first_name=kid_first, last_name="Morris", birthdate=date(2016, 6, 6)
        )
        hh = Household.objects.create(name=name, primary_adult=adult, **hh_kwargs)
        # Add the kid first to prove ordering puts the primary adult ahead of it.
        HouseholdMember.objects.create(
            household=hh, person=kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        HouseholdMember.objects.create(
            household=hh, person=adult,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        return hh

    def test_label_lists_members_primary_first_with_location(self):
        hh = self._morris("Morris", "John", "Colton", address_line1="12 Oak St")
        label = hh.selector_label()
        self.assertIn("Morris", label)
        self.assertIn("John", label)
        self.assertIn("Colton", label)
        self.assertLess(label.index("John"), label.index("Colton"))
        self.assertIn("12 Oak St", label)

    def test_two_same_surname_families_are_distinguishable(self):
        a = self._morris("Morris", "John", "Colton")
        b = self._morris("Morris", "Mark", "Nash")
        self.assertNotEqual(a.selector_label(), b.selector_label())
        self.assertIn("Colton", a.selector_label())
        self.assertIn("Nash", b.selector_label())

    def test_label_falls_back_to_name_when_no_members(self):
        hh = Household.objects.create(name="Lonely Household")
        self.assertEqual(hh.selector_label(), "Lonely Household")

    def test_membership_form_options_show_member_names(self):
        from households.forms import HouseholdMembershipForm

        self._morris("Morris", "John", "Colton")
        outsider = Person.objects.create(
            first_name="Nash", last_name="Smith", birthdate=date(2015, 2, 2)
        )
        rendered = str(HouseholdMembershipForm(person=outsider)["household"])
        self.assertIn("John", rendered)
        self.assertIn("Colton", rendered)

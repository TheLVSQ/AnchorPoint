from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from households.models import Household
from people.models import Person

from .models import Group, GroupMembership


def make_staff_user(username="staffuser"):
    User = get_user_model()
    user = User.objects.create_user(username=username, password="pw")
    user.profile.role = "staff"
    user.profile.save()
    return user


class GroupDetailViewTests(TestCase):
    def setUp(self):
        self.user = make_staff_user()
        self.client.force_login(self.user)
        self.group = Group.objects.create(
            name="Sunday Volunteers",
            category="volunteer",
            location="Main Hall",
            meeting_schedule="Sundays at 8am",
        )

    def test_detail_returns_200(self):
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)

    def test_detail_shows_group_name(self):
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertContains(response, "Sunday Volunteers")

    def test_detail_shows_location_and_schedule(self):
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertContains(response, "Main Hall")
        self.assertContains(response, "Sundays at 8am")

    def test_list_links_to_detail(self):
        response = self.client.get(reverse("groups:list"))
        self.assertContains(response, reverse("groups:detail", args=[self.group.pk]))

    def test_unauthenticated_redirects(self):
        self.client.logout()
        url = reverse("groups:detail", args=[self.group.pk])
        response = self.client.get(url)
        # staff_required redirects to the app's own login page.
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)


class GroupEditViewTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("edituser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Ushers", category="volunteer")

    def test_edit_page_returns_200(self):
        response = self.client.get(reverse("groups:edit", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)

    def test_edit_page_shows_current_values(self):
        response = self.client.get(reverse("groups:edit", args=[self.group.pk]))
        self.assertContains(response, "Ushers")

    def test_edit_updates_group(self):
        response = self.client.post(reverse("groups:edit", args=[self.group.pk]), {
            "name": "Head Ushers",
            "category": "volunteer",
            "short_code": "",
            "description": "",
            "location": "",
            "meeting_schedule": "",
            "capacity": "",
            "is_active": "True",
        })
        self.assertRedirects(response, reverse("groups:detail", args=[self.group.pk]))
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Head Ushers")

    def test_edit_cancel_url_points_to_detail(self):
        response = self.client.get(reverse("groups:edit", args=[self.group.pk]))
        self.assertContains(response, reverse("groups:detail", args=[self.group.pk]))


class GroupDeleteViewTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("deleteuser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Parking Team", category="volunteer")

    def test_delete_page_returns_200(self):
        response = self.client.get(reverse("groups:delete", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Team")

    def test_delete_post_removes_group(self):
        pk = self.group.pk
        response = self.client.post(reverse("groups:delete", args=[pk]))
        self.assertRedirects(response, reverse("groups:list"))
        self.assertFalse(Group.objects.filter(pk=pk).exists())

    def test_delete_also_removes_memberships(self):
        person = Person.objects.create(first_name="Jane", last_name="Doe", phone="+15550001111")
        GroupMembership.objects.create(group=self.group, person=person)
        pk = self.group.pk
        self.client.post(reverse("groups:delete", args=[pk]))
        self.assertEqual(GroupMembership.objects.filter(group_id=pk).count(), 0)


class GroupMemberSearchTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("searchuser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Worship Team", category="volunteer")
        self.alice = Person.objects.create(first_name="Alice", last_name="Smith", phone="+15550001111")
        self.bob = Person.objects.create(first_name="Bob", last_name="Smith", phone="+15550002222")
        self.carol = Person.objects.create(first_name="Carol", last_name="Jones", phone="+15550003333")
        GroupMembership.objects.create(group=self.group, person=self.bob)

    def _search(self, q):
        return self.client.get(
            reverse("groups:member_search", args=[self.group.pk]),
            {"q": q},
        )

    def test_empty_query_returns_empty(self):
        response = self._search("")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"")

    def test_search_finds_matching_people(self):
        response = self._search("Smith")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")

    def test_search_excludes_existing_members(self):
        response = self._search("Smith")
        self.assertNotContains(response, "Bob")

    def test_search_is_case_insensitive(self):
        response = self._search("alice")
        self.assertContains(response, "Alice")

    def test_search_shows_add_family_when_household_has_non_members(self):
        household = Household.objects.create(name="Smith Family")
        household.members.add(self.alice, self.carol)
        response = self._search("Alice")
        self.assertContains(response, "Add family")

    def test_search_no_add_family_when_all_in_group(self):
        household = Household.objects.create(name="Smith Solo")
        household.members.add(self.alice)
        response = self._search("Alice")
        self.assertNotContains(response, "Add family")


class GroupMemberAddTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("adduser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Greeters", category="volunteer")
        self.alice = Person.objects.create(first_name="Alice", last_name="A", phone="+15550001111")
        self.bob = Person.objects.create(first_name="Bob", last_name="B", phone="+15550002222")
        self.carol = Person.objects.create(first_name="Carol", last_name="C", phone="+15550003333")

    def _add_person(self, person):
        return self.client.post(
            reverse("groups:member_add", args=[self.group.pk]),
            {"person_id": person.pk},
        )

    def _add_household(self, household):
        return self.client.post(
            reverse("groups:member_add", args=[self.group.pk]),
            {"household_id": household.pk},
        )

    def test_add_person_creates_membership(self):
        response = self._add_person(self.alice)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=self.alice).exists())

    def test_add_person_returns_member_list_partial(self):
        response = self._add_person(self.alice)
        self.assertContains(response, "Alice")

    def test_add_person_idempotent(self):
        self._add_person(self.alice)
        self._add_person(self.alice)
        self.assertEqual(GroupMembership.objects.filter(group=self.group, person=self.alice).count(), 1)

    def test_add_household_adds_all_non_members(self):
        household = Household.objects.create(name="A Family")
        household.members.add(self.alice, self.bob, self.carol)
        GroupMembership.objects.create(group=self.group, person=self.bob)
        response = self._add_household(household)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=self.alice).exists())
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=self.carol).exists())
        self.assertEqual(GroupMembership.objects.filter(group=self.group, person=self.bob).count(), 1)

    def test_add_household_returns_member_list_partial(self):
        household = Household.objects.create(name="B Family")
        household.members.add(self.alice, self.bob)
        response = self._add_household(household)
        self.assertContains(response, "member-list")


class GroupMemberRemoveTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("removeuser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Media Team", category="volunteer")
        self.other_group = Group.objects.create(name="Other", category="other")
        self.person = Person.objects.create(first_name="Dave", last_name="D", phone="+15550004444")
        self.membership = GroupMembership.objects.create(group=self.group, person=self.person)

    def _remove(self, group_pk, mid):
        return self.client.post(reverse("groups:member_remove", args=[group_pk, mid]))

    def test_remove_deletes_membership(self):
        response = self._remove(self.group.pk, self.membership.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GroupMembership.objects.filter(pk=self.membership.pk).exists())

    def test_remove_returns_member_list_partial(self):
        response = self._remove(self.group.pk, self.membership.pk)
        self.assertContains(response, "member-list")

    def test_remove_wrong_group_returns_404(self):
        other_person = Person.objects.create(first_name="Eve", last_name="E", phone="+15550005555")
        other_membership = GroupMembership.objects.create(group=self.other_group, person=other_person)
        response = self._remove(self.group.pk, other_membership.pk)
        self.assertEqual(response.status_code, 404)

    def test_remove_nonexistent_membership_returns_404(self):
        response = self._remove(self.group.pk, 99999)
        self.assertEqual(response.status_code, 404)

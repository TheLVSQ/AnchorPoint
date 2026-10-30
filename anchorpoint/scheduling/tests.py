from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from groups.forms import MembershipForm
from groups.models import Group, GroupMembership, Position
from people.models import Person
from people.services.merge import merge_persons

from . import availability
from .forms import BlockoutForm
from .models import Blockout

User = get_user_model()


def make_login(username, role, person=None):
    user = User.objects.create_user(username=username, password="pw-Strong-1234")
    user.profile.role = role
    user.profile.person = person
    user.profile.save()
    return user


class TeamTestCase(TestCase):
    def setUp(self):
        self.team = Group.objects.create(name="Worship", category="volunteer")
        self.keys = Position.objects.create(group=self.team, name="Keys")
        self.vocals = Position.objects.create(group=self.team, name="Vocals")
        self.alex = Person.objects.create(first_name="Alex", last_name="Rivera")
        self.sam = Person.objects.create(first_name="Sam", last_name="Lee")
        self.alex_on_team = GroupMembership.objects.create(
            group=self.team, person=self.alex, serving_weeks="3")
        self.alex_on_team.positions.add(self.keys)
        self.sam_on_team = GroupMembership.objects.create(group=self.team, person=self.sam)
        self.sam_on_team.positions.add(self.keys, self.vocals)


class WeekOfMonthTests(TestCase):
    def test_weeks(self):
        for day, week in [(1, 1), (7, 1), (8, 2), (15, 3), (21, 3), (28, 4), (29, 5), (31, 5)]:
            self.assertEqual(availability.week_of_month(date(2026, 3, day)), week, day)


class BlockoutTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(first_name="Alex", last_name="Rivera")

    def blockout(self, start, end, yearly=False):
        return Blockout(person=self.person, starts_on=start, ends_on=end, repeats_yearly=yearly)

    def test_one_day(self):
        b = self.blockout(date(2026, 11, 15), date(2026, 11, 15))
        self.assertTrue(b.covers(date(2026, 11, 15)))
        self.assertFalse(b.covers(date(2026, 11, 16)))
        self.assertFalse(b.covers(date(2027, 11, 15)))

    def test_yearly_across_new_year(self):
        b = self.blockout(date(2026, 12, 28), date(2027, 1, 3), yearly=True)
        for day in (date(2029, 12, 30), date(2030, 1, 2), date(2026, 12, 28)):
            self.assertTrue(b.covers(day), day)
        for day in (date(2029, 12, 27), date(2030, 1, 4), date(2030, 6, 1)):
            self.assertFalse(b.covers(day), day)

    def test_yearly_leap_day_falls_back_to_feb_28(self):
        b = self.blockout(date(2028, 2, 29), date(2028, 2, 29), yearly=True)
        self.assertTrue(b.covers(date(2029, 2, 28)))
        self.assertTrue(b.covers(date(2032, 2, 29)))
        self.assertFalse(b.covers(date(2029, 3, 1)))

    def test_end_before_start_is_invalid(self):
        form = BlockoutForm({"starts_on": "2026-11-15", "ends_on": "2026-11-14"},
                            person=self.person)
        self.assertFalse(form.is_valid())
        self.assertIn("ends_on", form.errors)

    def test_yearly_must_be_shorter_than_a_year(self):
        form = BlockoutForm({"starts_on": "2026-01-01", "ends_on": "2026-12-31",
                             "repeats_yearly": "on"}, person=self.person)
        self.assertFalse(form.is_valid())

    def test_blank_end_means_one_day(self):
        form = BlockoutForm({"starts_on": "2026-11-15", "ends_on": ""}, person=self.person)
        self.assertTrue(form.is_valid(), form.errors)
        b = form.save()
        self.assertEqual((b.starts_on, b.ends_on), (date(2026, 11, 15), date(2026, 11, 15)))

    def test_past_one_off_is_not_current_but_yearly_is(self):
        past = self.blockout(date(2020, 1, 1), date(2020, 1, 2))
        yearly = self.blockout(date(2020, 1, 1), date(2020, 1, 2), yearly=True)
        self.assertFalse(past.is_current(date(2026, 1, 1)))
        self.assertTrue(yearly.is_current(date(2026, 1, 1)))


class AvailabilityTests(TeamTestCase):
    THIRD_SUNDAY = date(2026, 11, 15)
    FIRST_SUNDAY = date(2026, 11, 1)
    FIFTH_SUNDAY = date(2026, 11, 29)

    def names(self, day, position=None):
        qs = availability.available(self.team.memberships.all(), day, position)
        return sorted(m.person.first_name for m in qs)

    def test_pattern_limits_weeks(self):
        self.assertEqual(self.names(self.THIRD_SUNDAY), ["Alex", "Sam"])
        self.assertEqual(self.names(self.FIRST_SUNDAY), ["Sam"])
        self.assertEqual(self.names(self.FIFTH_SUNDAY), ["Sam"])

    def test_blockout_rules_out(self):
        Blockout.objects.create(person=self.sam, starts_on=date(2026, 11, 14),
                                ends_on=date(2026, 11, 16), note="Away")
        self.assertEqual(self.names(self.THIRD_SUNDAY), ["Alex"])
        self.assertEqual(availability.reasons_unavailable(self.sam_on_team, self.THIRD_SUNDAY),
                         ["Blocked out: Away"])

    def test_yearly_blockout_rules_out_in_a_later_year(self):
        Blockout.objects.create(person=self.alex, starts_on=date(2025, 11, 15),
                                ends_on=date(2025, 11, 15), repeats_yearly=True)
        self.assertEqual(self.names(self.THIRD_SUNDAY), ["Sam"])

    def test_position(self):
        self.assertEqual(self.names(self.THIRD_SUNDAY, self.vocals), ["Sam"])

    def test_reasons_name_the_pattern(self):
        reasons = availability.reasons_unavailable(self.alex_on_team, self.FIRST_SUNDAY)
        self.assertEqual(reasons, ["Serves 3rd only on Worship, not the 1st week"])
        self.assertEqual(availability.reasons_unavailable(self.alex_on_team, self.THIRD_SUNDAY), [])

    def test_weeks_label(self):
        for weeks, label in [("12345", "Every week"), ("3", "3rd only"),
                             ("13", "1st and 3rd"), ("124", "1st, 2nd and 4th")]:
            self.assertEqual(GroupMembership(serving_weeks=weeks).serving_weeks_label, label)


class MergeTests(TeamTestCase):
    def test_blockouts_move_and_shared_team_combines(self):
        dupe = Person.objects.create(first_name="Alex", last_name="Rivera")
        on_team = GroupMembership.objects.create(group=self.team, person=dupe, role="leader")
        on_team.positions.add(self.vocals)
        Blockout.objects.create(person=dupe, starts_on=date(2026, 12, 1), ends_on=date(2026, 12, 2))
        merge_persons(self.alex, dupe)
        kept = GroupMembership.objects.get(group=self.team, person=self.alex)
        self.assertEqual(set(kept.positions.all()), {self.keys, self.vocals})
        self.assertEqual((kept.serving_weeks, kept.role), ("3", "leader"))
        self.assertEqual(self.alex.blockouts.count(), 1)

    def test_default_weeks_take_the_duplicates_pattern(self):
        dupe = Person.objects.create(first_name="Sam", last_name="Lee")
        GroupMembership.objects.create(group=self.team, person=dupe, serving_weeks="1")
        merge_persons(self.sam, dupe)
        self.assertEqual(GroupMembership.objects.get(person=self.sam).serving_weeks, "1")


class StaffTeamPageTests(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(make_login("staff", UserProfile.Role.STAFF))

    def test_positions_card_and_member_details(self):
        resp = self.client.get(reverse("groups:detail", args=[self.team.pk]))
        self.assertContains(resp, "Positions")
        self.assertContains(resp, "Keys · 3rd only")

    def test_no_positions_on_checkin_classrooms(self):
        room = Group.objects.create(name="Room 3", category="checkin")
        resp = self.client.get(reverse("groups:detail", args=[room.pk]))
        self.assertNotContains(resp, "Positions")
        form = MembershipForm(instance=GroupMembership(group=room, person=self.sam))
        self.assertEqual(list(form.fields), ["role"])

    def test_add_and_remove_position(self):
        url = reverse("groups:position_add", args=[self.team.pk])
        self.client.post(url, {"name": "Sound"})
        self.assertTrue(self.team.positions.filter(name="Sound").exists())
        resp = self.client.post(url, {"name": "keys"})
        self.assertContains(resp, "already has keys")
        sound = self.team.positions.get(name="Sound")
        self.client.post(reverse("groups:position_remove", args=[self.team.pk, sound.pk]))
        self.assertFalse(self.team.positions.filter(name="Sound").exists())

    def test_edit_member(self):
        url = reverse("groups:member_edit", args=[self.team.pk, self.alex_on_team.pk])
        resp = self.client.post(url, {"role": "member", "positions": [self.vocals.pk],
                                      "serving_weeks": ["1", "3"]})
        self.assertRedirects(resp, reverse("groups:detail", args=[self.team.pk]))
        self.alex_on_team.refresh_from_db()
        self.assertEqual(self.alex_on_team.serving_weeks, "13")
        self.assertEqual(list(self.alex_on_team.positions.all()), [self.vocals])

    def test_edit_member_rejects_other_teams_positions(self):
        other = Position.objects.create(
            group=Group.objects.create(name="Tech", category="volunteer"), name="Sound")
        url = reverse("groups:member_edit", args=[self.team.pk, self.alex_on_team.pk])
        resp = self.client.post(url, {"role": "member", "positions": [other.pk],
                                      "serving_weeks": ["3"]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(self.alex_on_team.positions.all()), [self.keys])

    def test_edit_member_needs_a_week(self):
        url = reverse("groups:member_edit", args=[self.team.pk, self.alex_on_team.pk])
        resp = self.client.post(url, {"role": "member", "positions": [self.keys.pk]})
        self.assertContains(resp, "Tick at least one week")

    def test_person_page_serving_and_blockouts(self):
        add = reverse("scheduling:person_blockout_add", args=[self.alex.pk])
        resp = self.client.post(add, {"starts_on": "2026-12-24", "ends_on": "2026-12-26",
                                      "note": "Family trip"})
        self.assertRedirects(resp, reverse("people_detail", args=[self.alex.pk]))
        page = self.client.get(reverse("people_detail", args=[self.alex.pk]))
        self.assertContains(page, "Worship")
        self.assertContains(page, "Keys · 3rd only")
        self.assertContains(page, "Family trip")
        blockout = self.alex.blockouts.get()
        self.client.post(reverse("scheduling:person_blockout_delete",
                                 args=[self.alex.pk, blockout.pk]))
        self.assertFalse(self.alex.blockouts.exists())


class MyServingTests(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_login("alex", UserProfile.Role.TEAM_MEMBER, person=self.alex)
        self.client.force_login(self.user)

    def test_shows_own_teams_and_sidebar_link(self):
        Group.objects.create(name="Room 3", category="checkin").memberships.create(person=self.alex)
        resp = self.client.get(reverse("scheduling:my_serving"))
        self.assertContains(resp, "Worship")
        self.assertContains(resp, "Keys")
        self.assertNotContains(resp, "Room 3")
        self.assertContains(resp, 'href="/serving/" aria-current="page"')

    def test_set_own_weeks(self):
        url = reverse("scheduling:my_serving_weeks", args=[self.alex_on_team.pk])
        prefix = f"m{self.alex_on_team.pk}-serving_weeks"
        self.client.post(url, {prefix: ["1", "3"]})
        self.alex_on_team.refresh_from_db()
        self.assertEqual(self.alex_on_team.serving_weeks, "13")
        resp = self.client.post(url, {})
        self.assertContains(resp, "Tick at least one week")

    def test_cannot_touch_someone_elses_team_or_positions(self):
        url = reverse("scheduling:my_serving_weeks", args=[self.sam_on_team.pk])
        self.assertEqual(self.client.post(url, {f"m{self.sam_on_team.pk}-serving_weeks": ["1"]})
                         .status_code, 404)
        own = reverse("scheduling:my_serving_weeks", args=[self.alex_on_team.pk])
        self.client.post(own, {f"m{self.alex_on_team.pk}-serving_weeks": ["3"],
                               "positions": [self.vocals.pk]})
        self.assertEqual(list(self.alex_on_team.positions.all()), [self.keys])

    def test_own_blockouts(self):
        self.client.post(reverse("scheduling:my_blockout_add"),
                         {"starts_on": "2026-07-01", "ends_on": "2026-07-10", "repeats_yearly": "on"})
        mine = self.alex.blockouts.get()
        self.assertTrue(mine.repeats_yearly)
        theirs = Blockout.objects.create(person=self.sam, starts_on=date(2026, 8, 1),
                                         ends_on=date(2026, 8, 1))
        resp = self.client.post(reverse("scheduling:my_blockout_delete", args=[theirs.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Blockout.objects.filter(pk=theirs.pk).exists())
        self.client.post(reverse("scheduling:my_blockout_delete", args=[mine.pk]))
        self.assertFalse(self.alex.blockouts.exists())

    def test_login_without_a_person(self):
        self.client.force_login(make_login("admin2", UserProfile.Role.ADMIN))
        resp = self.client.get(reverse("scheduling:my_serving"))
        self.assertContains(resp, "isn't linked to a person")
        self.assertNotContains(resp, 'href="/serving/"')
        self.assertEqual(self.client.post(reverse("scheduling:my_blockout_add"),
                                          {"starts_on": "2026-07-01"}).status_code, 404)

    def test_staff_pages_refused(self):
        refused = [
            reverse("groups:member_edit", args=[self.team.pk, self.alex_on_team.pk]),
            reverse("groups:position_add", args=[self.team.pk]),
            reverse("groups:position_remove", args=[self.team.pk, self.keys.pk]),
            reverse("scheduling:person_blockout_add", args=[self.sam.pk]),
        ]
        for url in refused:
            with self.subTest(url):
                self.assertIn(self.client.post(url, {"name": "X", "starts_on": "2026-07-01"})
                              .status_code, (302, 403))
        self.assertTrue(self.team.positions.filter(pk=self.keys.pk).exists())
        self.assertFalse(Blockout.objects.exists())

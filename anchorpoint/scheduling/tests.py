from datetime import date, datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile
from groups.forms import MembershipForm
from groups.models import Group, GroupMembership, Position
from messaging.adapters import FakeAdapter
from messaging.models import Communication, Delivery
from messaging.services import unsubscribe_url
from people.models import Person
from people.services.merge import merge_persons

from . import availability, schedule
from . import requests as schedule_requests
from .forms import BlockoutForm, ServiceTypeForm
from .models import Assignment, Blockout, Plan, ServiceType, ServiceTypeNeed

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


# ---------------------------------------------------------------------------
# 1b: service types, plans, the schedule grid
# ---------------------------------------------------------------------------

class PlanTestCase(TeamTestCase):
    THIRD_SUNDAY = date(2026, 11, 15)
    FIRST_SUNDAY = date(2026, 11, 1)

    def setUp(self):
        super().setUp()
        self.sunday = ServiceType.objects.create(name="Sunday Morning", weekday=6,
                                                 default_time=time(10, 30))
        ServiceTypeNeed.objects.create(service_type=self.sunday, position=self.keys, count=1)
        ServiceTypeNeed.objects.create(service_type=self.sunday, position=self.vocals, count=2)
        self.plan = Plan.objects.create(service_type=self.sunday, date=self.THIRD_SUNDAY)


class GeneratePlansTests(TestCase):
    def test_one_plan_per_weekday_and_rerun_adds_nothing(self):
        sunday = ServiceType.objects.create(name="Sunday Morning", weekday=6,
                                            default_time=time(10, 30))
        added = schedule.generate_plans(sunday, date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(added, 5)
        self.assertEqual([p.date.day for p in sunday.plans.all()], [1, 8, 15, 22, 29])
        self.assertEqual(sunday.plans.first().time, time(10, 30))
        self.assertEqual(schedule.generate_plans(sunday, date(2026, 11, 1), date(2026, 12, 6)), 1)

    def test_no_weekday_means_every_day(self):
        vbs = ServiceType.objects.create(name="VBS 2027", weekday=None)
        self.assertEqual(schedule.generate_plans(vbs, date(2027, 6, 14), date(2027, 6, 18)), 5)


class AlreadyServingTests(PlanTestCase):
    def test_another_position_that_day_is_a_reason(self):
        Assignment.objects.create(plan=self.plan, position=self.vocals, person=self.sam)
        self.assertEqual(availability.reasons_unavailable(self.sam_on_team, self.THIRD_SUNDAY),
                         ["Already serving: Vocals on Sunday Morning"])

    def test_declined_doesnt_count(self):
        Assignment.objects.create(plan=self.plan, position=self.vocals, person=self.sam,
                                  status=Assignment.Status.DECLINED)
        self.assertEqual(availability.reasons_unavailable(self.sam_on_team, self.THIRD_SUNDAY), [])

    def test_other_service_type_same_day_counts(self):
        evening = ServiceType.objects.create(name="Evening", weekday=6)
        other = Plan.objects.create(service_type=evening, date=self.THIRD_SUNDAY)
        Assignment.objects.create(plan=other, position=self.keys, person=self.sam)
        self.assertEqual(availability.reasons_unavailable(self.sam_on_team, self.THIRD_SUNDAY),
                         ["Already serving: Keys on Evening"])


class GridTests(PlanTestCase):
    def cell(self, grid, position, plan_index=0):
        for team_rows in grid:
            for row in team_rows.rows:
                if row.position == position:
                    return row.cells[plan_index]

    def test_rows_counts_and_warnings(self):
        Assignment.objects.create(plan=self.plan, position=self.keys, person=self.sam)
        Assignment.objects.create(plan=self.plan, position=self.vocals, person=self.sam)
        # Blocked out after being scheduled: the grid still has to show it.
        Blockout.objects.create(person=self.sam, starts_on=self.THIRD_SUNDAY,
                                ends_on=self.THIRD_SUNDAY, note="Away")
        grid = schedule.build_grid(self.sunday, [self.plan])
        self.assertEqual([t.team for t in grid], [self.team])
        self.assertEqual([r.position for r in grid[0].rows], [self.keys, self.vocals])
        keys = self.cell(grid, self.keys)
        self.assertEqual((keys.filled, keys.needed, keys.short), (1, 1, 0))
        self.assertEqual(keys.slots[0].warnings,
                         ["Blocked out: Away", "Already serving: Vocals on Sunday Morning"])
        self.assertEqual(self.cell(grid, self.vocals).short, 1)

    def test_pattern_warning_and_declined_leaves_the_slot_open_without_warnings(self):
        first = Plan.objects.create(service_type=self.sunday, date=self.FIRST_SUNDAY)
        Assignment.objects.create(plan=first, position=self.keys, person=self.alex,
                                  status=Assignment.Status.DECLINED)
        Assignment.objects.create(plan=first, position=self.vocals, person=self.alex)
        grid = schedule.build_grid(self.sunday, [first])
        keys = self.cell(grid, self.keys)
        self.assertEqual(keys.short, 1)
        self.assertEqual(keys.slots[0].warnings, [])  # they said no: nothing to warn about
        self.assertEqual(self.cell(grid, self.vocals).slots[0].warnings,
                         ["Serves 3rd only on Worship, not the 1st week"])

    def test_someone_off_the_team_and_a_position_no_longer_needed_still_show(self):
        sound = Position.objects.create(group=self.team, name="Sound")
        outsider = Person.objects.create(first_name="Pat", last_name="Moss")
        Assignment.objects.create(plan=self.plan, position=sound, person=outsider)
        cell = self.cell(schedule.build_grid(self.sunday, [self.plan]), sound)
        self.assertEqual(cell.needed, 0)
        self.assertEqual(cell.slots[0].warnings, ["Not on Worship"])

    def test_team_filter(self):
        kids = Group.objects.create(name="Kids Team", category="volunteer")
        teacher = Position.objects.create(group=kids, name="Teacher")
        ServiceTypeNeed.objects.create(service_type=self.sunday, position=teacher)
        self.assertEqual([t.team for t in schedule.build_grid(self.sunday, [self.plan])],
                         [kids, self.team])
        self.assertEqual([t.team for t in schedule.build_grid(self.sunday, [self.plan], team=kids)],
                         [kids])

    def test_query_count_doesnt_grow_with_the_grid(self):
        plans = [self.plan] + [Plan.objects.create(service_type=self.sunday,
                                                   date=self.THIRD_SUNDAY + timedelta(weeks=w))
                               for w in range(1, 6)]
        for plan in plans:
            for person in (self.alex, self.sam):
                Assignment.objects.create(plan=plan, position=self.vocals, person=person)
        with self.assertNumQueries(5):
            schedule.build_grid(self.sunday, plans)


class CandidateTests(PlanTestCase):
    def test_fits_available_first_others_and_people_in_the_cell_left_out(self):
        pat = Person.objects.create(first_name="Pat", last_name="Moss")
        GroupMembership.objects.create(group=self.team, person=pat)  # no positions yet
        first = Plan.objects.create(service_type=self.sunday, date=self.FIRST_SUNDAY)
        fits, others = schedule.candidates(first, self.keys)
        self.assertEqual([c.membership.person for c in fits], [self.sam, self.alex])
        self.assertEqual(fits[1].reasons, ["Serves 3rd only on Worship, not the 1st week"])
        self.assertEqual([c.membership.person for c in others], [pat])
        Assignment.objects.create(plan=first, position=self.keys, person=self.sam)
        fits, _ = schedule.candidates(first, self.keys)
        self.assertEqual([c.membership.person for c in fits], [self.alex])


class ScheduleViewTests(PlanTestCase):
    HX = {"HTTP_HX_REQUEST": "true"}

    def setUp(self):
        super().setUp()
        self.staff = make_login("staff", UserProfile.Role.STAFF)
        self.client.force_login(self.staff)

    def test_create_service_type_with_needs(self):
        resp = self.client.post(reverse("scheduling:service_type_create"), {
            "name": "VBS 2027", "weekday": "", "default_time": "09:00", "is_active": "on",
            f"need_{self.keys.pk}": "2", f"need_{self.vocals.pk}": "0",
        })
        vbs = ServiceType.objects.get(name="VBS 2027")
        self.assertRedirects(resp, reverse("scheduling:schedule", args=[vbs.pk]))
        self.assertIsNone(vbs.weekday)
        self.assertEqual(list(vbs.needs.values_list("position__name", "count")), [("Keys", 2)])

    def test_editing_a_need_to_zero_removes_it(self):
        form = ServiceTypeForm({"name": "Sunday Morning", "weekday": "6", "is_active": "on",
                                f"need_{self.keys.pk}": "1", f"need_{self.vocals.pk}": "0"},
                               instance=self.sunday)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual([n.position for n in self.sunday.needs.all()], [self.keys])

    def test_add_dates_and_grid(self):
        resp = self.client.post(reverse("scheduling:plans_add", args=[self.sunday.pk]),
                                {"starts_on": "2026-11-01", "ends_on": "2026-11-30"})
        self.assertRedirects(resp, reverse("scheduling:schedule", args=[self.sunday.pk])
                             + "?start=2026-11-01")
        self.assertEqual(self.sunday.plans.count(), 5)
        resp = self.client.get(reverse("scheduling:schedule", args=[self.sunday.pk])
                               + "?start=2026-11-01")
        self.assertContains(resp, "Sun, Nov 15")
        self.assertContains(resp, "Needs 2")

    def test_list_page(self):
        resp = self.client.get(reverse("scheduling:service_type_list"))
        self.assertContains(resp, "Sunday Morning")

    def test_pick_assign_remove(self):
        pick = self.client.get(reverse("scheduling:cell_pick", args=[self.plan.pk, self.keys.pk]),
                               **self.HX)
        self.assertContains(pick, "Alex Rivera")
        self.assertContains(pick, "Sam Lee")
        url = reverse("scheduling:cell_assign", args=[self.plan.pk, self.keys.pk])
        resp = self.client.post(url, {"person": self.sam.pk}, **self.HX)
        self.assertContains(resp, "Sam Lee")
        self.assertContains(resp, "1 of 1")
        assignment = Assignment.objects.get()
        self.assertEqual((assignment.person, assignment.created_by), (self.sam, self.staff))
        resp = self.client.post(reverse("scheduling:assignment_remove", args=[assignment.pk]),
                                **self.HX)
        self.assertContains(resp, "0 of 1")
        self.assertFalse(Assignment.objects.exists())

    def test_assign_refuses_someone_not_on_the_team(self):
        outsider = Person.objects.create(first_name="Pat", last_name="Moss")
        resp = self.client.post(
            reverse("scheduling:cell_assign", args=[self.plan.pk, self.keys.pk]),
            {"person": outsider.pk}, **self.HX)
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Assignment.objects.exists())

    def test_without_htmx_assign_goes_to_the_plan_page(self):
        resp = self.client.post(
            reverse("scheduling:cell_assign", args=[self.plan.pk, self.keys.pk]),
            {"person": self.sam.pk})
        self.assertRedirects(resp, reverse("scheduling:plan_detail", args=[self.plan.pk]))

    def test_plan_page_edit_and_delete(self):
        Assignment.objects.create(plan=self.plan, position=self.keys, person=self.sam)
        url = reverse("scheduling:plan_detail", args=[self.plan.pk])
        self.assertContains(self.client.get(url), "Sam Lee")
        self.client.post(url, {"title": "Thanksgiving", "time": "10:30", "notes": ""})
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.title, "Thanksgiving")
        self.client.post(reverse("scheduling:plan_delete", args=[self.plan.pk]))
        self.assertFalse(Plan.objects.exists())
        self.assertFalse(Assignment.objects.exists())

    def test_position_on_a_schedule_cant_be_removed(self):
        Assignment.objects.create(plan=self.plan, position=self.keys, person=self.sam)
        resp = self.client.post(reverse("groups:position_remove",
                                        args=[self.team.pk, self.keys.pk]), follow=True)
        self.assertContains(resp, "Keys is on 1 schedule.")
        self.assertTrue(Position.objects.filter(pk=self.keys.pk).exists())

    def test_team_on_a_schedule_cant_be_deleted(self):
        Assignment.objects.create(plan=self.plan, position=self.keys, person=self.sam)
        resp = self.client.post(reverse("groups:delete", args=[self.team.pk]), follow=True)
        self.assertContains(resp, "Worship is on 1 schedule.")
        self.assertTrue(Group.objects.filter(pk=self.team.pk).exists())
        self.plan.delete()
        self.client.post(reverse("groups:delete", args=[self.team.pk]))
        self.assertFalse(Group.objects.filter(pk=self.team.pk).exists())

    def test_person_page_lists_upcoming(self):
        upcoming = Plan.objects.create(service_type=self.sunday,
                                       date=timezone.localdate() + timedelta(days=3))
        Assignment.objects.create(plan=upcoming, position=self.keys, person=self.sam)
        resp = self.client.get(reverse("people_detail", args=[self.sam.pk]))
        self.assertContains(resp, "Scheduled")
        self.assertContains(resp, upcoming.date.strftime("%b %-d"))

    def test_team_member_is_refused(self):
        self.client.force_login(make_login("alex", UserProfile.Role.TEAM_MEMBER, person=self.alex))
        for url in (reverse("scheduling:schedule", args=[self.sunday.pk]),
                    reverse("scheduling:cell_pick", args=[self.plan.pk, self.keys.pk])):
            self.assertIn(self.client.get(url).status_code, (302, 403))
        resp = self.client.post(reverse("scheduling:cell_assign",
                                        args=[self.plan.pk, self.keys.pk]), {"person": self.alex.pk})
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(Assignment.objects.exists())


class MergeAssignmentTests(PlanTestCase):
    def test_both_records_in_the_same_slot_collapse_to_one(self):
        dupe = Person.objects.create(first_name="Sam", last_name="Lee")
        Assignment.objects.create(plan=self.plan, position=self.keys, person=self.sam)
        Assignment.objects.create(plan=self.plan, position=self.keys, person=dupe)
        Assignment.objects.create(plan=self.plan, position=self.vocals, person=dupe)
        merge_persons(self.sam, dupe)
        self.assertEqual(sorted(a.position.name for a in self.sam.assignments.all()),
                         ["Keys", "Vocals"])


# ---------------------------------------------------------------------------
# 1c: requests, answers, reminders
# ---------------------------------------------------------------------------

BASE = "https://serve.example.test"


@override_settings(SITE_BASE_URL=BASE, DEFAULT_FROM_EMAIL="church@example.test")
class RequestTestCase(PlanTestCase):
    def setUp(self):
        super().setUp()
        FakeAdapter.reset()
        self.addCleanup(FakeAdapter.reset)
        self.staff = make_login("staff", UserProfile.Role.STAFF)
        self.staff.email = "leader@example.test"
        self.staff.save()
        self.sam.email = "sam@example.test"
        self.sam.save()
        self.today = timezone.localdate()
        self.soon = Plan.objects.create(service_type=self.sunday,
                                        date=self.today + timedelta(days=10))

    def schedule(self, person, plan=None, position=None, **kw):
        return Assignment.objects.create(plan=plan or self.soon, position=position or self.keys,
                                         person=person, created_by=self.staff, **kw)

    def emails_to(self, person):
        return Delivery.objects.filter(person=person, communication__channel="email")


class QueueAndSendTests(RequestTestCase):
    def test_drafts_queue_then_cron_emails_each_person_once(self):
        self.schedule(self.sam)
        self.schedule(self.sam, position=self.vocals)
        self.schedule(self.alex)  # no email address
        people, unreachable = schedule_requests.queue_requests(self.sunday)
        self.assertEqual(people, [self.alex, self.sam])
        self.assertEqual(unreachable, [self.alex])
        self.assertFalse(Assignment.objects.filter(requested_at__isnull=True).exists())

        self.assertEqual(schedule_requests.send_due(), (1, 0))
        comm = self.emails_to(self.sam).get().communication
        self.assertEqual(comm.subject, "Can you serve? 2 dates")
        self.assertIn("Keys (Worship)", comm.body)
        self.assertIn(f"{BASE}/serving/respond/", comm.body)
        self.assertFalse(Assignment.objects.filter(request_sent_at__isnull=True).exists())
        self.assertEqual(schedule_requests.send_due(), (0, 0))  # never twice

    def test_past_drafts_and_other_service_types_arent_queued(self):
        past = Plan.objects.create(service_type=self.sunday, date=self.today - timedelta(days=7))
        old = self.schedule(self.sam, plan=past)
        evening = ServiceType.objects.create(name="Evening", weekday=6)
        other = self.schedule(self.sam, plan=Plan.objects.create(service_type=evening,
                                                                 date=self.soon.date))
        schedule_requests.queue_requests(self.sunday)
        old.refresh_from_db(), other.refresh_from_db()
        self.assertIsNone(old.requested_at)
        self.assertIsNone(other.requested_at)

    def test_team_filter_sends_only_that_team(self):
        kids = Group.objects.create(name="Kids Team", category="volunteer")
        teacher = Position.objects.create(group=kids, name="Teacher")
        ServiceTypeNeed.objects.create(service_type=self.sunday, position=teacher)
        mine = self.schedule(self.sam)
        theirs = self.schedule(self.alex, position=teacher)
        self.client.force_login(self.staff)
        grid = self.client.get(reverse("scheduling:schedule", args=[self.sunday.pk])
                               + f"?team={self.team.pk}")
        self.assertContains(grid, "Send Worship requests (1)")
        self.client.post(reverse("scheduling:send_requests", args=[self.sunday.pk]),
                         {"team": self.team.pk})
        mine.refresh_from_db(), theirs.refresh_from_db()
        self.assertIsNotNone(mine.requested_at)
        self.assertIsNone(theirs.requested_at)

    def test_answered_before_the_cron_gets_no_request_email(self):
        a = self.schedule(self.sam, requested_at=timezone.now())
        schedule_requests.respond(a, accept=True)
        self.assertEqual(schedule_requests.send_due(), (0, 0))
        self.assertFalse(self.emails_to(self.sam).exists())

    def test_refuses_without_email_or_site_address(self):
        self.schedule(self.sam)
        FakeAdapter.is_ready = False
        with self.assertRaises(schedule_requests.NotReady):
            schedule_requests.queue_requests(self.sunday)
        FakeAdapter.is_ready = True
        with override_settings(SITE_BASE_URL="", CSRF_TRUSTED_ORIGINS=[]):
            with self.assertRaises(schedule_requests.NotReady):
                schedule_requests.queue_requests(self.sunday)
        self.assertTrue(Assignment.objects.get().is_draft)

    def test_grid_flags_not_sent_and_no_email(self):
        self.schedule(self.alex)
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("scheduling:schedule", args=[self.sunday.pk]))
        self.assertContains(resp, "Not sent")
        self.assertContains(resp, "No email")
        self.assertContains(resp, "Send requests (1)")

    def test_send_button(self):
        self.schedule(self.sam)
        self.client.force_login(self.staff)
        resp = self.client.post(reverse("scheduling:send_requests", args=[self.sunday.pk]),
                                follow=True)
        self.assertContains(resp, "Sending requests to 1 person within a minute.")
        self.assertNotContains(resp, "Send requests (")


class EmailSubjectTests(RequestTestCase):
    @override_settings(OUTBOUND_ADAPTERS={"email": "messaging.adapters.Email"})
    def test_real_email_has_subject_and_clickable_link(self):
        from messaging import outbound
        outbound.send_transactional(Communication.Channel.EMAIL, people=[self.sam],
                                    subject="Can you serve?", title="Schedule request",
                                    body=f"Answer here: {BASE}/serving/respond/x/")
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Can you serve?")
        html = msg.alternatives[0][0]
        self.assertIn(f'<a href="{BASE}/serving/respond/x/"', html)


class RespondTests(RequestTestCase):
    def setUp(self):
        super().setUp()
        self.assignment = self.schedule(self.sam, requested_at=timezone.now())
        self.url = schedule_requests.respond_url(self.sam, BASE).removeprefix(BASE)

    def test_link_shows_only_their_requested_dates(self):
        draft = Plan.objects.create(service_type=self.sunday, date=self.today + timedelta(days=17))
        self.schedule(self.sam, plan=draft)  # a staff draft: not shown
        self.schedule(self.alex, requested_at=timezone.now(), position=self.vocals)
        resp = self.client.get(self.url)
        self.assertContains(resp, "Hi Sam")
        self.assertContains(resp, self.soon.date.strftime("%b %-d"))
        self.assertNotContains(resp, draft.date.strftime("%b %-d"))
        self.assertNotContains(resp, "Alex")

    def test_decline_with_reason_tells_the_scheduler(self):
        resp = self.client.post(self.url, {"assignment": self.assignment.pk, "answer": "decline",
                                           "reason": "Out of town"}, follow=True)
        self.assertContains(resp, "let the scheduler know")
        self.assignment.refresh_from_db()
        self.assertEqual((self.assignment.status, self.assignment.decline_reason),
                         ("declined", "Out of town"))
        self.assertEqual(mail.outbox[0].to, ["leader@example.test"])
        self.assertIn("Out of town", mail.outbox[0].body)

    def test_accept(self):
        self.client.post(self.url, {"assignment": self.assignment.pk, "answer": "accept"})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "accepted")
        self.assertEqual(mail.outbox, [])

    def test_someone_elses_assignment_is_404(self):
        theirs = self.schedule(self.alex, requested_at=timezone.now())
        resp = self.client.post(self.url, {"assignment": theirs.pk, "answer": "decline"})
        self.assertEqual(resp.status_code, 404)

    def test_unsubscribe_and_tampered_tokens_dont_work(self):
        token = unsubscribe_url(self.sam, BASE).rstrip("/").rsplit("/", 1)[1]
        self.assertEqual(self.client.get(reverse("scheduling:respond", args=[token])).status_code,
                         404)
        self.assertEqual(self.client.get(self.url.replace(":", "x", 1)).status_code, 404)

    def test_expired_link(self):
        token = self.url.rstrip("/").rsplit("/", 1)[1]
        later = timezone.now() + timedelta(days=schedule_requests.RESPOND_LINK_DAYS + 1)
        with mock.patch("time.time", return_value=later.timestamp()):
            self.assertIsNone(schedule_requests.person_from_token(token))
        self.assertEqual(schedule_requests.person_from_token(token), self.sam)

    def test_past_dates_cant_be_answered(self):
        self.soon.date = self.today - timedelta(days=1)
        self.soon.save()
        with self.assertRaises(schedule_requests.TooLate):
            schedule_requests.respond(self.assignment, accept=True)

    def test_my_serving_answer_and_dashboard_prompt(self):
        user = make_login("sam", UserProfile.Role.TEAM_MEMBER, person=self.sam)
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("dashboard")), "date to answer")
        self.client.post(reverse("scheduling:my_answer"),
                         {"assignment": self.assignment.pk, "answer": "accept"})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "accepted")
        resp = self.client.get(reverse("scheduling:my_serving"))
        self.assertContains(resp, "Serving")
        self.assertNotContains(self.client.get(reverse("dashboard")), "date to answer")


class ReminderTests(RequestTestCase):
    def at(self, days_ahead_of_plan, hour):
        day = self.soon.date - timedelta(days=days_ahead_of_plan)
        return timezone.make_aware(datetime.combine(day, time(hour, 0)))

    def test_one_reminder_in_the_window_in_the_morning(self):
        sent = timezone.now() - timedelta(days=20)
        a = self.schedule(self.sam, requested_at=sent, request_sent_at=sent,
                          status=Assignment.Status.ACCEPTED)
        self.assertEqual(schedule_requests.send_due(now=self.at(5, 9)), (0, 0))  # too early
        self.assertEqual(schedule_requests.send_due(now=self.at(2, 6)), (0, 0))  # overnight
        self.assertEqual(schedule_requests.send_due(now=self.at(2, 9)), (0, 1))
        self.assertEqual(schedule_requests.send_due(now=self.at(1, 9)), (0, 0))  # only once
        comm = self.emails_to(self.sam).get().communication
        self.assertTrue(comm.subject.startswith("Reminder: you're serving"))
        self.assertIn("Can't make it after all?", comm.body)
        a.refresh_from_db()
        self.assertIsNotNone(a.reminded_at)

    def test_answered_before_the_request_email_still_gets_a_reminder(self):
        sent = timezone.now() - timedelta(days=20)
        self.schedule(self.sam, requested_at=sent, status=Assignment.Status.ACCEPTED)
        self.assertEqual(schedule_requests.send_due(now=self.at(2, 9)), (0, 1))

    def test_no_reminder_for_declined_or_drafts(self):
        sent = timezone.now() - timedelta(days=20)
        self.schedule(self.sam, requested_at=sent, request_sent_at=sent,
                      status=Assignment.Status.DECLINED)
        self.schedule(self.sam, position=self.vocals)  # draft
        self.assertEqual(schedule_requests.send_due(now=self.at(2, 9)), (0, 0))

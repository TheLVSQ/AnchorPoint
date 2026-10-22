"""CheckIn lifecycle: the four states, the filters and the transitions (GLOSSARY.md)."""
from datetime import time

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession
from checkin.tests.test_preprint import PreprintFixture
from core.models import UserProfile
from people.models import Person

State = CheckIn.State


class LifecycleFixture(TestCase):
    def setUp(self):
        self.session = CheckInSession.objects.create(
            name="Sunday AM", date=timezone.localdate(),
            checkin_opens=time(0, 0), checkin_closes=time(23, 50),
            event_starts=time(0, 5), event_ends=time(23, 55), is_active=True,
        )
        self.staff = get_user_model().objects.create_user(username="staff", password="pw")
        self.rows = {
            state: self._make(state, i) for i, state in enumerate(State)
        }

    def _make(self, state, i):
        person = Person.objects.create(first_name=f"Kid{i}", last_name=state.label)
        fields = {
            State.EXPECTED: {},
            State.NO_SHOW: {"no_show": True},
            State.PRESENT: {"arrived_at": timezone.now()},
            State.CHECKED_OUT: {"arrived_at": timezone.now(), "checked_out_at": timezone.now()},
        }[state]
        return CheckIn.objects.create(
            session=self.session, person=person, security_code=f"C{i:03d}", **fields
        )

    def reload(self, state):
        return CheckIn.objects.get(pk=self.rows[state].pk)


class StateTests(LifecycleFixture):
    def test_each_row_has_exactly_its_state(self):
        for state, row in self.rows.items():
            self.assertEqual(row.state, state)
            self.assertEqual(row.get_state_display(), state.label)

    def test_one_filter_per_state(self):
        qs = self.session.checkins
        filters = {State.EXPECTED: qs.expected, State.NO_SHOW: qs.no_show,
                   State.PRESENT: qs.present, State.CHECKED_OUT: qs.checked_out}
        for state, f in filters.items():
            self.assertEqual(list(f()), [self.rows[state]], state)

    def test_filters_agree_with_state_property(self):
        for row in self.session.checkins.all():
            self.assertIn(row, {
                State.EXPECTED: self.session.checkins.expected(),
                State.NO_SHOW: self.session.checkins.no_show(),
                State.PRESENT: self.session.checkins.present(),
                State.CHECKED_OUT: self.session.checkins.checked_out(),
            }[row.state])

    def test_active_and_attended(self):
        self.assertEqual(
            set(self.session.checkins.active()),
            {self.rows[State.EXPECTED], self.rows[State.NO_SHOW], self.rows[State.PRESENT]},
        )
        self.assertEqual(
            set(self.session.checkins.attended()),
            {self.rows[State.PRESENT], self.rows[State.CHECKED_OUT]},
        )

    def test_state_counts_one_query(self):
        with self.assertNumQueries(1):
            counts = self.session.checkins.state_counts()
        self.assertEqual(counts, {state: 1 for state in State})

    def test_state_q_for_annotations(self):
        session = CheckInSession.objects.annotate(
            present=Count("checkins", filter=CheckIn.state_q(State.PRESENT)),
            no_show=Count("checkins", filter=CheckIn.state_q(State.NO_SHOW)),
            attended=Count("checkins", filter=CheckIn.attended_q()),
        ).get(pk=self.session.pk)
        self.assertEqual((session.present, session.no_show, session.attended), (1, 1, 2))

    def test_arrived_row_with_stale_no_show_flag_is_present(self):
        row = self.rows[State.PRESENT]
        CheckIn.objects.filter(pk=row.pk).update(no_show=True)
        self.assertEqual(CheckIn.objects.get(pk=row.pk).state, State.PRESENT)
        self.assertNotIn(row, self.session.checkins.no_show())


class TransitionTests(LifecycleFixture):
    def test_arrive_from_expected_records_staff(self):
        self.assertTrue(self.rows[State.EXPECTED].arrive(user=self.staff))
        row = self.reload(State.EXPECTED)
        self.assertEqual(row.state, State.PRESENT)
        self.assertEqual(row.checked_in_by, self.staff)

    def test_arrive_from_no_show_reverses_it(self):
        row = self.rows[State.NO_SHOW]
        self.assertTrue(row.arrive())
        self.assertEqual(row.state, State.PRESENT)  # instance refreshed in place
        self.assertFalse(row.no_show)
        self.assertIsNone(row.checked_in_by)  # kiosk self check-in: no staff user

    def test_arrive_does_nothing_to_present_or_checked_out(self):
        for state in (State.PRESENT, State.CHECKED_OUT):
            before = self.reload(state).arrived_at
            self.assertFalse(self.rows[state].arrive(user=self.staff))
            self.assertEqual(self.reload(state).arrived_at, before)
            self.assertIsNone(self.reload(state).checked_in_by)

    def test_mark_no_show_only_from_expected(self):
        self.assertTrue(self.rows[State.EXPECTED].mark_no_show())
        self.assertEqual(self.reload(State.EXPECTED).state, State.NO_SHOW)
        for state in (State.PRESENT, State.CHECKED_OUT):
            self.assertFalse(self.rows[state].mark_no_show())
            self.assertEqual(self.reload(state).state, state)

    def test_check_out_only_from_present(self):
        self.assertTrue(self.rows[State.PRESENT].check_out(user=self.staff))
        row = self.reload(State.PRESENT)
        self.assertEqual(row.state, State.CHECKED_OUT)
        self.assertEqual(row.checked_out_by, self.staff)
        for state in (State.EXPECTED, State.NO_SHOW):
            self.assertFalse(self.rows[state].check_out())
            self.assertEqual(self.reload(state).state, state)

    def test_bulk_transitions_skip_invalid_rows_and_count_changes(self):
        everyone = self.session.checkins.all()
        self.assertEqual(everyone.mark_no_show(), 1)  # only the expected row
        self.assertEqual(everyone.arrive(user=self.staff), 2)  # both no-shows now
        self.assertEqual(everyone.check_out(user=self.staff), 3)  # all present now
        self.assertEqual(self.session.checkins.state_counts()[State.CHECKED_OUT], 4)


class ScreensUseOneNameTests(PreprintFixture):
    """Every screen calls a no-show a no-show (the pre-print page used to say Expected)."""

    def _stage_and_no_show(self):
        self._preprint({self.kids[0]: self.room_a})
        ci = CheckIn.objects.get(person=self.kids[0])
        ci.mark_no_show()
        return ci

    def test_preprint_page_shows_no_show(self):
        self._stage_and_no_show()
        resp = self.client.get(reverse("checkin:session_preprint", args=[self.session.pk]))
        self.assertContains(resp, "No-show")
        rows = [r for g in resp.context["groups"] for r in g["rows"]]
        status = {r["person"]: r["status"] for r in rows}
        self.assertEqual(status[self.kids[0]], State.NO_SHOW)

    def test_preprint_reprint_of_no_show_keeps_its_code(self):
        ci = self._stage_and_no_show()
        self._preprint({self.kids[0]: self.room_a})  # tick it again -> reprint
        self.assertEqual(CheckIn.objects.filter(person=self.kids[0]).count(), 1)
        ci.refresh_from_db()
        self.assertEqual(ci.state, State.NO_SHOW)

    def test_session_detail_shows_state_not_here(self):
        self._stage_and_no_show()
        resp = self.client.get(reverse("checkin:session_detail", args=[self.session.pk]))
        self.assertContains(resp, "No-show")
        self.assertNotContains(resp, ">Here<")


class ManagerRecordsStaffTests(LifecycleFixture):
    def test_bulk_arrive_records_who_confirmed(self):
        self.staff.profile.role = UserProfile.Role.VOLUNTEER
        self.staff.profile.save()
        self.client.force_login(self.staff)
        self.client.post(
            reverse("checkin:checkin_bulk_action", args=[self.session.pk]),
            {"action": "arrive", "checkin_ids": [self.rows[State.EXPECTED].pk]},
        )
        row = self.reload(State.EXPECTED)
        self.assertEqual(row.state, State.PRESENT)
        self.assertEqual(row.checked_in_by, self.staff)

    def test_mark_no_show_on_present_child_is_refused(self):
        self.staff.profile.role = UserProfile.Role.VOLUNTEER
        self.staff.profile.save()
        self.client.force_login(self.staff)
        self.client.post(reverse(
            "checkin:checkin_mark_noshow",
            args=[self.session.pk, self.rows[State.PRESENT].pk],
        ))
        self.assertEqual(self.reload(State.PRESENT).state, State.PRESENT)

"""Family check-in module: kiosk check-in, Pre-print staging, label printing."""
from unittest import mock

from django.core import mail

from checkin.models import CheckIn, PrintAgent, PrintJob
from checkin.services import family_checkin
from checkin.tests.test_preprint import PreprintFixture
from core.models import OrganizationSettings
from groups.models import Group, GroupMembership
from households.models import FamilyConflictFlag
from messaging.adapters import FakeAdapter
from messaging.models import Communication

State = CheckIn.State
QUEUE = "checkin.services.family_checkin.enqueue_checkin_labels"


class FamilyCheckInFixture(PreprintFixture):
    """The Walker family: Sue (adult, opted in) and kids Ava + Ben (age 9)."""

    def setUp(self):
        super().setUp()
        FakeAdapter.reset()
        self.addCleanup(FakeAdapter.reset)
        self.mom.phone = "+15550100"
        self.mom.phone_opt_in = True
        self.mom.save()
        self.room_b.min_age, self.room_b.max_age = 6, 12  # the kids' age-matched room
        self.room_b.save()
        self.ava, self.ben = self.kids

    def _flag(self, child):
        user = self.admin
        user.email = "admin@example.com"
        user.save()
        settings = OrganizationSettings.load()
        settings.family_alert_recipients.add(user)
        FamilyConflictFlag.objects.create(child=child, household=self.family)

    def prestage(self, person, code="PRE1"):
        return CheckIn.objects.create(session=self.session, person=person,
                                      room=self.room_a, security_code=code)


class KioskCheckInTests(FamilyCheckInFixture):
    @mock.patch(QUEUE, return_value=3)
    def test_walk_in_siblings_share_one_fresh_code(self, queue):
        result = family_checkin.check_in_family(
            self.session, self.family, [(self.ava, self.room_a), (self.ben, self.room_a)]
        )
        codes = {c.security_code for c in result.checkins}
        self.assertEqual(codes, {result.new_code})
        self.assertTrue(all(c.state == State.PRESENT for c in result.checkins))
        self.assertEqual(result.printed, result.checkins)
        self.assertTrue(result.labels_queued)
        self.assertFalse(result.needs_browser_print)
        queue.assert_called_once()

    @mock.patch(QUEUE, return_value=2)
    def test_walk_in_never_gets_the_familys_live_code(self, _q):
        self.prestage(self.ava, code="LIVE")
        result = family_checkin.check_in_family(self.session, self.family, [(self.ben, None)])
        self.assertNotEqual(result.new_code, "LIVE")
        self.assertEqual(result.checkins[0].security_code, result.new_code)

    @mock.patch(QUEUE, return_value=2)
    def test_no_room_chosen_uses_age_matched_room(self, _q):
        result = family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertEqual(result.checkins[0].room, self.room_b)

    @mock.patch(QUEUE, return_value=2)
    def test_chosen_room_wins_over_match(self, _q):
        result = family_checkin.check_in_family(self.session, self.family, [(self.ava, self.room_a)])
        self.assertEqual(result.checkins[0].room, self.room_a)

    @mock.patch(QUEUE)
    def test_prestaged_arrival_keeps_code_and_prints_nothing(self, queue):
        staged = self.prestage(self.ava)
        result = family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertEqual(result.checkins, [staged])
        self.assertEqual(result.checkins[0].state, State.PRESENT)
        self.assertEqual(result.checkins[0].security_code, "PRE1")
        self.assertEqual(result.new_code, "")
        self.assertEqual(result.printed, [])
        self.assertFalse(result.needs_browser_print)
        queue.assert_not_called()

    @mock.patch(QUEUE, return_value=2)
    def test_no_show_who_turns_up_arrives(self, _q):
        staged = self.prestage(self.ava)
        staged.mark_no_show()
        result = family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertEqual(result.checkins[0].state, State.PRESENT)
        self.assertEqual(result.printed, [])

    @mock.patch(QUEUE, return_value=2)
    def test_mixed_arrival_texts_each_code_once(self, _q):
        self.prestage(self.ava, code="PRE1")
        result = family_checkin.check_in_family(
            self.session, self.family, [(self.ava, None), (self.ben, None)]
        )
        self.assertTrue(result.texted)
        bodies = sorted(Communication.objects.values_list("body", flat=True))
        self.assertEqual(len(bodies), 2)
        self.assertTrue(any("PRE1" in b and "Ava" in b for b in bodies))
        self.assertTrue(any(result.new_code in b and "Ben" in b for b in bodies))

    @mock.patch(QUEUE, return_value=0)
    def test_no_print_agent_means_browser_print(self, _q):
        self.prestage(self.ava)  # a pre-staged arrival must not hide the walk-in's labels
        result = family_checkin.check_in_family(
            self.session, self.family, [(self.ava, None), (self.ben, None)]
        )
        self.assertFalse(result.labels_queued)
        self.assertTrue(result.needs_browser_print)

    @mock.patch(QUEUE, side_effect=RuntimeError("printer on fire"))
    def test_side_effect_failures_never_block_check_in(self, _q):
        FakeAdapter.fail_with = "twilio down"
        with mock.patch("checkin.services.family_checkin.alert_flagged_checkins",
                        side_effect=RuntimeError("smtp down")):
            result = family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertEqual(result.checkins[0].state, State.PRESENT)
        self.assertFalse(result.labels_queued)
        self.assertFalse(result.texted)

    @mock.patch(QUEUE, return_value=2)
    def test_auto_enrolls_into_configured_group(self, _q):
        day2 = Group.objects.create(name="VBS Day 2", category="event")
        self.config.auto_enroll_group = day2
        self.config.save()
        self.session.refresh_from_db()
        family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertTrue(GroupMembership.objects.filter(group=day2, person=self.ava).exists())

    @mock.patch(QUEUE, return_value=2)
    def test_flagged_child_alerts_staff(self, _q):
        self._flag(self.ava)
        family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Ava", mail.outbox[0].subject)

    @mock.patch(QUEUE, return_value=2)
    def test_raced_active_check_in_is_reused_not_duplicated(self, _q):
        # A Pre-print for the same child lands after the kiosk looked for pre-staged
        # rows but before it saves: the one-active-check-in constraint trips.
        raced = self.prestage(self.ava)
        with mock.patch("checkin.services.family_checkin._prestaged", return_value={}):
            result = family_checkin.check_in_family(self.session, self.family, [(self.ava, None)])
        self.assertEqual(CheckIn.objects.filter(person=self.ava).count(), 1)
        self.assertEqual(result.checkins[0].pk, raced.pk)
        self.assertEqual(result.checkins[0].state, State.PRESENT)
        self.assertEqual(result.new_code, "")  # the minted code ended up on no one


class StageFamiliesTests(FamilyCheckInFixture):
    @mock.patch(QUEUE, return_value=3)
    def test_new_family_shares_one_code_and_is_expected(self, queue):
        staging = family_checkin.stage_families(self.session, [(self.ava, None), (self.ben, self.room_a)])
        self.assertEqual((staging.created, staging.reprinted, staging.families), (2, 0, 1))
        rows = list(CheckIn.objects.filter(session=self.session))
        self.assertEqual(len({c.security_code for c in rows}), 1)
        self.assertTrue(all(c.state == State.EXPECTED for c in rows))
        self.assertEqual({c.person: c.room for c in rows}, {self.ava: self.room_b, self.ben: self.room_a})
        queue.assert_called_once()

    @mock.patch(QUEUE, return_value=2)
    def test_reuses_family_code_staff_side(self, _q):
        self.prestage(self.ava, code="FAM1")
        staging = family_checkin.stage_families(self.session, [(self.ben, None)])
        self.assertEqual(staging.created, 1)
        self.assertEqual(CheckIn.objects.get(person=self.ben).security_code, "FAM1")

    @mock.patch(QUEUE, return_value=2)
    def test_already_active_is_reprinted_not_duplicated(self, _q):
        self.prestage(self.ava)
        staging = family_checkin.stage_families(self.session, [(self.ava, None)])
        self.assertEqual((staging.created, staging.reprinted), (0, 1))
        self.assertEqual(CheckIn.objects.filter(person=self.ava).count(), 1)


class PrintLabelsTests(FamilyCheckInFixture):
    def setUp(self):
        super().setUp()
        self.agent = PrintAgent.objects.create(name="Desk")
        self.agent.complete_pairing()

    def test_mixed_codes_print_one_pickup_tag_per_code(self):
        ava = self.prestage(self.ava, code="AAAA")
        ben = CheckIn.objects.create(session=self.session, person=self.ben,
                                     room=self.room_a, security_code="BBBB")
        queued = family_checkin.print_labels([ava, ben], self.session, agent=self.agent)
        jobs = list(PrintJob.objects.order_by("pk").values_list("kind", "description"))
        self.assertEqual(queued, 4)
        self.assertEqual(jobs, [
            ("child", "Ava Walker"), ("pickup", "Pickup tag: Ava"),
            ("child", "Ben Walker"), ("pickup", "Pickup tag: Ben"),
        ])

    def test_never_raises(self):
        with mock.patch(QUEUE, side_effect=RuntimeError("boom")):
            self.assertEqual(family_checkin.print_labels([self.prestage(self.ava)], self.session), 0)

    def test_empty_batch_prints_nothing(self):
        self.assertEqual(family_checkin.print_labels([], self.session), 0)


class ConfirmArrivalsTests(FamilyCheckInFixture):
    def test_records_staff_and_alerts_flagged_child(self):
        staged = self.prestage(self.ava)
        self._flag(self.ava)
        n = family_checkin.confirm_arrivals(
            self.session, self.session.checkins.filter(pk=staged.pk), self.admin
        )
        self.assertEqual(n, 1)
        staged.refresh_from_db()
        self.assertEqual((staged.state, staged.checked_in_by), (State.PRESENT, self.admin))
        self.assertEqual(len(mail.outbox), 1)

    def test_present_child_is_not_re_arrived_or_re_alerted(self):
        staged = self.prestage(self.ava)
        staged.arrive()
        self._flag(self.ava)
        n = family_checkin.confirm_arrivals(
            self.session, self.session.checkins.filter(pk=staged.pk), self.admin
        )
        self.assertEqual(n, 0)
        self.assertEqual(len(mail.outbox), 0)

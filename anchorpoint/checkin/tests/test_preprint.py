"""Tests for pre-printed check-in (walk-up-and-go) + kiosk lock hardening."""

from datetime import date, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import (
    CheckIn, CheckInConfiguration, CheckInWindow, PrintAgent, Room,
)
from core.models import OrganizationSettings, UserProfile
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person


def _admin(username="ppadmin"):
    user = get_user_model().objects.create_user(username=username, password="pw")
    user.profile.role = UserProfile.Role.ADMIN
    user.profile.save()
    return user


def _open_window(config):
    now = timezone.localtime()
    return CheckInWindow.objects.create(
        configuration=config,
        schedule_type=CheckInWindow.TYPE_WEEKLY,
        day_of_week=(now.weekday() + 1) % 7,
        checkin_opens=time(0, 0), event_starts=time(0, 5),
        checkin_closes=time(23, 50), event_ends=time(23, 55),
    )


class PreprintFixture(TestCase):
    def setUp(self):
        self.admin = _admin()
        self.client.force_login(self.admin)

        self.group = Group.objects.create(name="VBS 2026", category="event")
        self.config = CheckInConfiguration.objects.create(name="VBS")
        self.config.groups.add(self.group)
        self.room_a = Room.objects.create(name="Preschool", capacity=20)
        self.room_b = Room.objects.create(name="Elementary", capacity=20)
        self.config.rooms.add(self.room_a, self.room_b)
        _open_window(self.config)

        from checkin.services.session_manager import get_or_create_session
        self.session = get_or_create_session(self.config, self.config.windows.first())

        # One family with two enrolled kids.
        self.family = Household.objects.create(name="Walker Family")
        self.mom = Person.objects.create(first_name="Sue", last_name="Walker",
                                         birthdate=date(1988, 1, 1))
        HouseholdMember.objects.create(
            household=self.family, person=self.mom,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        self.kids = []
        for name in ("Ava", "Ben"):
            kid = Person.objects.create(
                first_name=name, last_name="Walker",
                birthdate=date(2017, 6, 1),
            )
            HouseholdMember.objects.create(
                household=self.family, person=kid,
                relationship_type=HouseholdMember.RelationshipType.CHILD,
            )
            GroupMembership.objects.create(group=self.group, person=kid)
            self.kids.append(kid)

    def _preprint(self, rooms_by_kid):
        data = {}
        for kid, room in rooms_by_kid.items():
            data[f"select_{kid.pk}"] = "on"
            data[f"room_{kid.pk}"] = str(room.pk)
        return self.client.post(
            reverse("checkin:session_preprint", args=[self.session.pk]), data
        )


class PreprintRosterTests(PreprintFixture):
    def test_roster_lists_enrolled_kids_not_adults(self):
        resp = self.client.get(reverse("checkin:session_preprint", args=[self.session.pk]))
        self.assertContains(resp, "Ava Walker")
        self.assertContains(resp, "Ben Walker")
        self.assertNotContains(resp, "Sue Walker")  # adult not in the VBS group

    def test_each_family_has_a_select_all_checkbox(self):
        # Per-family header checkbox to select that whole family at once.
        resp = self.client.get(reverse("checkin:session_preprint", args=[self.session.pk]))
        self.assertContains(resp, 'class="family-select"')

    def test_requires_checkin_admin(self):
        staff = get_user_model().objects.create_user(username="plainstaff", password="pw")
        staff.profile.role = UserProfile.Role.VOLUNTEER
        staff.profile.save()
        self.client.force_login(staff)
        resp = self.client.get(reverse("checkin:session_preprint", args=[self.session.pk]))
        self.assertNotEqual(resp.status_code, 200)

    @mock.patch("checkin.views.enqueue_checkin_labels", return_value=3)
    def test_generate_creates_prestaged_checkins_with_shared_code(self, mock_enqueue):
        self._preprint({self.kids[0]: self.room_a, self.kids[1]: self.room_b})
        checkins = CheckIn.objects.filter(session=self.session)
        self.assertEqual(checkins.count(), 2)
        for c in checkins:
            self.assertIsNone(c.arrived_at)          # pre-staged, not arrived
            self.assertTrue(c.is_expected)
            self.assertIsNotNone(c.room)
        codes = {c.security_code for c in checkins}
        self.assertEqual(len(codes), 1)              # one shared family code
        mock_enqueue.assert_called_once()            # labels queued once for the family

    @mock.patch("checkin.views.enqueue_checkin_labels", return_value=2)
    def test_reselecting_staged_reprints_without_creating(self, mock_enqueue):
        self._preprint({self.kids[0]: self.room_a, self.kids[1]: self.room_b})
        mock_enqueue.reset_mock()
        # Re-selecting the same (already-staged) kids re-queues their labels
        # (reprint) but creates no new check-ins.
        self._preprint({self.kids[0]: self.room_a, self.kids[1]: self.room_b})
        self.assertEqual(CheckIn.objects.filter(session=self.session).count(), 2)
        mock_enqueue.assert_called_once()

    @mock.patch("checkin.views.enqueue_checkin_labels", return_value=1)
    def test_print_selected_mixes_new_and_reprint(self, mock_enqueue):
        self._preprint({self.kids[0]: self.room_a})  # stage one kid
        mock_enqueue.reset_mock()
        # Select both: the staged kid (reprint) + the new kid (create + print).
        self._preprint({self.kids[0]: self.room_a, self.kids[1]: self.room_b})
        self.assertEqual(CheckIn.objects.filter(session=self.session).count(), 2)
        mock_enqueue.assert_called_once()  # one batch for the family

    @mock.patch("checkin.views.enqueue_checkin_labels", return_value=2)
    def test_prestaged_not_counted_present(self, _m):
        self._preprint({self.kids[0]: self.room_a, self.kids[1]: self.room_b})
        self.assertEqual(self.session.total_checked_in(), 0)  # none present yet
        from checkin.views import _session_stats
        stats = _session_stats(self.session)
        self.assertEqual(stats["checked_in"], 0)
        self.assertEqual(stats["expected"], 2)


class PreprintArrivalTests(PreprintFixture):
    def setUp(self):
        super().setUp()
        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()
        # Pre-stage both kids directly.
        self.code = "PRE1"
        for kid, room in ((self.kids[0], self.room_a), (self.kids[1], self.room_b)):
            CheckIn.objects.create(
                session=self.session, person=kid, room=room,
                security_code=self.code, arrived_at=None,
            )
        s = self.client.session
        s["kiosk_authenticated"] = True
        s["kiosk_session_id"] = self.session.pk
        s.save()

    @mock.patch("checkin.views.send_security_code_sms", return_value=0)
    @mock.patch("checkin.views.enqueue_checkin_labels")
    def test_arrival_sets_arrived_without_reprint(self, mock_enqueue, _sms):
        resp = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.family.pk]),
            {f"select_{self.kids[0].pk}": "on", f"select_{self.kids[1].pk}": "on"},
        )
        self.assertRedirects(resp, reverse("checkin:kiosk_confirmation"))
        # No new rows; both now present; labels NOT re-queued.
        self.assertEqual(CheckIn.objects.filter(session=self.session).count(), 2)
        for c in CheckIn.objects.filter(session=self.session):
            self.assertIsNotNone(c.arrived_at)
            self.assertEqual(c.security_code, self.code)  # kept pre-printed code
        mock_enqueue.assert_not_called()
        self.assertEqual(self.session.total_checked_in(), 2)

    @mock.patch("checkin.views.send_security_code_sms", return_value=0)
    @mock.patch("checkin.views.enqueue_checkin_labels", return_value=1)
    def test_walkin_sibling_shares_family_code_and_prints(self, mock_enqueue, _sms):
        # A third, not-pre-staged sibling joins at the door.
        walkin = Person.objects.create(first_name="Cy", last_name="Walker",
                                       birthdate=date(2019, 3, 3))
        HouseholdMember.objects.create(
            household=self.family, person=walkin,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        GroupMembership.objects.create(group=self.group, person=walkin)
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.family.pk]),
            {
                f"select_{self.kids[0].pk}": "on",
                f"select_{walkin.pk}": "on",
                f"room_{walkin.pk}": str(self.room_a.pk),
            },
        )
        walkin_ci = CheckIn.objects.get(session=self.session, person=walkin)
        self.assertEqual(walkin_ci.security_code, self.code)  # shares family code
        self.assertIsNotNone(walkin_ci.arrived_at)
        mock_enqueue.assert_called_once()  # only the walk-in prints

    def test_prestaged_not_checkout_able_until_arrived(self):
        staff = get_user_model().objects.create_user(username="costaff", password="pw")
        staff.profile.role = UserProfile.Role.STAFF
        staff.profile.save()
        self.client.force_login(staff)
        resp = self.client.post(
            reverse("checkin:checkout_lookup", args=[self.session.pk]),
            {"security_code": self.code},
        )
        self.assertContains(resp, "No active check-ins")
        # After arrival, checkout finds them.
        CheckIn.objects.filter(session=self.session).update(arrived_at=timezone.now())
        resp = self.client.post(
            reverse("checkin:checkout_lookup", args=[self.session.pk]),
            {"security_code": self.code},
        )
        self.assertContains(resp, "Ava")


class KioskLockTests(TestCase):
    def test_lock_logs_out_authenticated_user(self):
        user = _admin("lockadmin")
        self.client.force_login(user)
        s = self.client.session
        s["kiosk_authenticated"] = True
        s.save()
        self.client.get(reverse("checkin:kiosk_lock"))
        # Subsequent request to a login-required page should redirect to login.
        resp = self.client.get(reverse("checkin:session_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.url)


class KioskAddChildTests(PreprintFixture):
    """Adding an unregistered walk-in to an existing family from the kiosk."""

    def setUp(self):
        super().setUp()
        s = self.client.session
        s["kiosk_authenticated"] = True
        s["kiosk_session_id"] = self.session.pk
        s.save()

    def _add(self, **data):
        return self.client.post(
            reverse("checkin:kiosk_family_add_child", args=[self.family.pk]), data
        )

    def test_adds_child_links_family_and_enrolls(self):
        resp = self._add(first_name="Nora", grade="2")
        self.assertRedirects(
            resp, reverse("checkin:kiosk_family_select", args=[self.family.pk])
        )
        nora = Person.objects.get(first_name="Nora")
        self.assertEqual(nora.last_name, "Walker")          # surname from the family
        self.assertEqual(nora.grade, "2")
        self.assertTrue(self.family.members.filter(pk=nora.pk).exists())
        self.assertTrue(
            GroupMembership.objects.filter(group=self.group, person=nora).exists()
        )
        # Eligible + visible on the family screen, ready to check in.
        page = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.family.pk])
        )
        self.assertContains(page, "Nora Walker")

    def test_adds_child_with_birthdate(self):
        self._add(first_name="Eli", birthdate="2017-09-01")
        eli = Person.objects.get(first_name="Eli")
        self.assertEqual(eli.birthdate, date(2017, 9, 1))

    def test_blank_name_is_a_noop(self):
        before = Person.objects.count()
        self._add(first_name="   ", grade="2")
        self.assertEqual(Person.objects.count(), before)

    def test_existing_same_name_member_not_duplicated(self):
        self._add(first_name="Ava", last_name="Walker", grade="1")  # Ava already exists
        self.assertEqual(
            Person.objects.filter(first_name="Ava", last_name="Walker").count(), 1
        )

    def test_requires_kiosk_unlock(self):
        s = self.client.session
        s["kiosk_authenticated"] = False
        s.save()
        resp = self._add(first_name="Locked", grade="2")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Person.objects.filter(first_name="Locked").exists())


class SessionCreateWindowLinkTests(PreprintFixture):
    """A manually-created session links the day's schedule window (and reuses an
    existing one), so it isn't a duplicate of the kiosk's auto-opened session."""

    def _create(self, date_obj):
        return self.client.post(reverse("checkin:session_create"), {
            "configuration": self.config.pk,
            "name": "VBS manual",
            "date": date_obj.isoformat(),
            "checkin_opens": "09:00", "checkin_closes": "12:00",
            "event_starts": "09:30", "event_ends": "11:30",
            "rooms": [self.room_a.pk],
            "is_active": "on",
        })

    def test_reuses_existing_windowed_session(self):
        from checkin.models import CheckInSession
        # The fixture already made self.session for (config, window, today).
        before = CheckInSession.objects.filter(date=timezone.localdate()).count()
        resp = self._create(timezone.localdate())
        self.assertRedirects(
            resp, reverse("checkin:session_detail", args=[self.session.pk])
        )
        self.assertEqual(CheckInSession.objects.filter(date=timezone.localdate()).count(), before)

    def test_links_window_on_create(self):
        from checkin.models import CheckInSession
        future = timezone.localdate() + timedelta(days=7)  # same weekday → weekly window
        self._create(future)
        s = CheckInSession.objects.get(date=future)
        self.assertEqual(s.window, self.config.windows.first())

"""Security regressions for the kiosk, checkout, and kiosk-unlock paths.

Each test pins down one exploit that used to work (see the 2026-10 security
review): leaking a family's live pickup code at the kiosk, checking a child out
without the pickup code, opening any household by id, and brute-forcing the
kiosk PIN.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from checkin import views
from checkin.models import CheckIn
from checkin.tests.kiosk_helpers import unlock_kiosk
from checkin.tests.test_preprint import PreprintFixture
from core.models import OrganizationSettings, UserProfile
from core.net import client_ip


def _user(username, role):
    user = get_user_model().objects.create_user(username=username, password="pw")
    user.profile.role = role
    user.profile.save()
    return user


class KioskFixture(PreprintFixture):
    """Anonymous, PIN-unlocked kiosk with Ava already checked in (present)."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.logout()  # a public kiosk, not a signed-in admin
        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()
        self.ava, self.ben = self.kids
        self.live = CheckIn.objects.create(
            session=self.session, person=self.ava, room=self.room_a,
            security_code="LIVE", arrived_at=timezone.now(),
        )
        s = self.client.session
        unlock_kiosk(s)
        s["kiosk_session_id"] = self.session.pk
        s.save()

    def _select(self, *people, room=None):
        data = {}
        for p in people:
            data[f"select_{p.pk}"] = "on"
            data[f"room_{p.pk}"] = str((room or self.room_a).pk)
        return self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.family.pk]), data
        )


@mock.patch("checkin.views.send_security_code_sms", return_value=0)
@mock.patch("checkin.views.enqueue_checkin_labels", return_value=0)
class KioskCodeLeakTests(KioskFixture):
    def test_present_child_cannot_be_rechecked_in(self, mock_enqueue, _sms):
        # Forged POST for a child who is already here: no reprint, no reveal.
        resp = self._select(self.ava)
        self.assertEqual(resp.status_code, 200)  # form error, not a confirmation
        mock_enqueue.assert_not_called()
        self.assertNotContains(resp, "LIVE")
        self.assertEqual(CheckIn.objects.filter(person=self.ava).count(), 1)

    def test_present_child_shown_as_checked_in(self, _enqueue, _sms):
        resp = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.family.pk])
        )
        self.assertContains(resp, "Already checked in")
        self.assertNotContains(resp, f'name="select_{self.ava.pk}"')
        self.assertNotContains(resp, "LIVE")

    def test_walkin_sibling_never_gets_the_live_code(self, mock_enqueue, _sms):
        self._select(self.ben)
        ben_ci = CheckIn.objects.get(session=self.session, person=self.ben)
        self.assertNotEqual(ben_ci.security_code, "LIVE")
        resp = self.client.get(reverse("checkin:kiosk_confirmation"))
        self.assertContains(resp, ben_ci.security_code)
        self.assertNotContains(resp, "LIVE")

    def test_prestaged_arrival_does_not_display_code(self, mock_enqueue, _sms):
        self.live.delete()
        CheckIn.objects.create(
            session=self.session, person=self.ava, room=self.room_a,
            security_code="PRE9", arrived_at=None,
        )
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.family.pk]),
            {f"select_{self.ava.pk}": "on"},
        )
        mock_enqueue.assert_not_called()
        resp = self.client.get(reverse("checkin:kiosk_confirmation"))
        self.assertNotContains(resp, "PRE9")


class KioskHouseholdAccessTests(KioskFixture):
    def test_household_by_id_requires_lookup(self):
        s = self.client.session
        unlock_kiosk(s, households=[])
        s.save()
        url = reverse("checkin:kiosk_family_select", args=[self.family.pk])
        self.assertRedirects(self.client.get(url), reverse("checkin:kiosk_lookup"),
                             fetch_redirect_response=False)
        # ...but a search that returns the family lets this kiosk open it.
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Walker"})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_child_requires_lookup(self):
        s = self.client.session
        unlock_kiosk(s, households=[])
        s.save()
        self.client.post(
            reverse("checkin:kiosk_family_add_child", args=[self.family.pk]),
            {"first_name": "Intruder"},
        )
        self.assertFalse(self.family.members.filter(first_name="Intruder").exists())


class KioskUnlockTests(TestCase):
    def setUp(self):
        cache.clear()
        org = OrganizationSettings.load()
        org.kiosk_pin = "4321"
        org.save()
        self.url = reverse("checkin:kiosk_unlock")

    def _try(self, pin, ip="198.51.100.7"):
        return self.client.post(self.url, {"pin": pin}, HTTP_CF_CONNECTING_IP=ip)

    def test_lockout_after_repeated_wrong_pins(self):
        for _ in range(views.KIOSK_PIN_IP_LIMIT):
            self._try("0000")
        resp = self._try("4321")  # right PIN, but this IP is locked out
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Too many incorrect PINs")
        self.assertFalse(self.client.session.get(views.KIOSK_SESSION_KEY))

    def test_lockout_is_per_ip_and_ignores_forwarded_for(self):
        for i in range(views.KIOSK_PIN_IP_LIMIT):
            # Rotating X-Forwarded-For must not reset the counter.
            self.client.post(self.url, {"pin": "0000"},
                             HTTP_CF_CONNECTING_IP="198.51.100.7",
                             HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
        self.assertContains(self._try("4321"), "Too many incorrect PINs")
        # A different real client is unaffected.
        resp = self._try("4321", ip="203.0.113.9")
        self.assertRedirects(resp, reverse("checkin:kiosk_lookup"),
                             fetch_redirect_response=False)

    def test_checkin_admin_bypasses_lockout(self):
        for _ in range(views.KIOSK_PIN_IP_LIMIT):
            self._try("0000")
        self.client.force_login(_user("kadmin", UserProfile.Role.ADMIN))
        resp = self._try("4321")
        self.assertRedirects(resp, reverse("checkin:kiosk_lookup"),
                             fetch_redirect_response=False)

    def test_pin_change_relocks_unlocked_kiosks(self):
        self._try("4321")
        self.assertTrue(self.client.session.get(views.KIOSK_SESSION_KEY))
        org = OrganizationSettings.load()
        org.kiosk_pin = "9999"
        org.save()
        resp = self.client.get(reverse("checkin:kiosk_lookup"))
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)

    def test_unlock_expires(self):
        self._try("4321")
        s = self.client.session
        s[views.KIOSK_UNLOCKED_AT_KEY] -= views.KIOSK_UNLOCK_MAX_AGE + 1
        s.save()
        resp = self.client.get(reverse("checkin:kiosk_lookup"))
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)


class CheckoutRequiresCodeTests(KioskFixture):
    def setUp(self):
        super().setUp()
        self.config.checkout_enabled = True
        self.config.save()
        self.volunteer = _user("vol", UserProfile.Role.VOLUNTEER)
        self.client.force_login(self.volunteer)
        self.confirm_url = reverse("checkin:checkout_confirm", args=[self.session.pk])
        self.lookup_url = reverse("checkin:checkout_lookup", args=[self.session.pk])

    def _token_for(self, code):
        resp = self.client.post(self.lookup_url, {"security_code": code})
        return resp.context["checkout_token"]

    def test_confirm_without_code_lookup_checks_out_nobody(self):
        self.client.post(self.confirm_url, {"checkin_ids": [self.live.pk]})
        self.live.refresh_from_db()
        self.assertIsNone(self.live.checked_out_at)

    def test_confirm_with_matching_code(self):
        token = self._token_for("LIVE")
        self.client.post(self.confirm_url, {
            "checkin_ids": [self.live.pk], "checkout_token": token,
        })
        self.live.refresh_from_db()
        self.assertIsNotNone(self.live.checked_out_at)

    def test_token_for_one_code_cannot_check_out_another_child(self):
        other = CheckIn.objects.create(
            session=self.session, person=self.ben, room=self.room_a,
            security_code="OTHR", arrived_at=timezone.now(),
        )
        token = self._token_for("OTHR")
        self.client.post(self.confirm_url, {
            "checkin_ids": [self.live.pk, other.pk], "checkout_token": token,
        })
        self.live.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNone(self.live.checked_out_at)
        self.assertIsNotNone(other.checked_out_at)

    def test_tampered_or_expired_token_rejected(self):
        token = self._token_for("LIVE")
        self.client.post(self.confirm_url, {
            "checkin_ids": [self.live.pk], "checkout_token": token + "x",
        })
        with mock.patch.object(views, "CHECKOUT_TOKEN_MAX_AGE", -1):
            self.client.post(self.confirm_url, {
                "checkin_ids": [self.live.pk], "checkout_token": token,
            })
        self.live.refresh_from_db()
        self.assertIsNone(self.live.checked_out_at)

    def test_anonymous_checkout_goes_to_login(self):
        self.client.logout()
        resp = self.client.get(self.lookup_url)
        self.assertRedirects(resp, reverse("login"), fetch_redirect_response=False)


class CheckoutToggleTests(KioskFixture):
    """Checkout is opt-in per configuration (off by default)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(_user("vol2", UserProfile.Role.VOLUNTEER))
        self.lookup_url = reverse("checkin:checkout_lookup", args=[self.session.pk])

    def test_off_by_default_and_unreachable(self):
        self.assertFalse(self.config.checkout_enabled)
        resp = self.client.get(self.lookup_url)
        self.assertRedirects(
            resp, reverse("checkin:checkin_manager", args=[self.session.pk]),
            fetch_redirect_response=False,
        )
        # A crafted confirm can't check anyone out either.
        self.client.post(
            reverse("checkin:checkout_confirm", args=[self.session.pk]),
            {"checkin_ids": [self.live.pk]},
        )
        self.live.refresh_from_db()
        self.assertIsNone(self.live.checked_out_at)

    def test_checkout_button_follows_the_toggle(self):
        self.client.force_login(_user("adm2", UserProfile.Role.ADMIN))
        detail = reverse("checkin:session_detail", args=[self.session.pk])
        self.assertNotContains(self.client.get(detail), self.lookup_url)
        self.config.checkout_enabled = True
        self.config.save()
        self.assertContains(self.client.get(detail), self.lookup_url)
        self.assertEqual(self.client.get(self.lookup_url).status_code, 200)

    def test_pickup_code_still_issued_when_checkout_off(self):
        with mock.patch("checkin.views.enqueue_checkin_labels", return_value=1), \
                mock.patch("checkin.views.send_security_code_sms", return_value=0):
            self._select(self.ben)
        ben_ci = CheckIn.objects.get(session=self.session, person=self.ben)
        self.assertTrue(ben_ci.security_code)


class ManagerRosterGroupingTests(KioskFixture):
    def test_each_room_listed_once_even_with_equal_sort_order(self):
        from checkin.views import _present_checkins
        self.room_a.sort_order = self.room_b.sort_order = 0
        self.room_a.save(); self.room_b.save()
        from people.models import Person
        cal = Person.objects.create(first_name="Cal", last_name="Walker")
        # Ava (room A), Ben (room B), Cal (room A): name order alone interleaves rooms.
        CheckIn.objects.create(session=self.session, person=self.ben, room=self.room_b,
                               security_code="ZZ22", arrived_at=timezone.now())
        CheckIn.objects.create(session=self.session, person=cal, room=self.room_a,
                               security_code="ZZ33", arrived_at=timezone.now())
        rooms = [c.room_id for c in _present_checkins(self.session)]
        self.assertEqual(len(rooms), 3)
        # contiguous: once a room ends it never reappears
        self.assertEqual(len(rooms), len(set(rooms)) + sum(
            1 for i in range(1, len(rooms)) if rooms[i] == rooms[i - 1]))


class ClientIpTests(TestCase):
    def test_prefers_cloudflare_header_and_ignores_forwarded_for(self):
        rf = RequestFactory()
        req = rf.get("/", HTTP_CF_CONNECTING_IP="203.0.113.5",
                     HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(client_ip(req), "203.0.113.5")
        req = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(client_ip(req), "127.0.0.1")

    def test_garbage_header_falls_back(self):
        req = RequestFactory().get("/", HTTP_CF_CONNECTING_IP="not-an-ip",
                                   REMOTE_ADDR="192.0.2.1")
        self.assertEqual(client_ip(req), "192.0.2.1")

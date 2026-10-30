"""Invites, "Forgot password?", and the Team Member role they hand out."""
from datetime import time

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from checkin.models import CheckInConfiguration, CheckInSession
from core import invites
from core.models import UserProfile
from people.models import Person

User = get_user_model()
BASE = "https://ap.example.org"


def make_user(email, role, person=None, **extra):
    user = User.objects.create_user(username=email, email=email, password="pw-Strong-1234", **extra)
    user.profile.role = role
    user.profile.person = person
    user.profile.save()
    return user


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="church@example.org", SITE_BASE_URL=BASE)
class InviteTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_user("staff@example.org", UserProfile.Role.STAFF)
        self.person = Person.objects.create(first_name="Jordan", last_name="Carter",
                                            email="jordan@example.org")
        mail.outbox.clear()


class InviteServiceTests(InviteTestCase):
    def invite(self, person=None):
        return invites.invite(person or self.person, invited_by=self.staff, base_url=BASE)

    def test_creates_team_member_login_and_emails_link(self):
        result = self.invite()
        user = result.user
        self.assertTrue(result.created and result.sent)
        self.assertEqual(user.email, "jordan@example.org")
        self.assertEqual(user.profile.role, UserProfile.Role.TEAM_MEMBER)
        self.assertEqual(user.profile.person, self.person)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)  # the invite, and no welcome email
        msg = mail.outbox[0]
        self.assertIn("invited", msg.subject.lower() + msg.body)
        self.assertIn(f"{BASE}/password-reset/", msg.body)

    def test_resend_reuses_the_login(self):
        first = self.invite().user
        again = self.invite()
        self.assertFalse(again.created)
        self.assertEqual(again.user.pk, first.pk)
        self.assertEqual(len(mail.outbox), 2)

    def test_refuses_someone_who_already_signed_in(self):
        user = self.invite().user
        user.last_login = timezone.now()
        user.save()
        with self.assertRaisesMessage(invites.InviteError, "already has a login"):
            self.invite()

    def test_refuses_without_email(self):
        self.person.email = ""
        self.person.save()
        with self.assertRaisesMessage(invites.InviteError, "Add an email address"):
            self.invite()

    def test_refuses_an_email_that_is_another_persons_login(self):
        other = Person.objects.create(first_name="Sam", last_name="Carter")
        make_user("jordan@example.org", UserProfile.Role.VOLUNTEER, person=other)
        with self.assertRaisesMessage(invites.InviteError, "already the login for Sam Carter"):
            self.invite()

    def test_links_an_unlinked_login_without_changing_its_role(self):
        existing = make_user("Jordan@Example.org", UserProfile.Role.VOLUNTEER)
        result = self.invite()
        existing.profile.refresh_from_db()
        self.assertFalse(result.created)
        self.assertEqual(existing.profile.person, self.person)
        self.assertEqual(existing.profile.role, UserProfile.Role.VOLUNTEER)


class InviteViewTests(InviteTestCase):
    def test_staff_can_invite_from_profile(self):
        self.client.force_login(self.staff)
        resp = self.client.post(reverse("person_invite", args=[self.person.pk]), follow=True)
        self.assertContains(resp, "Invite sent to jordan@example.org")
        self.assertContains(resp, "Never (invite not used yet)")
        self.assertContains(resp, "Resend invite")

    def test_profile_offers_invite(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("people_detail", args=[self.person.pk]))
        self.assertContains(resp, "Invite to log in")

    def test_team_member_cannot_invite(self):
        member = make_user("member@example.org", UserProfile.Role.TEAM_MEMBER)
        self.client.force_login(member)
        resp = self.client.post(reverse("person_invite", args=[self.person.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(email="jordan@example.org").exists())


class PasswordResetTests(InviteTestCase):
    def link_from(self, msg):
        return next(line for line in msg.body.splitlines() if "/password-reset/" in line).strip()

    def test_login_page_links_to_reset(self):
        self.assertContains(self.client.get(reverse("login")), reverse("password_reset"))

    def test_invited_user_with_no_password_can_ask_for_a_new_link(self):
        invites.invite(self.person, invited_by=self.staff, base_url=BASE)
        mail.outbox.clear()
        resp = self.client.post(reverse("password_reset"), {"email": "JORDAN@example.org"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(self.link_from(mail.outbox[0]).startswith(f"{BASE}/password-reset/"))

    def test_unknown_email_looks_the_same_but_sends_nothing(self):
        resp = self.client.post(reverse("password_reset"), {"email": "nobody@example.org"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(mail.outbox, [])

    def test_too_many_requests_from_one_ip_are_refused(self):
        for _ in range(5):
            self.client.post(reverse("password_reset"), {"email": "staff@example.org"})
        resp = self.client.post(reverse("password_reset"), {"email": "staff@example.org"}, follow=True)
        self.assertContains(resp, "Too many requests")
        self.assertEqual(len(mail.outbox), 5)

    def test_link_sets_password_signs_in_and_then_stops_working(self):
        user = invites.invite(self.person, invited_by=self.staff, base_url=BASE).user
        path = self.link_from(mail.outbox[0]).replace(BASE, "")
        form_page = self.client.get(path, follow=True)
        self.assertContains(form_page, "Set your password")
        resp = self.client.post(form_page.redirect_chain[-1][0], {
            "new_password1": "Harbor-Sunday-77", "new_password2": "Harbor-Sunday-77",
        }, follow=True)
        self.assertRedirects(resp, reverse("dashboard"))
        self.assertContains(resp, "Your password is set")
        user.refresh_from_db()
        self.assertTrue(user.check_password("Harbor-Sunday-77"))
        self.client.logout()
        self.assertContains(self.client.get(path, follow=True), "This link has expired")

    def test_bad_token_shows_expired(self):
        uid = urlsafe_base64_encode(force_bytes(self.staff.pk))
        resp = self.client.get(reverse("password_reset_confirm", args=[uid, "bad-token"]), follow=True)
        self.assertContains(resp, "This link has expired")


class TeamMemberAccessTests(TestCase):
    """A Team Member login must never reach staff pages or anything on the check-in team
    (children's names, allergies, custody notes, pickup codes)."""

    def setUp(self):
        person = Person.objects.create(first_name="Team", last_name="Member")
        self.member = make_user("member@example.org", UserProfile.Role.TEAM_MEMBER, person=person)
        config = CheckInConfiguration.objects.create(name="Sunday Kids")
        self.session = CheckInSession.objects.create(
            name="Sunday AM", configuration=config, date=timezone.localdate(), is_active=True,
            checkin_opens=time(0, 0), checkin_closes=time(23, 50),
            event_starts=time(0, 5), event_ends=time(23, 55),
        )
        self.child = Person.objects.create(first_name="Kid", last_name="Safe", allergies="Peanuts")

    def test_refused_everywhere_but_their_own_pages(self):
        self.client.force_login(self.member)
        refused = [
            ("people_list", []), ("people_detail", [self.child.pk]),
            ("households:family_list", []), ("households:family_flags", []),
            ("groups:list", []), ("events:manage_list", []), ("events:registration_queue", []),
            ("messaging:home", []), ("reporting:list", []), ("user_list", []),
            ("settings_home", []), ("checkin:dashboard", []), ("checkin:session_list", []),
            ("checkin:checkin_manager", [self.session.pk]),
            ("checkin:checkin_manager_roster", [self.session.pk]),
            ("checkin:checkout_lookup", [self.session.pk]),
            ("groups:member_edit", [1, 1]), ("groups:position_add", [1]),
            ("scheduling:person_blockout_add", [self.child.pk]),
        ]
        for name, args in refused:
            with self.subTest(name):
                resp = self.client.get(reverse(name, args=args))
                self.assertIn(resp.status_code, (302, 403), f"{name} returned {resp.status_code}")
                self.assertNotContains(resp, "Peanuts", status_code=resp.status_code)
        for name in ("dashboard", "profile", "help:list", "scheduling:my_serving"):
            with self.subTest(name):
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200)
                self.assertNotContains(resp, "Sunday Kids")

    def test_check_in_volunteers_still_reach_the_manager(self):
        # Control for the test above: the manager is reachable by the Volunteer role.
        volunteer = make_user("vol@example.org", UserProfile.Role.VOLUNTEER)
        self.client.force_login(volunteer)
        resp = self.client.get(reverse("checkin:checkin_manager", args=[self.session.pk]))
        self.assertEqual(resp.status_code, 200)

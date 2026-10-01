from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from people.models import Person
from .forms import OrganizationSettingsForm
from .models import UserProfile


class OrganizationSettingsFormTests(TestCase):
    def test_twilio_fields_present(self):
        form = OrganizationSettingsForm()
        self.assertIn("twilio_account_sid", form.fields)
        self.assertIn("twilio_auth_token", form.fields)
        self.assertIn("sms_blackout_start", form.fields)


class ManageRolesViewTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="admin", password="password"
        )
        admin_profile = self.admin.profile
        admin_profile.role = UserProfile.Role.ADMIN
        admin_profile.save()
        self.user = get_user_model().objects.create_user(
            username="member", password="password"
        )

    def test_toggle_communications_permission(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("manage_roles"),
            {
                "user_id": self.user.id,
                "role": UserProfile.Role.STAFF,
                "can_manage_communications": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertTrue(profile.can_manage_communications)
        self.assertTrue(profile.has_communications_access)


User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailServiceTest(TestCase):
    def setUp(self):
        mail.outbox.clear()

    def test_send_welcome_email_sends_to_user(self):
        from core.email_service import send_welcome_email
        user = User.objects.create_user(
            username="emailtest", email="test@example.com", password="pass"
        )
        mail.outbox.clear()  # clear email triggered by user creation signal
        send_welcome_email(user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("test@example.com", mail.outbox[0].to)

    def test_send_welcome_email_does_not_raise_on_failure(self):
        from core.email_service import send_welcome_email
        user = User.objects.create_user(
            username="noemail", email="", password="pass"
        )
        mail.outbox.clear()
        send_welcome_email(user)  # must not raise

    def test_send_registration_confirmation_sends_to_registrant(self):
        from core.email_service import send_registration_confirmation
        from events.models import Event, EventRegistration
        event = Event.objects.create(title="Test Event", created_by=None)
        registration = EventRegistration.objects.create(
            event=event,
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
        )
        send_registration_confirmation(registration)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("jane@example.com", mail.outbox[0].to)
        self.assertIn("Test Event", mail.outbox[0].subject)

    def test_send_staff_notification_sends_to_staff(self):
        from core.email_service import send_staff_registration_notification
        from events.models import Event, EventRegistration
        staff_user = User.objects.create_user(
            username="staffuser", email="staff@example.com", password="pass"
        )
        mail.outbox.clear()
        staff_user.profile.role = UserProfile.Role.STAFF
        staff_user.profile.save()
        event = Event.objects.create(title="Test Event", created_by=None)
        registration = EventRegistration.objects.create(
            event=event,
            first_name="John",
            last_name="Smith",
            email="john@example.com",
        )
        mail.outbox.clear()
        send_staff_registration_notification(registration)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("staff@example.com", mail.outbox[0].bcc)

    def test_send_staff_notification_skips_when_no_staff(self):
        from core.email_service import send_staff_registration_notification
        from events.models import Event, EventRegistration
        event = Event.objects.create(title="Test Event", created_by=None)
        registration = EventRegistration.objects.create(
            event=event,
            first_name="John",
            last_name="Smith",
            email="john@example.com",
        )
        mail.outbox.clear()
        send_staff_registration_notification(registration)
        self.assertEqual(len(mail.outbox), 0)


class CheckinAdminRequiredTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()

        self.staff = User.objects.create_user(username="staff", password="pw")
        self.staff.profile.role = UserProfile.Role.STAFF
        self.staff.profile.save()

        self.vol_admin = User.objects.create_user(username="voladmin", password="pw")
        self.vol_admin.profile.role = UserProfile.Role.VOLUNTEER_ADMIN
        self.vol_admin.profile.save()

        self.volunteer = User.objects.create_user(username="vol", password="pw")
        self.volunteer.profile.role = UserProfile.Role.VOLUNTEER
        self.volunteer.profile.save()

    def test_admin_allowed(self):
        from core.permissions import is_checkin_admin
        self.assertTrue(is_checkin_admin(self.admin))

    def test_staff_allowed(self):
        from core.permissions import is_checkin_admin
        self.assertTrue(is_checkin_admin(self.staff))

    def test_volunteer_admin_allowed(self):
        from core.permissions import is_checkin_admin
        self.assertTrue(is_checkin_admin(self.vol_admin))

    def test_volunteer_denied(self):
        from core.permissions import is_checkin_admin
        self.assertFalse(is_checkin_admin(self.volunteer))

    def test_unauthenticated_denied(self):
        from django.contrib.auth.models import AnonymousUser
        from core.permissions import is_checkin_admin
        self.assertFalse(is_checkin_admin(AnonymousUser()))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WelcomeEmailSignalTest(TestCase):
    def setUp(self):
        mail.outbox.clear()

    def test_welcome_email_sent_on_user_creation(self):
        User.objects.create_user(
            username="newuser", email="newuser@example.com", password="pass"
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("newuser@example.com", mail.outbox[0].to)

    def test_welcome_email_not_sent_on_user_update(self):
        user = User.objects.create_user(
            username="existing", email="existing@example.com", password="pass"
        )
        mail.outbox.clear()
        user.first_name = "Updated"
        user.save()
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Task 1: UserProfile → Person link
# ---------------------------------------------------------------------------

class UserProfilePersonLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="linktest", password="pw")
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe", phone="+15550001111"
        )

    def test_profile_person_defaults_to_null(self):
        self.assertIsNone(self.user.profile.person)

    def test_profile_can_be_linked_to_person(self):
        self.user.profile.person = self.person
        self.user.profile.save()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.person, self.person)

    def test_person_link_cleared_on_person_delete(self):
        self.user.profile.person = self.person
        self.user.profile.save()
        self.person.delete()
        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.person)


# ---------------------------------------------------------------------------
# Task 2: Email-based login
# ---------------------------------------------------------------------------

class EmailLoginTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="jdoe@bolivar.church",
            email="jdoe@bolivar.church",
            password="securepass123",
            first_name="Jane",
            last_name="Doe",
        )

    def test_login_with_email_succeeds(self):
        response = self.client.post(reverse("login"), {
            "username": "jdoe@bolivar.church",
            "password": "securepass123",
        })
        self.assertRedirects(response, reverse("dashboard"))

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(reverse("login"), {
            "username": "jdoe@bolivar.church",
            "password": "wrongpassword",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_with_unknown_email_fails(self):
        response = self.client.post(reverse("login"), {
            "username": "nobody@bolivar.church",
            "password": "securepass123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_with_inactive_user_fails(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(reverse("login"), {
            "username": "jdoe@bolivar.church",
            "password": "securepass123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_page_shows_email_input(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'type="email"')


# ---------------------------------------------------------------------------
# Task 3: CreateUserForm + user_create view
# ---------------------------------------------------------------------------

class CreateUserFormEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="pw",
        )

    def _valid_data(self, email="new@example.com"):
        return {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": email,
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
        }

    def test_email_required(self):
        from core.forms import CreateUserForm
        data = self._valid_data()
        data["email"] = ""
        form = CreateUserForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_duplicate_email_rejected(self):
        from core.forms import CreateUserForm
        form = CreateUserForm(self._valid_data(email="existing@example.com"))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_valid_form_has_no_username_field(self):
        from core.forms import CreateUserForm
        form = CreateUserForm(self._valid_data())
        self.assertNotIn("username", form.fields)

    def test_password_mismatch_rejected(self):
        from core.forms import CreateUserForm
        data = self._valid_data()
        data["confirm_password"] = "different"
        form = CreateUserForm(data)
        self.assertFalse(form.is_valid())


class UserCreateViewEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.client.force_login(self.admin)

    def _post(self, email="newuser@example.com"):
        return self.client.post(reverse("user_create"), {
            "first_name": "New",
            "last_name": "User",
            "email": email,
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
        })

    def test_creates_user_with_email_as_username(self):
        self._post(email="staff@example.com")
        User = get_user_model()
        user = User.objects.get(email="staff@example.com")
        self.assertEqual(user.username, "staff@example.com")

    def test_redirects_to_user_list_on_success(self):
        response = self._post()
        self.assertRedirects(response, reverse("user_list"))

    def test_duplicate_email_shows_form_error(self):
        self._post(email="dup@example.com")
        response = self._post(email="dup@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")


# ---------------------------------------------------------------------------
# Task 4: Person match HTMX endpoint + person linking
# ---------------------------------------------------------------------------

class UserPersonCheckTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin2", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe",
            email="jane@example.com", phone="+15550001111"
        )

    def test_returns_partial_when_person_found(self):
        response = self.client.get(
            reverse("user_person_check"),
            {"email": "jane@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jane")
        self.assertContains(response, "Doe")

    def test_returns_empty_when_no_person(self):
        response = self.client.get(
            reverse("user_person_check"),
            {"email": "nobody@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"")

    def test_returns_empty_when_no_email(self):
        response = self.client.get(reverse("user_person_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"")

    def test_requires_admin(self):
        self.client.logout()
        User = get_user_model()
        vol = User.objects.create_user(username="vol", password="pw")
        self.client.force_login(vol)
        response = self.client.get(
            reverse("user_person_check"),
            {"email": "jane@example.com"},
        )
        self.assertNotEqual(response.status_code, 200)


class UserCreatePersonLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin3", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe",
            email="jane@church.com", phone="+15550002222"
        )

    def test_links_person_when_checkbox_checked(self):
        self.client.post(reverse("user_create"), {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@church.com",
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
            "link_person": str(self.person.pk),
        })
        User = get_user_model()
        user = User.objects.get(email="jane@church.com")
        self.assertEqual(user.profile.person, self.person)

    def test_no_link_when_checkbox_absent(self):
        self.client.post(reverse("user_create"), {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@church.com",
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
        })
        User = get_user_model()
        user = User.objects.get(email="jane@church.com")
        self.assertIsNone(user.profile.person)

    def test_stale_person_id_silently_ignored(self):
        self.client.post(reverse("user_create"), {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@church.com",
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
            "link_person": "99999",
        })
        User = get_user_model()
        user = User.objects.get(email="jane@church.com")
        self.assertIsNone(user.profile.person)


@override_settings(GOOGLE_CLIENT_ID="test-client-id-123")
class GoogleAuthCallbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="jsmith",
            email="jsmith@bolivar.church",
            password="unused",
        )
        self.url = reverse("google_auth")

    def _post(self, credential="fake-jwt"):
        return self.client.post(self.url, {"credential": credential})

    def _mock_verify(self, email="jsmith@bolivar.church"):
        """Return a patch context that makes verify_oauth2_token return a valid payload."""
        return patch(
            "core.views.id_token.verify_oauth2_token",
            return_value={"email": email, "email_verified": True},
        )

    def test_valid_credential_logs_in_and_redirects(self):
        with self._mock_verify():
            response = self._post()
        self.assertRedirects(response, reverse("dashboard"))
        response2 = self.client.get(reverse("dashboard"))
        self.assertEqual(response2.status_code, 200)

    def test_wrong_domain_rejected(self):
        with self._mock_verify(email="hacker@gmail.com"):
            response = self._post()
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_no_matching_user_rejected(self):
        with self._mock_verify(email="unknown@bolivar.church"):
            response = self._post()
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_invalid_jwt_rejected(self):
        with patch(
            "core.views.id_token.verify_oauth2_token",
            side_effect=ValueError("bad token"),
        ):
            response = self._post()
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_missing_credential_rejected(self):
        response = self.client.post(self.url, {})
        self.assertRedirects(response, reverse("login"))

    def test_get_request_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("login"))

    def test_unconfigured_client_id_rejected(self):
        with override_settings(GOOGLE_CLIENT_ID=""):
            response = self._post()
        self.assertRedirects(response, reverse("login"))

    def test_email_match_is_case_insensitive(self):
        with self._mock_verify(email="JSMITH@BOLIVAR.CHURCH"):
            response = self._post()
        self.assertRedirects(response, reverse("dashboard"))


class LoginPageTests(TestCase):
    @override_settings(GOOGLE_CLIENT_ID="test-client-id-123")
    def test_login_page_shows_google_button_when_configured(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "g_id_signin")
        self.assertContains(response, "test-client-id-123")

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_login_page_hides_google_button_when_not_configured(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "g_id_signin")

    def test_login_page_always_shows_password_form(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

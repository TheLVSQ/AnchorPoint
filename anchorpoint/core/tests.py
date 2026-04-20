from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

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

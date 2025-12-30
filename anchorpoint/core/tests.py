from django.contrib.auth import get_user_model
from django.test import TestCase
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

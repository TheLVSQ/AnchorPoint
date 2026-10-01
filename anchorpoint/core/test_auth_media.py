"""Batch 4 security regressions: media access, uploads, login, account safety."""
import os
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.login_throttle import LOGIN_FAIL_LIMIT
from core.models import OrganizationSettings, UserProfile
from core.validators import MAX_IMAGE_BYTES, person_photo_upload_path, validate_image_size, validate_pdf
from people.models import Person


def _user(username, role, password="Sturdy-pass-123", **extra):
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password=password, **extra
    )
    user.profile.role = role
    user.profile.save()
    return user


def _media_file(rel_path, content=b"data"):
    full = os.path.join(settings.MEDIA_ROOT, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(content)
    return f"/media/{rel_path}"


class MediaAccessTests(TestCase):
    def setUp(self):
        self.photo = _media_file("people/photos/IMG_1234.jpg", b"\xff\xd8kid")
        self.public = _media_file("events/photos/picnic.jpg", b"\xff\xd8picnic")

    def test_person_photo_requires_staff(self):
        resp = self.client.get(self.photo)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])
        self.client.force_login(_user("vol", UserProfile.Role.VOLUNTEER))
        self.assertEqual(self.client.get(self.photo).status_code, 403)
        self.client.force_login(_user("st", UserProfile.Role.STAFF))
        resp = self.client.get(self.photo)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Cache-Control"], "private, no-store")

    def test_dot_dot_cannot_escape_into_a_private_folder(self):
        resp = self.client.get("/media/events/photos/../../people/photos/IMG_1234.jpg")
        self.assertNotEqual(resp.status_code, 200)

    def test_public_folders_stay_public(self):
        self.assertEqual(self.client.get(self.public).status_code, 200)

    def test_html_upload_is_forced_to_download_in_sandbox(self):
        url = _media_file("events/releases/evil.html", b"<script>alert(1)</script>")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))
        self.assertEqual(resp["Content-Security-Policy"], "sandbox")


class UploadValidationTests(TestCase):
    def test_release_must_be_a_real_pdf(self):
        validate_pdf(SimpleUploadedFile("release.pdf", b"%PDF-1.7 ..."))
        for name, body in (("release.html", b"%PDF-"), ("release.pdf", b"<html>x</html>")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_pdf(SimpleUploadedFile(name, body))

    def test_existing_non_pdf_release_doesnt_block_editing(self):
        from events.models import Event
        event = Event.objects.create(title="Legacy", summary="s", description="d")
        event.media_release_custom.save("Photo_Release.pages", SimpleUploadedFile("x.pages", b"PK.."))
        event.refresh_from_db()
        validate_pdf(event.media_release_custom)  # stored file: not re-validated
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile("new.pages", b"PK.."))

    def test_image_size_limit(self):
        with self.assertRaises(ValidationError):
            validate_image_size(SimpleUploadedFile("big.jpg", b"x" * (MAX_IMAGE_BYTES + 1)))

    def test_person_photo_names_are_random(self):
        a = person_photo_upload_path(None, "Emma_Smith.JPG")
        b = person_photo_upload_path(None, "Emma_Smith.JPG")
        self.assertTrue(a.startswith("people/photos/") and a.endswith(".jpg"))
        self.assertNotIn("Emma", a)
        self.assertNotEqual(a, b)


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("victim", UserProfile.Role.ADMIN)
        self.url = reverse("login")

    def _login(self, password, email="victim@example.com", ip="198.51.100.9"):
        return self.client.post(self.url, {"username": email, "password": password},
                                HTTP_CF_CONNECTING_IP=ip)

    def test_account_locks_after_repeated_failures(self):
        for _ in range(LOGIN_FAIL_LIMIT):
            self._login("wrong")
        resp = self._login("Sturdy-pass-123", ip="203.0.113.1")  # even from another IP
        self.assertContains(resp, "Too many failed sign-in attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ip_locks_after_spraying_many_accounts(self):
        for i in range(LOGIN_FAIL_LIMIT):
            self._login("wrong", email=f"nobody{i}@example.com")
        resp = self._login("Sturdy-pass-123")
        self.assertContains(resp, "Too many failed sign-in attempts")

    def test_admin_login_is_throttled_too(self):
        url = "/admin/login/"
        for _ in range(LOGIN_FAIL_LIMIT):
            self.client.post(url, {"username": "victim", "password": "wrong"},
                             HTTP_CF_CONNECTING_IP="198.51.100.9")
        resp = self.client.post(url, {"username": "victim", "password": "Sturdy-pass-123"},
                                HTTP_CF_CONNECTING_IP="198.51.100.9")
        self.assertEqual(resp.status_code, 429)


class AccountSafetyTests(TestCase):
    def test_logout_requires_post(self):
        user = _user("u1", UserProfile.Role.STAFF)
        self.client.force_login(user)
        self.client.get(reverse("logout"))
        self.assertIn("_auth_user_id", self.client.session)
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_required_pages_go_to_real_login(self):
        resp = self.client.get(reverse("profile"))
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    def test_volunteer_dashboard_hides_recent_people(self):
        Person.objects.create(first_name="Zebulon", last_name="Newkid")
        self.client.force_login(_user("vol", UserProfile.Role.VOLUNTEER))
        self.assertNotContains(self.client.get(reverse("dashboard")), "Zebulon")

    def test_app_admin_cannot_reset_superuser_password(self):
        root = _user("root", UserProfile.Role.ADMIN, is_superuser=True, is_staff=True)
        self.client.force_login(_user("adm", UserProfile.Role.ADMIN))
        resp = self.client.post(reverse("user_set_password", args=[root.pk]), {
            "new_password": "Takeover-pass-9", "confirm_password": "Takeover-pass-9",
        })
        self.assertEqual(resp.status_code, 403)
        root.refresh_from_db()
        self.assertTrue(root.check_password("Sturdy-pass-123"))

    def test_changing_email_needs_current_password(self):
        user = _user("me", UserProfile.Role.STAFF)
        self.client.force_login(user)
        data = {"update_profile": "1", "first_name": "Me", "last_name": "Self",
                "email": "hijack@example.com"}
        self.client.post(reverse("profile"), data)
        user.refresh_from_db()
        self.assertEqual(user.email, "me@example.com")
        data["current_password"] = "Sturdy-pass-123"
        self.client.post(reverse("profile"), data)
        user.refresh_from_db()
        self.assertEqual(user.email, "hijack@example.com")
        self.assertEqual(user.username, "hijack@example.com")

    def test_twilio_webhook_fails_closed_without_token(self):
        org = OrganizationSettings.load()
        org.twilio_auth_token = ""
        org.save()
        resp = self.client.post(reverse("messaging:phone_call_status_webhook"),
                                {"CallSid": "CA1", "CallStatus": "completed"})
        self.assertEqual(resp.status_code, 403)

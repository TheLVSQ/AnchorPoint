from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from .guides import GUIDES, image_paths, render_guide


class GuideContentTests(TestCase):
    def test_every_guide_file_exists(self):
        for guide in GUIDES:
            self.assertTrue(guide.path.exists(), guide.path)

    def test_every_referenced_image_exists(self):
        # Prod uses hashed-manifest static storage, where static() raises for a
        # missing file — a typo'd image path would 500 the page there.
        for guide in GUIDES:
            paths = image_paths(guide.path.read_text())
            self.assertTrue(paths, f"{guide.slug} has no images (regex broken?)")
            for rel in paths:
                self.assertIsNotNone(finders.find(f"help/{rel}"), f"{guide.slug}: missing {rel}")

    def test_relative_images_resolve_to_static(self):
        html, toc = render_guide(GUIDES[0])
        self.assertIn('src="/static/help/checkin-setup/', html)
        self.assertNotIn('src="checkin-setup/', html)
        self.assertTrue(toc)


class HelpViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("vol", password="x")

    def test_login_required(self):
        resp = self.client.get(reverse("help:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_list_shows_guides_and_sidebar_link(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("help:list"))
        self.assertContains(resp, "Setting up check-in")
        self.assertContains(resp, 'href="/help/" aria-current="page"')

    def test_guide_renders(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("help:guide", args=["checkin-setup"]))
        self.assertContains(resp, "Step 1")
        self.assertContains(resp, "Print / save PDF")

    def test_unknown_guide_404s(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("help:guide", args=["nope"]))
        self.assertEqual(resp.status_code, 404)

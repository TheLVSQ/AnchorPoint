import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from groups.models import Group, GroupMembership
from people.models import Person

from .models import Arrangement, Chart, MediaLink, Song

User = get_user_model()
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def make_login(username, role, person=None):
    user = User.objects.create_user(username=username, password="pw-Strong-1234")
    user.profile.role = role
    user.profile.person = person
    user.profile.save()
    return user


def pdf(name="chart.pdf", content=PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class SongTestCase(TestCase):
    def setUp(self):
        self.staff = make_login("staff", UserProfile.Role.STAFF)
        self.song = Song.objects.create(title="Be Thou My Vision", author="Traditional",
                                        ccli_number="30639")
        self.arrangement = Arrangement.objects.create(song=self.song, key="D", bpm=72)
        self.client.force_login(self.staff)

    def add_chart(self, label="Chord chart", content=PDF, name="chart.pdf"):
        return self.client.post(
            reverse("songs:chart_add", args=[self.arrangement.pk]),
            {f"chart{self.arrangement.pk}-label": label,
             f"chart{self.arrangement.pk}-file": pdf(name, content)}, follow=True)


class AccessTests(SongTestCase):
    def setUp(self):
        super().setUp()
        self.chart = Chart.objects.create(arrangement=self.arrangement, label="Chord chart",
                                          file=pdf())
        self.team = Group.objects.create(name="Worship", category="volunteer")
        self.alex = Person.objects.create(first_name="Alex", last_name="Rivera")
        self.membership = GroupMembership.objects.create(group=self.team, person=self.alex)
        self.volunteer = make_login("alex", UserProfile.Role.TEAM_MEMBER, person=self.alex)

    def test_volunteer_who_leads_nothing_is_refused_everywhere(self):
        self.client.force_login(self.volunteer)
        for name, args in [("songs:list", []), ("songs:create", []),
                           ("songs:detail", [self.song.pk]), ("songs:chart", [self.chart.pk])]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        with self.subTest("raw media path"):
            self.assertEqual(self.client.get("/media/" + self.chart.file.name).status_code, 403)
        self.assertNotContains(self.client.get(reverse("dashboard")), "Songs")

    def test_anonymous_goes_to_login(self):
        self.client.logout()
        for url in (reverse("songs:list"), reverse("songs:chart", args=[self.chart.pk])):
            with self.subTest(url):
                self.assertRedirects(self.client.get(url), reverse("login"),
                                     fetch_redirect_response=False)

    def test_team_leader_manages_songs(self):
        self.membership.role = "leader"
        self.membership.save()
        self.client.force_login(self.volunteer)
        self.assertContains(self.client.get(reverse("dashboard")), "Songs")
        self.assertContains(self.client.get(reverse("songs:list")), "Be Thou My Vision")
        resp = self.client.get(reverse("songs:chart", args=[self.chart.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_chart_is_served_inline_and_never_linked_by_file_url(self):
        resp = self.client.get(reverse("songs:chart", args=[self.chart.pk]))
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("inline", resp["Content-Disposition"])
        self.assertIn("be-thou-my-vision-chord-chart.pdf", resp["Content-Disposition"])
        self.assertEqual(resp["Cache-Control"], "private, no-store")
        self.assertEqual(b"".join(resp.streaming_content), PDF)
        detail = self.client.get(reverse("songs:detail", args=[self.song.pk]))
        self.assertContains(detail, reverse("songs:chart", args=[self.chart.pk]))
        self.assertNotContains(detail, "/media/songs/")


class LibraryTests(SongTestCase):
    def test_new_song_gets_a_default_arrangement(self):
        resp = self.client.post(reverse("songs:create"), {"title": "Amazing Grace",
                                                          "author": "John Newton"})
        song = Song.objects.get(title="Amazing Grace")
        self.assertRedirects(resp, reverse("songs:detail", args=[song.pk]))
        self.assertEqual([a.name for a in song.arrangements.all()], ["Default"])

    def test_search_by_title_writer_or_ccli(self):
        Song.objects.create(title="Amazing Grace", author="John Newton")
        for query, expected in [("vision", "Be Thou"), ("newton", "Amazing"), ("30639", "Be Thou")]:
            with self.subTest(query):
                resp = self.client.get(reverse("songs:list"), {"q": query})
                self.assertEqual([s.title[:7] for s in resp.context["songs"]], [expected[:7]])

    def test_archive_hides_and_restore_brings_back(self):
        self.client.post(reverse("songs:archive", args=[self.song.pk]), follow=True)  # eats the message
        self.assertNotContains(self.client.get(reverse("songs:list")), "Be Thou My Vision")
        archived = self.client.get(reverse("songs:list"), {"archived": "1"})
        self.assertContains(archived, "Be Thou My Vision")
        self.client.post(reverse("songs:archive", args=[self.song.pk]))
        self.assertContains(self.client.get(reverse("songs:list")), "Be Thou My Vision")

    def test_arrangement_names_are_unique_per_song(self):
        url = reverse("songs:arrangement_create", args=[self.song.pk])
        resp = self.client.post(url, {"name": "default", "key": "C"})
        self.assertContains(resp, "already has an arrangement called default")
        self.client.post(url, {"name": "Acoustic", "key": "C"})
        self.assertTrue(self.song.arrangements.filter(name="Acoustic", key="C").exists())

    def test_last_arrangement_cant_be_removed(self):
        resp = self.client.post(reverse("songs:arrangement_delete", args=[self.arrangement.pk]),
                                follow=True)
        self.assertContains(resp, "needs at least one arrangement")
        self.assertTrue(Arrangement.objects.filter(pk=self.arrangement.pk).exists())


class ChartAndLinkTests(SongTestCase):
    def test_upload_stores_a_random_name_under_songs_charts(self):
        resp = self.add_chart()
        self.assertContains(resp, "Added Chord chart")
        chart = Chart.objects.get()
        self.assertTrue(chart.file.name.startswith("songs/charts/"))
        self.assertNotIn("chart", os.path.basename(chart.file.name))

    def test_only_real_pdfs_under_the_size_cap(self):
        resp = self.add_chart(content=b"<html><script>alert(1)</script>", name="chart.pdf")
        self.assertContains(resp, "Please upload a PDF file.")
        resp = self.add_chart(content=PDF, name="chart.html")
        self.assertContains(resp, "not allowed")
        with mock.patch("core.validators.MAX_PDF_BYTES", 10):
            resp = self.add_chart()
        self.assertContains(resp, "20 MB or smaller")
        self.assertFalse(Chart.objects.exists())

    def test_removing_a_chart_or_arrangement_deletes_the_file(self):
        self.add_chart()
        chart = Chart.objects.get()
        path = chart.file.path
        self.client.post(reverse("songs:chart_delete", args=[chart.pk]))
        self.assertFalse(os.path.exists(path))

        acoustic = Arrangement.objects.create(song=self.song, name="Acoustic")
        other = Chart.objects.create(arrangement=acoustic, label="Lead sheet", file=pdf())
        path = other.file.path
        self.client.post(reverse("songs:arrangement_delete", args=[acoustic.pk]))
        self.assertFalse(Arrangement.objects.filter(pk=acoustic.pk).exists())
        self.assertFalse(os.path.exists(path))

    def test_links_must_be_web_addresses(self):
        url = reverse("songs:link_add", args=[self.arrangement.pk])
        prefix = f"link{self.arrangement.pk}"
        resp = self.client.post(url, {f"{prefix}-label": "Bad",
                                      f"{prefix}-url": "javascript:alert(1)"})
        self.assertContains(resp, "Enter a valid URL")
        self.client.post(url, {f"{prefix}-label": "YouTube",
                               f"{prefix}-url": "https://www.youtube.com/watch?v=example"})
        self.assertEqual(list(MediaLink.objects.values_list("label", flat=True)), ["YouTube"])

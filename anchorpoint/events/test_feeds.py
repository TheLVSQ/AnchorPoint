"""Public events feeds (JSON + iCalendar) and the website rebuild trigger."""
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events import feeds
from events.models import Event, EventOccurrence, EventRegistration, WebsiteRebuildState

HOOK = "https://api.cloudflare.com/client/v4/workers/builds/deploy_hooks/test-secret"


def make_event(title="Fall Festival", days=7, **fields):
    defaults = dict(
        summary="Games and food",
        location_name="Church lawn",
        location_city="Bolivar",
        contact_name="Pat Organizer",
        contact_email="pat@example.com",
        contact_phone="555-0100",
        registration_capacity=50,
    )
    event = Event.objects.create(title=title, **{**defaults, **fields})
    EventOccurrence.objects.create(event=event, starts_at=timezone.now() + timedelta(days=days))
    return event


class EventsFeedJsonTests(TestCase):
    def get_feed(self):
        response = self.client.get(reverse("events:feed_json"))
        self.assertEqual(response.status_code, 200)
        return response

    def test_lists_only_published_upcoming_events_soonest_first(self):
        later = make_event("Later", days=20)
        sooner = make_event("Sooner", days=2)
        make_event("Hidden", is_published=False)
        past = Event.objects.create(title="Past")
        EventOccurrence.objects.create(event=past, starts_at=timezone.now() - timedelta(days=1))

        titles = [e["title"] for e in self.get_feed().json()["events"]]
        self.assertEqual(titles, [sooner.title, later.title])

    def test_items_have_absolute_links_and_upcoming_occurrences_only(self):
        event = make_event()
        EventOccurrence.objects.create(event=event, starts_at=timezone.now() - timedelta(days=3))

        item = self.get_feed().json()["events"][0]
        self.assertEqual(item["url"], f"http://testserver/events/{event.slug}/")
        self.assertEqual(len(item["occurrences"]), 1)
        self.assertEqual(item["next_start"], item["occurrences"][0]["starts_at"])
        self.assertEqual(item["cost_display"], "Free")
        self.assertTrue(item["registration_open"])

    def test_never_exposes_contact_capacity_or_registration_details(self):
        event = make_event()
        EventRegistration.objects.create(event=event, first_name="A", last_name="B", email="a@example.com")

        response = self.get_feed()
        item = response.json()["events"][0]
        for key in [
            "contact_name",
            "contact_email",
            "contact_phone",
            "registration_token",
            "registration_capacity",
            "registrations",
            "require_attendee_details",
            "liability_release_document",
            "media_release_document",
        ]:
            self.assertNotIn(key, item)
        body = response.content.decode()
        for secret in ["pat@example.com", "555-0100", "Pat Organizer", str(event.registration_token), "a@example.com"]:
            self.assertNotIn(secret, body)

    def test_is_public_and_cacheable(self):
        make_event()
        response = self.get_feed()  # anonymous client
        self.assertIn("public", response["Cache-Control"])
        self.assertIn("max-age=300", response["Cache-Control"])

    def test_rejects_writes(self):
        self.assertEqual(self.client.post(reverse("events:feed_json")).status_code, 405)


class EventsFeedIcsTests(TestCase):
    def test_calendar_escapes_text_and_folds_long_lines(self):
        make_event("Picnic, Games; and \\ more", summary="x" * 200)
        response = self.client.get(reverse("events:feed_ics"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()

        self.assertTrue(body.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(body.endswith("END:VCALENDAR\r\n"))
        self.assertIn("SUMMARY:Picnic\\, Games\\; and \\\\ more", body)
        for line in body.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)
        self.assertNotIn("pat@example.com", body)

    def test_all_day_events_use_local_dates(self):
        event = Event.objects.create(title="Retreat")
        # 11pm Eastern on Nov 6 is Nov 7 in UTC; the calendar date must stay Nov 6.
        start = timezone.make_aware(datetime(2099, 11, 6, 23, 0))
        EventOccurrence.objects.create(event=event, starts_at=start, ends_at=start, is_all_day=True)
        with mock.patch.object(feeds, "ICS_HORIZON_DAYS", 365 * 100):
            body = self.client.get(reverse("events:feed_ics")).content.decode()
        self.assertIn("DTSTART;VALUE=DATE:20991106", body)
        self.assertIn("DTEND;VALUE=DATE:20991107", body)


@override_settings(WEBSITE_DEPLOY_HOOK_URL=HOOK, SITE_BASE_URL="https://anchorpoint.example")
class TriggerSiteRebuildTests(TestCase):
    def run_command(self):
        out, err = StringIO(), StringIO()
        call_command("trigger_site_rebuild", stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def setUp(self):
        make_event()
        patcher = mock.patch("events.management.commands.trigger_site_rebuild.requests.post")
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def test_posts_hook_when_feed_changes(self):
        self.run_command()
        self.post.assert_called_once_with(HOOK, timeout=10)
        self.assertTrue(WebsiteRebuildState.load().feed_hash)

    def test_no_change_means_no_request(self):
        self.run_command()
        state = WebsiteRebuildState.load()
        state.last_requested_at = timezone.now() - timedelta(hours=1)
        state.save()
        self.post.reset_mock()
        self.run_command()
        self.post.assert_not_called()

    def test_debounces_changes_within_the_window(self):
        self.run_command()
        self.post.reset_mock()
        make_event("Another one")

        self.run_command()  # changed, but just rebuilt
        self.post.assert_not_called()

        state = WebsiteRebuildState.load()
        state.last_requested_at = timezone.now() - timedelta(minutes=6)
        state.save()
        self.run_command()
        self.post.assert_called_once()

    def test_failed_request_stays_pending_and_hides_the_url(self):
        self.post.side_effect = requests.ConnectionError("boom")
        with self.assertLogs("events.management.commands.trigger_site_rebuild", "WARNING") as logs:
            output = self.run_command()
        self.assertEqual(WebsiteRebuildState.load().feed_hash, "")
        self.assertNotIn("test-secret", output + "".join(logs.output))

        # After the window it retries.
        state = WebsiteRebuildState.load()
        state.last_requested_at = timezone.now() - timedelta(minutes=6)
        state.save()
        self.post.side_effect = None
        self.run_command()
        self.assertTrue(WebsiteRebuildState.load().feed_hash)

    @override_settings(WEBSITE_DEPLOY_HOOK_URL="")
    def test_missing_hook_is_a_no_op(self):
        self.run_command()
        self.post.assert_not_called()
        self.assertFalse(WebsiteRebuildState.objects.exists())

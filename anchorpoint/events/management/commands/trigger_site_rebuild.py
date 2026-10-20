"""Rebuild the church website when the public events feed changes.

Run every minute by the cron sidecar. Hashes the same payload /events/feed.json
serves; when it differs from the last rebuild and the debounce window has
passed, POSTs WEBSITE_DEPLOY_HOOK_URL. Comparing the feed (rather than hooking
model saves) catches every visible change, including admin/shell edits and an
occurrence slipping into the past, and ignores saves that change nothing public.
"""
import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from events import feeds
from events.models import WebsiteRebuildState
from messaging.services import get_site_base_url

logger = logging.getLogger(__name__)

DEBOUNCE = timedelta(minutes=5)
TIMEOUT_SECONDS = 10


class Command(BaseCommand):
    help = "POST the website's deploy hook if the public events feed changed (debounced)."

    def handle(self, *args, **options):
        hook = getattr(settings, "WEBSITE_DEPLOY_HOOK_URL", "")
        if not hook:
            return  # Not configured: nothing to do.

        base = get_site_base_url() or ""
        current = feeds.feed_hash(feeds.feed_items(lambda path: f"{base}{path}"))
        now = timezone.now()

        with transaction.atomic():
            state = WebsiteRebuildState.objects.select_for_update().get_or_create(pk=1)[0]
            if state.feed_hash == current:
                return
            if state.last_requested_at and now - state.last_requested_at < DEBOUNCE:
                return  # Changed, but rebuilt recently; the next run after the window picks it up.

            # Record the attempt either way so a failing hook retries once per window,
            # not every minute. The hash only advances on success.
            state.last_requested_at = now
            try:
                response = requests.post(hook, timeout=TIMEOUT_SECONDS)
                response.raise_for_status()
            except requests.RequestException as exc:
                # Never log the URL: it is the secret.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                logger.warning("Website rebuild request failed (%s); will retry.", status or type(exc).__name__)
                state.save(update_fields=["last_requested_at"])
                self.stderr.write("Website rebuild request failed; will retry.")
                return

            state.feed_hash = current
            state.save(update_fields=["feed_hash", "last_requested_at"])
        self.stdout.write("Website rebuild requested (events feed changed).")

"""Daily system health check (core/management/commands/system_health.py)."""
import json
import os
import tempfile
from collections import namedtuple
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from checkin.models import PrintAgent
from core.management.commands import system_health
from core.models import OrganizationSettings, UserProfile

Usage = namedtuple("Usage", "total used free")
HEALTHY_DISK = Usage(100 * 2**30, 40 * 2**30, 60 * 2**30)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SystemHealthTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="ops", email="ops@example.com", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        OrganizationSettings.load().maintenance_alert_recipients.add(self.admin)
        mail.outbox.clear()
        self.now = timezone.now()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "status.json")
        self._write_host()
        p1 = mock.patch.object(system_health, "HOST_STATUS_PATH", self.path)
        p2 = mock.patch.object(system_health.shutil, "disk_usage", return_value=HEALTHY_DISK)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def _write_host(self, **overrides):
        ts = self.now.timestamp()
        status = {
            "generated_at": ts, "reboot_required": False, "reboot_required_since": 0,
            "updates_pending": 3, "security_updates_pending": 0, "disk_used_pct": 40,
            "disk_free_gb": 33, "latest_backup_at": ts - 3600,
            "latest_backup_bytes": 80_000_000, "uptime_days": 2,
        }
        status.update(overrides)
        with open(self.path, "w") as fh:
            json.dump(status, fh)

    def _run(self, when=None):
        out = StringIO()
        with mock.patch.object(system_health.timezone, "now", return_value=when or self.now):
            call_command("system_health", stdout=out)
        return out.getvalue()

    def _a_tuesday(self):
        d = timezone.localtime(self.now)
        return self.now + timedelta(days=(1 - d.weekday()) % 7)

    def test_all_good_sends_nothing_midweek(self):
        when = self._a_tuesday()
        self._write_host(generated_at=when.timestamp(), latest_backup_at=when.timestamp() - 3600)
        self._run(when)
        self.assertEqual(len(mail.outbox), 0)

    def test_monday_all_clear(self):
        d = timezone.localtime(self.now)
        monday = self.now + timedelta(days=(0 - d.weekday()) % 7)
        self._write_host(generated_at=monday.timestamp(), latest_backup_at=monday.timestamp() - 3600)
        self._run(monday)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("all good", mail.outbox[0].subject)

    def test_problems_are_emailed(self):
        ts = self.now.timestamp()
        self._write_host(
            reboot_required=True, reboot_required_since=ts - 10 * 86400,
            security_updates_pending=2, latest_backup_at=ts - 30 * 3600,
        )
        with mock.patch.object(system_health.shutil, "disk_usage",
                               return_value=Usage(100 * 2**30, 85 * 2**30, 15 * 2**30)):
            self._run()
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertEqual(mail.outbox[0].to, ["ops@example.com"])
        for needle in ("85% full", "needed a reboot for 10 days", "2 security update",
                       "backup is 30 hours old"):
            self.assertIn(needle, body)

    def test_recent_reboot_need_is_not_flagged(self):
        self._write_host(reboot_required=True, reboot_required_since=self.now.timestamp() - 86400)
        issues = system_health.collect_issues(self.now)
        self.assertFalse(any("reboot" in i for i in issues))

    def test_missing_or_stale_host_status(self):
        os.remove(self.path)
        self.assertTrue(any("missing" in i for i in system_health.collect_issues(self.now)))
        self._write_host(generated_at=self.now.timestamp() - 5 * 3600)
        self.assertTrue(any("hasn't updated" in i for i in system_health.collect_issues(self.now)))

    def test_quiet_print_agent_flagged(self):
        agent = PrintAgent.objects.create(name="Old Zebra", token_hash="abc",
                                          last_seen_at=self.now - timedelta(days=30))
        self.assertTrue(any("Old Zebra" in i for i in system_health.collect_issues(self.now)))
        agent.is_active = False
        agent.save()
        self.assertFalse(any("Old Zebra" in i for i in system_health.collect_issues(self.now)))

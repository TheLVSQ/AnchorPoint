"""Daily system health check, emailed to Org Settings > Maintenance Alerts.

Sends only when something needs attention, plus a short all-clear on Mondays
so a silent inbox can't hide a dead check. Run daily by the cron sidecar.

Host-level facts (reboot needed, apt updates, backups) come from
/hoststatus/status.json, written by docker/hoststatus.sh on the droplet.
"""
import json
import os
import shutil
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

HOST_STATUS_PATH = os.getenv("HOST_STATUS_PATH", "/hoststatus/status.json")

DISK_WARN_PCT = 80
BACKUP_MAX_AGE_H = 26
HOST_STATUS_MAX_AGE_H = 3
REBOOT_GRACE_DAYS = 8      # weekly Tuesday reboot should clear it well within this
AGENT_QUIET_DAYS = 7


def collect_issues(now=None):
    """Return a list of human-readable problems (empty = all good)."""
    now = now or timezone.now()
    issues = []

    # Disk (the container's / is the droplet's root filesystem).
    try:
        usage = shutil.disk_usage("/")
        pct = round(100 * usage.used / usage.total)
        if pct >= DISK_WARN_PCT:
            issues.append(f"Disk is {pct}% full ({usage.free // 2**30} GB free).")
    except OSError:
        pass

    # Host status from the droplet.
    host = _read_host_status()
    if host is None:
        issues.append("Host status file is missing — the droplet's hoststatus cron may not be installed.")
    else:
        age_h = (now.timestamp() - host.get("generated_at", 0)) / 3600
        if age_h > HOST_STATUS_MAX_AGE_H:
            issues.append(f"Host status hasn't updated in {age_h:.0f} hours (hoststatus cron stopped?).")
        if host.get("reboot_required"):
            waited = (now.timestamp() - host.get("reboot_required_since", 0)) / 86400
            if waited > REBOOT_GRACE_DAYS:
                issues.append(f"The droplet has needed a reboot for {waited:.0f} days "
                              "(the weekly Tuesday reboot isn't happening).")
        if host.get("security_updates_pending", 0) > 0:
            issues.append(f"{host['security_updates_pending']} security update(s) are waiting on the droplet.")
        backup_at = host.get("latest_backup_at", 0)
        if not backup_at:
            issues.append("No database backups found on the droplet.")
        else:
            backup_age_h = (now.timestamp() - backup_at) / 3600
            if backup_age_h > BACKUP_MAX_AGE_H:
                issues.append(f"The last database backup is {backup_age_h:.0f} hours old (expected daily).")
            elif host.get("latest_backup_bytes", 0) < 1024:
                issues.append("The latest database backup is nearly empty — pg_dump may be failing.")

    # Print agents that are active but have gone quiet.
    from checkin.models import PrintAgent
    quiet_cutoff = now - timedelta(days=AGENT_QUIET_DAYS)
    for agent in PrintAgent.objects.filter(is_active=True).exclude(token_hash=""):
        if agent.last_seen_at is None or agent.last_seen_at < quiet_cutoff:
            seen = agent.last_seen_at.strftime("%b %-d") if agent.last_seen_at else "never"
            issues.append(f"Print agent \"{agent.name}\" hasn't checked in since {seen} "
                          "(offline, or deactivate it on the Print Agents page if retired).")

    # Failed communications in the last day.
    from messaging.models import PhoneBlast, SmsMessage
    day_ago = now - timedelta(days=1)
    failed_blasts = PhoneBlast.objects.filter(status=PhoneBlast.Status.FAILED, updated_at__gte=day_ago).count()
    failed_sms = SmsMessage.objects.filter(status=SmsMessage.Status.FAILED, updated_at__gte=day_ago).count()
    if failed_blasts:
        issues.append(f"{failed_blasts} phone blast(s) failed in the last 24 hours.")
    if failed_sms:
        issues.append(f"{failed_sms} SMS message(s) failed in the last 24 hours.")

    return issues


def _read_host_status():
    try:
        with open(HOST_STATUS_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _recipients():
    from core.models import OrganizationSettings
    return [
        u.email for u in OrganizationSettings.load().maintenance_alert_recipients.filter(is_active=True)
        if u.email
    ]


class Command(BaseCommand):
    help = "Check disk, backups, host updates, print agents and messaging; email problems."

    def add_arguments(self, parser):
        parser.add_argument("--force-email", action="store_true",
                            help="Email the result even if everything is fine.")

    def handle(self, *args, **opts):
        now = timezone.now()
        issues = collect_issues(now)
        weekly_all_clear = timezone.localtime(now).weekday() == 0  # Monday
        host = _read_host_status() or {}

        if issues:
            subject = f"AnchorPoint: {len(issues)} item(s) need attention"
            body = "The daily health check found:\n\n" + "\n".join(f"- {i}" for i in issues)
        elif weekly_all_clear or opts["force_email"]:
            subject = "AnchorPoint weekly health check: all good"
            body = "Everything checked out."
        else:
            self.stdout.write("Health check: all good (no email).")
            return

        body += (
            "\n\nServer snapshot: "
            f"disk {host.get('disk_used_pct', '?')}% used, "
            f"{host.get('updates_pending', '?')} package update(s) pending, "
            f"up {host.get('uptime_days', '?')} days."
            "\n\nAdjust who gets this under Settings > Organization > Maintenance Alerts."
        )
        recipients = _recipients()
        if recipients:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
        self.stdout.write(f"{subject} -> {len(recipients)} recipient(s)")
        for issue in issues:
            self.stdout.write(f"  - {issue}")

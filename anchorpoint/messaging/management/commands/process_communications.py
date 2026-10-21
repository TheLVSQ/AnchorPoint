from django.core.management.base import BaseCommand

from messaging import outbound


class Command(BaseCommand):
    help = "Send every broadcast (SMS / phone blast) that is due. Run each minute by cron."

    def handle(self, *args, **options):
        report = outbound.dispatch_due()
        if report.stale_calls:
            self.stdout.write(f"Settled {report.stale_calls} call(s) with no status callback.")
        if report.deferred:
            self.stdout.write(f"Inside blackout window; holding {report.deferred} broadcast(s).")
        for comm in report.sent:
            self.stdout.write(f"Delivered {comm.get_channel_display()} #{comm.pk}")
        for comm in report.failed:
            self.stderr.write(f"Failed to deliver {comm.get_channel_display()} #{comm.pk}")

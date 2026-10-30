from django.core.management.base import BaseCommand

from scheduling import requests


class Command(BaseCommand):
    help = "Email due schedule requests and serving reminders. Run each minute by cron."

    def handle(self, *args, **options):
        sent, reminded = requests.send_due()
        if sent:
            self.stdout.write(f"Sent {sent} schedule request email(s).")
        if reminded:
            self.stdout.write(f"Sent {reminded} serving reminder email(s).")

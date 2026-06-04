"""Reset passwords for one or more users to fresh random values.

    python manage.py rotate_passwords admin tester1 tester2
    python manage.py rotate_passwords --all-staff

New passwords are printed once. Use after a credential exposure, or to reset a
staff member who has been locked out.
"""

import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import UserProfile

User = get_user_model()

STAFF_ROLES = [
    UserProfile.Role.ADMIN,
    UserProfile.Role.STAFF,
    UserProfile.Role.VOLUNTEER_ADMIN,
]


def generate_password(length=16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "Reset passwords for the named users (or all staff) to fresh random values."

    def add_arguments(self, parser):
        parser.add_argument("usernames", nargs="*", help="Usernames to rotate.")
        parser.add_argument(
            "--all-staff",
            action="store_true",
            help="Rotate every admin / staff / volunteer-admin account.",
        )

    def handle(self, *args, **options):
        usernames = options["usernames"]
        all_staff = options["all_staff"]
        if not usernames and not all_staff:
            raise CommandError("Provide one or more usernames, or --all-staff.")

        if all_staff:
            users = list(User.objects.filter(profile__role__in=STAFF_ROLES))
        else:
            users = list(User.objects.filter(username__in=usernames))
            found = {u.username for u in users}
            for name in sorted(set(usernames) - found):
                self.stdout.write(self.style.WARNING(f"  {name}: no such user, skipped"))

        if not users:
            self.stdout.write("No matching users; nothing rotated.")
            return

        rotated = []
        for user in users:
            pw = generate_password()
            user.set_password(pw)
            user.save(update_fields=["password"])
            rotated.append((user.username, pw))

        self.stdout.write(self.style.SUCCESS("Rotated passwords (save these now):"))
        for name, pw in sorted(rotated):
            self.stdout.write(f"  {name} -> {pw}")

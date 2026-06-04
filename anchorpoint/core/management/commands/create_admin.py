"""Create or promote an AnchorPoint admin account.

Use this to bootstrap your own admin after deployment instead of relying on a
seeded account with a known password. Idempotent: if the user already exists it
is promoted to admin (and its password reset only if you pass --password).

    python manage.py create_admin --username you@church.org --email you@church.org
    python manage.py create_admin --username you --password 'choose-your-own' --name "Jane Doe"

With no --password, a strong password is generated and printed once.
"""

import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import UserProfile

User = get_user_model()


def generate_password(length=16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "Create or promote a user to AnchorPoint admin (staff + superuser + ADMIN role)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument(
            "--password",
            default=None,
            help="Password to set. If omitted, a strong one is generated and printed "
            "(for a new user) or the existing password is left unchanged.",
        )
        parser.add_argument("--name", default="", help='Full name, e.g. "Jane Doe".')

    def handle(self, *args, **options):
        username = options["username"].strip()
        email = options["email"].strip()
        password = options["password"]
        name = options["name"].strip()

        user, created = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )

        generated = False
        if password is None and created:
            password = generate_password()
            generated = True

        if email and not user.email:
            user.email = email
        if name:
            first, _, last = name.partition(" ")
            user.first_name = first
            user.last_name = last
        user.is_staff = True
        user.is_superuser = True
        if password is not None:
            user.set_password(password)
        user.save()

        # Profile is auto-created by a post_save signal; get_or_create guards
        # against any legacy user that somehow lacks one.
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = UserProfile.Role.ADMIN
        profile.can_manage_communications = True
        profile.save()

        action = "Created" if created else "Promoted existing user to"
        self.stdout.write(self.style.SUCCESS(f"{action} admin: {username}"))
        if generated:
            self.stdout.write(self.style.WARNING(f"Generated password: {password}"))
            self.stdout.write("Save it now — it will not be shown again.")
        elif password is not None:
            self.stdout.write("Password set.")
        else:
            self.stdout.write("Existing password left unchanged (pass --password to reset it).")

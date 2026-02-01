"""
Management command to create beta test users for AnchorPoint.

Usage:
    python manage.py setup_beta_users

This creates:
    - An admin user (if none exists)
    - Two staff users for beta testing
"""

import secrets
import string
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import UserProfile


User = get_user_model()


def generate_password(length=12):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "Create beta test users for AnchorPoint"

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-username",
            default="admin",
            help="Username for admin account (default: admin)",
        )
        parser.add_argument(
            "--admin-email",
            default="admin@example.com",
            help="Email for admin account",
        )
        parser.add_argument(
            "--tester1-username",
            default="tester1",
            help="Username for first tester (default: tester1)",
        )
        parser.add_argument(
            "--tester1-email",
            default="tester1@example.com",
            help="Email for first tester",
        )
        parser.add_argument(
            "--tester2-username",
            default="tester2",
            help="Username for second tester (default: tester2)",
        )
        parser.add_argument(
            "--tester2-email",
            default="tester2@example.com",
            help="Email for second tester",
        )

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("AnchorPoint Beta User Setup")
        self.stdout.write("=" * 60 + "\n")

        created_users = []

        # Create admin user
        admin_username = options["admin_username"]
        admin_email = options["admin_email"]
        admin_user, admin_created = User.objects.get_or_create(
            username=admin_username,
            defaults={
                "email": admin_email,
                "first_name": "Admin",
                "last_name": "User",
                "is_staff": True,
                "is_superuser": True,
            },
        )

        if admin_created:
            admin_password = generate_password()
            admin_user.set_password(admin_password)
            admin_user.save()
            # Profile is auto-created by signal, update role
            admin_user.profile.role = UserProfile.Role.ADMIN
            admin_user.profile.can_manage_communications = True
            admin_user.profile.save()
            created_users.append(("ADMIN", admin_username, admin_password, admin_email))
            self.stdout.write(self.style.SUCCESS(f"Created admin user: {admin_username}"))
        else:
            self.stdout.write(self.style.WARNING(f"Admin user '{admin_username}' already exists - skipped"))

        # Create tester 1 (Staff role)
        tester1_username = options["tester1_username"]
        tester1_email = options["tester1_email"]
        tester1, tester1_created = User.objects.get_or_create(
            username=tester1_username,
            defaults={
                "email": tester1_email,
                "first_name": "Beta",
                "last_name": "Tester One",
            },
        )

        if tester1_created:
            tester1_password = generate_password()
            tester1.set_password(tester1_password)
            tester1.save()
            tester1.profile.role = UserProfile.Role.STAFF
            tester1.profile.can_manage_communications = True
            tester1.profile.save()
            created_users.append(("STAFF", tester1_username, tester1_password, tester1_email))
            self.stdout.write(self.style.SUCCESS(f"Created staff user: {tester1_username}"))
        else:
            self.stdout.write(self.style.WARNING(f"User '{tester1_username}' already exists - skipped"))

        # Create tester 2 (Staff role)
        tester2_username = options["tester2_username"]
        tester2_email = options["tester2_email"]
        tester2, tester2_created = User.objects.get_or_create(
            username=tester2_username,
            defaults={
                "email": tester2_email,
                "first_name": "Beta",
                "last_name": "Tester Two",
            },
        )

        if tester2_created:
            tester2_password = generate_password()
            tester2.set_password(tester2_password)
            tester2.save()
            tester2.profile.role = UserProfile.Role.STAFF
            tester2.profile.can_manage_communications = True
            tester2.profile.save()
            created_users.append(("STAFF", tester2_username, tester2_password, tester2_email))
            self.stdout.write(self.style.SUCCESS(f"Created staff user: {tester2_username}"))
        else:
            self.stdout.write(self.style.WARNING(f"User '{tester2_username}' already exists - skipped"))

        # Print credentials summary
        if created_users:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.WARNING("SAVE THESE CREDENTIALS - THEY WON'T BE SHOWN AGAIN!"))
            self.stdout.write("=" * 60 + "\n")

            for role, username, password, email in created_users:
                self.stdout.write(f"  Role:     {role}")
                self.stdout.write(f"  Username: {username}")
                self.stdout.write(f"  Password: {password}")
                self.stdout.write(f"  Email:    {email}")
                self.stdout.write("-" * 40)

            self.stdout.write("\n" + self.style.SUCCESS("Beta users setup complete!"))
        else:
            self.stdout.write("\n" + self.style.WARNING("No new users created - all already exist."))

        self.stdout.write("")

"""Enforce case-insensitive uniqueness of non-blank User emails.

The app authenticates by email (login_view / google_auth_callback look users up
via email), so duplicate emails break login. Django's default auth.User does not
constrain email, so this adds a partial, case-insensitive unique index directly
on auth_user. Blank emails are exempt (multiple users may have no email).

NOTE: this CREATE will fail if duplicate non-blank emails already exist. Resolve
duplicates first (see the rotate/dedup tooling) before applying.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_userprofile_person_link"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS uniq_auth_user_email_ci "
                "ON auth_user (LOWER(email)) WHERE email <> '';"
            ),
            reverse_sql="DROP INDEX IF EXISTS uniq_auth_user_email_ci;",
        ),
    ]

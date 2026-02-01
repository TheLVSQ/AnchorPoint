import re

from django.db import migrations, models


def normalize_phone(phone: str) -> str:
    """Strip all non-digit characters from a phone number."""
    return re.sub(r"\D+", "", phone or "")


def populate_normalized_phone(apps, schema_editor):
    """Backfill normalized_phone for all existing Person records."""
    Person = apps.get_model("people", "Person")
    for person in Person.objects.exclude(phone__isnull=True).exclude(phone=""):
        person.normalized_phone = normalize_phone(person.phone)
        person.save(update_fields=["normalized_phone"])


def reverse_populate(apps, schema_editor):
    """Clear normalized_phone (reverse migration)."""
    Person = apps.get_model("people", "Person")
    Person.objects.update(normalized_phone="")


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0003_person_profile_photo_and_address_split"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="normalized_phone",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                help_text="Auto-generated digits-only version of phone for fast lookups.",
                max_length=20,
            ),
        ),
        migrations.RunPython(populate_normalized_phone, reverse_populate),
    ]

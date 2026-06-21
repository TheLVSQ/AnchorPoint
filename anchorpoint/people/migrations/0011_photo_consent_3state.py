from django.db import migrations, models

CHOICES = [
    ("unknown", "Not asked"),
    ("granted", "Granted"),
    ("denied", "Denied — no photos"),
]
HELP = "Guardian's photo/likeness permission (relevant for minors)."


def to_three_state(apps, schema_editor):
    Person = apps.get_model("people", "Person")
    # Old boolean True (explicit opt-in) -> granted; everything else -> unknown
    # (the old default False meant "not on record", indistinguishable from
    # never-asked, so we don't infer a denial).
    Person.objects.filter(photo_consent=True).update(photo_consent_tmp="granted")


def back(apps, schema_editor):
    Person = apps.get_model("people", "Person")
    Person.objects.filter(photo_consent_tmp="granted").update(photo_consent=True)


class Migration(migrations.Migration):
    dependencies = [("people", "0010_person_external_id")]

    operations = [
        migrations.AddField(
            model_name="person",
            name="photo_consent_tmp",
            field=models.CharField(max_length=10, choices=CHOICES, default="unknown", help_text=HELP),
        ),
        migrations.RunPython(to_three_state, back),
        migrations.RemoveField(model_name="person", name="photo_consent"),
        migrations.RenameField(
            model_name="person", old_name="photo_consent_tmp", new_name="photo_consent"
        ),
    ]

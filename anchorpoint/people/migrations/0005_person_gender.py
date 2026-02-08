from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0004_add_normalized_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[
                    ("male", "Male"),
                    ("female", "Female"),
                    ("other", "Other"),
                    ("unknown", "Prefer not to say"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]

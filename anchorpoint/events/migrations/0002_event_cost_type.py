from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="cost_type",
            field=models.CharField(
                choices=[
                    ("per_person", "Per Person"),
                    ("per_family", "Per Family"),
                    ("per_group", "Per Group"),
                ],
                default="per_person",
                max_length=20,
            ),
        ),
    ]

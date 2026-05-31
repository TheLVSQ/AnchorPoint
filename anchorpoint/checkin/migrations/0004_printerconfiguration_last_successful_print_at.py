from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("checkin", "0003_remove_attendance_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="printerconfiguration",
            name="last_successful_print_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0002_person_additional_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="person",
            name="address",
        ),
        migrations.AddField(
            model_name="person",
            name="address_line1",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="Address line 1"
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="address_line2",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="Address line 2"
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="city",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="postal_code",
            field=models.CharField(
                blank=True, max_length=20, null=True, verbose_name="ZIP / Postal Code"
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="profile_photo",
            field=models.ImageField(
                blank=True, null=True, upload_to="people/photos/"
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="state",
            field=models.CharField(blank=True, max_length=80, null=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_organizationsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationsettings",
            name="logo",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="organization/logo/",
            ),
        ),
    ]

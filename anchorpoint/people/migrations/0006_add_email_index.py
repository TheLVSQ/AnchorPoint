from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0005_person_gender"),
    ]

    operations = [
        migrations.AlterField(
            model_name="person",
            name="email",
            field=models.EmailField(blank=True, db_index=True, max_length=254, null=True),
        ),
    ]

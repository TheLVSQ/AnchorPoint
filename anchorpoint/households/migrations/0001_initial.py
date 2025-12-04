from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("people", "0003_person_profile_photo_and_address_split"),
    ]

    operations = [
        migrations.CreateModel(
            name="Household",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("phone", models.CharField(blank=True, max_length=50, null=True)),
                (
                    "address_line1",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "address_line2",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("city", models.CharField(blank=True, max_length=120, null=True)),
                ("state", models.CharField(blank=True, max_length=80, null=True)),
                (
                    "postal_code",
                    models.CharField(blank=True, max_length=20, null=True),
                ),
                (
                    "primary_adult",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="primary_households",
                        to="people.person",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HouseholdMember",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "relationship_type",
                    models.CharField(
                        choices=[
                            ("adult", "Adult"),
                            ("child", "Child"),
                            ("student", "Student"),
                            ("other", "Other"),
                        ],
                        default="adult",
                        max_length=20,
                    ),
                ),
                (
                    "household",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="households.household",
                    ),
                ),
                (
                    "person",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="household_memberships",
                        to="people.person",
                    ),
                ),
            ],
            options={
                "ordering": ["household__name", "person__last_name"],
                "unique_together": {("household", "person")},
            },
        ),
        migrations.AddField(
            model_name="household",
            name="members",
            field=models.ManyToManyField(
                blank=True,
                related_name="households",
                through="households.HouseholdMember",
                to="people.person",
            ),
        ),
    ]

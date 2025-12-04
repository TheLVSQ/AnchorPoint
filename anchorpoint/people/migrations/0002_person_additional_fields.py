from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="address",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="allergies",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="baptism_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="first_visit_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="grade",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pre-k", "Pre-K"),
                    ("k", "Kindergarten"),
                    ("1", "1st Grade"),
                    ("2", "2nd Grade"),
                    ("3", "3rd Grade"),
                    ("4", "4th Grade"),
                    ("5", "5th Grade"),
                    ("6", "6th Grade"),
                    ("7", "7th Grade"),
                    ("8", "8th Grade"),
                    ("9", "9th Grade"),
                    ("10", "10th Grade"),
                    ("11", "11th Grade"),
                    ("12", "12th Grade"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="marital_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("single", "Single"),
                    ("married", "Married"),
                    ("engaged", "Engaged"),
                    ("separated", "Separated"),
                    ("divorced", "Divorced"),
                    ("widowed", "Widowed"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="phone_opt_in",
            field=models.BooleanField(
                default=True,
                help_text="Can this person receive text messages at their phone number?",
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="salvation_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="security_notes",
            field=models.TextField(blank=True, null=True),
        ),
    ]

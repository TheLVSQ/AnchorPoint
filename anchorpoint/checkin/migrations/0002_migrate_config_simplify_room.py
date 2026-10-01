from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("checkin", "0001_initial"),
        ("groups", "0002_groupmembership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- CheckInConfiguration ---
        migrations.CreateModel(
            name="CheckInConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
                ("description", models.TextField(blank=True)),
                ("welcome_message", models.CharField(blank=True, max_length=255)),
                ("location_name", models.CharField(blank=True, max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("min_age", models.PositiveIntegerField(blank=True, null=True)),
                ("max_age", models.PositiveIntegerField(blank=True, null=True)),
                ("min_grade", models.CharField(
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
                )),
                ("max_grade", models.CharField(
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
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("groups", models.ManyToManyField(
                    blank=True,
                    related_name="checkin_app_configurations",
                    to="groups.group",
                )),
                ("rooms", models.ManyToManyField(
                    blank=True,
                    related_name="configurations",
                    to="checkin.room",
                )),
            ],
            options={
                "ordering": ["name"],
            },
        ),

        # --- CheckInWindow ---
        migrations.CreateModel(
            name="CheckInWindow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("schedule_type", models.CharField(
                    choices=[("weekly", "Recurring (weekly)"), ("specific_date", "Specific date")],
                    default="weekly",
                    max_length=20,
                )),
                ("day_of_week", models.IntegerField(
                    blank=True,
                    choices=[
                        (0, "Sunday"),
                        (1, "Monday"),
                        (2, "Tuesday"),
                        (3, "Wednesday"),
                        (4, "Thursday"),
                        (5, "Friday"),
                        (6, "Saturday"),
                    ],
                    null=True,
                )),
                ("specific_date", models.DateField(blank=True, null=True)),
                ("checkin_opens", models.TimeField()),
                ("event_starts", models.TimeField()),
                ("checkin_closes", models.TimeField()),
                ("event_ends", models.TimeField()),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.CharField(blank=True, max_length=120)),
                ("configuration", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="windows",
                    to="checkin.checkinconfiguration",
                )),
            ],
            options={
                "ordering": ["schedule_type", "specific_date", "day_of_week", "checkin_opens"],
            },
        ),

        # --- Room: remove age/grade fields ---
        migrations.RemoveField(model_name="room", name="min_age"),
        migrations.RemoveField(model_name="room", name="max_age"),
        migrations.RemoveField(model_name="room", name="min_grade"),
        migrations.RemoveField(model_name="room", name="max_grade"),

        # --- CheckInSession: rename start_time -> checkin_opens, end_time -> checkin_closes ---
        migrations.RenameField(
            model_name="checkinsession",
            old_name="start_time",
            new_name="checkin_opens",
        ),
        migrations.RenameField(
            model_name="checkinsession",
            old_name="end_time",
            new_name="checkin_closes",
        ),

        # --- CheckInSession: add event_starts and event_ends ---
        migrations.AddField(
            model_name="checkinsession",
            name="event_starts",
            field=models.TimeField(default="00:00"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="checkinsession",
            name="event_ends",
            field=models.TimeField(default="23:59"),
            preserve_default=False,
        ),

        # --- CheckInSession: add configuration and window FKs ---
        migrations.AddField(
            model_name="checkinsession",
            name="configuration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sessions",
                to="checkin.checkinconfiguration",
            ),
        ),
        migrations.AddField(
            model_name="checkinsession",
            name="window",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sessions",
                to="checkin.checkinwindow",
            ),
        ),

        # --- CheckInSession: update Meta ordering ---
        migrations.AlterModelOptions(
            name="checkinsession",
            options={"ordering": ["-date", "-checkin_opens"]},
        ),

        # --- CheckIn: update security_code max_length and related_names ---
        migrations.AlterField(
            model_name="checkin",
            name="security_code",
            field=models.CharField(max_length=4),
        ),
        migrations.AlterField(
            model_name="checkin",
            name="checked_in_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="checked_in_by",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="checkin",
            name="checked_out_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="checked_out_by",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Remove room's related_name="checkins" (now no related_name = default "checkin_set")
        migrations.AlterField(
            model_name="checkin",
            name="room",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="checkin.room",
            ),
        ),
        # Remove unique_together constraint
        migrations.AlterUniqueTogether(
            name="checkin",
            unique_together=set(),
        ),

        # --- PrinterConfiguration: replace old fields with new schema ---
        migrations.RemoveField(model_name="printerconfiguration", name="printer_type"),
        migrations.RemoveField(model_name="printerconfiguration", name="connection_string"),
        migrations.RemoveField(model_name="printerconfiguration", name="label_width_mm"),
        migrations.RemoveField(model_name="printerconfiguration", name="label_height_mm"),
        migrations.RemoveField(model_name="printerconfiguration", name="dpi"),
        migrations.AddField(
            model_name="printerconfiguration",
            name="printer_type",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="printerconfiguration",
            name="connection_type",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="printerconfiguration",
            name="host",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="printerconfiguration",
            name="port",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name="printerconfiguration",
            options={},
        ),

        # --- LabelTemplate: replace old fields with new schema ---
        migrations.RemoveField(model_name="labeltemplate", name="label_type"),
        migrations.RemoveField(model_name="labeltemplate", name="template_json"),
        migrations.RemoveField(model_name="labeltemplate", name="is_default"),
        migrations.AddField(
            model_name="labeltemplate",
            name="width_mm",
            field=models.PositiveIntegerField(default=62),
        ),
        migrations.AddField(
            model_name="labeltemplate",
            name="height_mm",
            field=models.PositiveIntegerField(default=76),
        ),
        migrations.AddField(
            model_name="labeltemplate",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterModelOptions(
            name="labeltemplate",
            options={},
        ),
    ]

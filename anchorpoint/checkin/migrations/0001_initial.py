from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("people", "0005_person_gender"),
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Room",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("building", models.CharField(blank=True, max_length=100)),
                ("capacity", models.PositiveIntegerField(blank=True, null=True)),
                ("min_age", models.PositiveIntegerField(blank=True, null=True)),
                ("max_age", models.PositiveIntegerField(blank=True, null=True)),
                ("min_grade", models.CharField(blank=True, max_length=20)),
                ("max_grade", models.CharField(blank=True, max_length=20)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="CheckInSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("date", models.DateField()),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="events.event")),
                ("rooms", models.ManyToManyField(blank=True, to="checkin.room")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-date", "-start_time"],
            },
        ),
        migrations.CreateModel(
            name="CheckIn",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("security_code", models.CharField(db_index=True, max_length=8)),
                ("checked_in_at", models.DateTimeField(auto_now_add=True)),
                ("checked_out_at", models.DateTimeField(blank=True, null=True)),
                ("child_label_printed", models.BooleanField(default=False)),
                ("parent_label_printed", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checkins", to="checkin.checkinsession")),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checkins", to="people.person")),
                ("room", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="checkins", to="checkin.room")),
                ("checked_in_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="checkins_performed", to=settings.AUTH_USER_MODEL)),
                ("checked_out_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="checkouts_performed", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-checked_in_at"],
                "unique_together": {("session", "person")},
            },
        ),
        migrations.CreateModel(
            name="PrinterConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("printer_type", models.CharField(choices=[("escpos", "ESC/POS (Generic Thermal)"), ("brother", "Brother QL Series"), ("cups", "CUPS/System Printer"), ("zpl", "Zebra (ZPL)")], max_length=20)),
                ("connection_string", models.CharField(max_length=255)),
                ("label_width_mm", models.PositiveIntegerField(default=62)),
                ("label_height_mm", models.PositiveIntegerField(blank=True, help_text="Leave blank for continuous roll", null=True)),
                ("dpi", models.PositiveIntegerField(default=203)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Printer Configuration",
                "verbose_name_plural": "Printer Configurations",
            },
        ),
        migrations.CreateModel(
            name="LabelTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("label_type", models.CharField(choices=[("child", "Child Name Tag"), ("parent", "Parent Claim Tag"), ("allergy", "Allergy Alert"), ("visitor", "Visitor Badge")], max_length=20)),
                ("template_json", models.JSONField(default=dict)),
                ("is_default", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ["label_type", "name"],
            },
        ),
    ]

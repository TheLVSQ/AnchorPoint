import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("slug", models.SlugField(blank=True, unique=True, max_length=255)),
                ("summary", models.CharField(blank=True, help_text="Short teaser used on cards and embeds.", max_length=300)),
                ("description", models.TextField(blank=True)),
                ("location_name", models.CharField(blank=True, max_length=255)),
                ("location_address_line1", models.CharField(blank=True, max_length=255)),
                ("location_address_line2", models.CharField(blank=True, max_length=255)),
                ("location_city", models.CharField(blank=True, max_length=120)),
                ("location_state", models.CharField(blank=True, max_length=80)),
                ("location_postal_code", models.CharField(blank=True, max_length=20)),
                ("location_notes", models.TextField(blank=True)),
                ("contact_name", models.CharField(blank=True, max_length=255)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("contact_phone", models.CharField(blank=True, max_length=50)),
                ("is_free", models.BooleanField(default=True)),
                ("cost_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("registration_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("registration_deadline", models.DateTimeField(blank=True, null=True)),
                ("registration_capacity", models.PositiveIntegerField(blank=True, help_text="Optional cap on total registrations.", null=True)),
                ("registration_open", models.BooleanField(default=True)),
                ("is_published", models.BooleanField(default=True, help_text="Unpublished events stay hidden from public pages.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["title"],
            },
        ),
        migrations.CreateModel(
            name="EventPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="events/photos/")),
                ("caption", models.CharField(blank=True, max_length=255)),
                ("display_order", models.PositiveIntegerField(default=0)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="photos", to="events.event")),
            ],
            options={
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="EventOccurrence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("is_all_day", models.BooleanField(default=False)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="occurrences", to="events.event")),
            ],
            options={
                "ordering": ["starts_at"],
            },
        ),
        migrations.CreateModel(
            name="EventRegistration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_name", models.CharField(max_length=120)),
                ("last_name", models.CharField(max_length=120)),
                ("email", models.EmailField(max_length=254)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("number_of_attendees", models.PositiveIntegerField(default=1)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="registrations", to="events.event")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]

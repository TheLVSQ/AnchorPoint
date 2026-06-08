from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("checkin", "0005_checkinsession_uniq_session_per_config_window_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrintAgent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("token_hash", models.CharField(blank=True, max_length=64)),
                ("pairing_code", models.CharField(blank=True, db_index=True, max_length=12)),
                ("pairing_expires_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="PrintJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image_data", models.BinaryField()),
                ("kind", models.CharField(default="label", max_length=20)),
                ("description", models.CharField(blank=True, max_length=200)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("claimed", "Claimed"), ("printed", "Printed"), ("failed", "Failed")], default="pending", max_length=12)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("printed_at", models.DateTimeField(blank=True, null=True)),
                ("agent", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="jobs", to="checkin.printagent")),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="printjob",
            index=models.Index(fields=["agent", "status", "created_at"], name="ck_printjob_agent_status_idx"),
        ),
    ]

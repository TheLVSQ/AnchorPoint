from django.apps import AppConfig


class ReportingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reporting"

    def ready(self):
        # Import so the @register decorators populate the report registry.
        from . import reports  # noqa: F401

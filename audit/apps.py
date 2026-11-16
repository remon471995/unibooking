from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit"
    verbose_name = "سجل التعديلات"

    def ready(self):
        from . import signals
        signals.connect_signals()

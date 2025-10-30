from __future__ import annotations
from django.apps import AppConfig

class HelpdeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "helpdesk"
    verbose_name = "Helpdesk"

    def ready(self):
        # ربط إشعارات البريد وغيرها
        from . import signals  # noqa: F401

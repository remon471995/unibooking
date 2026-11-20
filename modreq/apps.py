from django.apps import AppConfig


class ModreqConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modreq"
    verbose_name = "طلبات التعديل"

    def ready(self):
        # بيحوّل شاشات "طلب تعديل" الثلاثة لنظام الاعتماد (من غير تعديل core/views.py)
        from . import override_views
        override_views.install()

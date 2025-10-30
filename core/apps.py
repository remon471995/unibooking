# core/apps.py
from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # تحميل إشارات المشروع (إنشاء EmployeeProfile تلقائيًا، إلخ)
        from . import signals  # noqa

        # محاولة تهيئة الجروبات الأساسية وربط الصلاحيات (مرة عند الإقلاع)
        # لو وقت المايجريشن/قاعدة البيانات مش جاهزة هنتجاهل بهدوء.
        try:
            signals.ensure_base_groups()
        except Exception:
            # يفضّل تسجيل لوج بدل الـ pass لو عايز تتتبع الأعطال
            pass

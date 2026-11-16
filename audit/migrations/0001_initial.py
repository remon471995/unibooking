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
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="الوقت")),
                ("user_repr", models.CharField(blank=True, max_length=150, verbose_name="اسم المستخدم")),
                ("action", models.CharField(choices=[("create", "إنشاء"), ("update", "تعديل"), ("delete", "حذف")], max_length=10, verbose_name="الإجراء")),
                ("model", models.CharField(db_index=True, max_length=60, verbose_name="النموذج")),
                ("model_label", models.CharField(max_length=100, verbose_name="النوع")),
                ("object_id", models.CharField(db_index=True, max_length=40, verbose_name="رقم السجل")),
                ("object_repr", models.CharField(blank=True, max_length=255, verbose_name="الوصف")),
                ("card_id", models.PositiveBigIntegerField(blank=True, db_index=True, null=True, verbose_name="رقم الكارت")),
                ("changes", models.JSONField(blank=True, default=dict, verbose_name="التغييرات")),
                ("ip", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="المستخدم")),
            ],
            options={
                "verbose_name": "سجل تعديل",
                "verbose_name_plural": "سجل التعديلات",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]

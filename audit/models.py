from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """سجل تعديلات: مين غيّر إيه ومتى وكانت القيمة كام. للقراءة فقط (مش بيتعدّل من التطبيق)."""

    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTIONS = (
        (ACTION_CREATE, "إنشاء"),
        (ACTION_UPDATE, "تعديل"),
        (ACTION_DELETE, "حذف"),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="الوقت")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+", verbose_name="المستخدم",
    )
    user_repr = models.CharField(max_length=150, blank=True, verbose_name="اسم المستخدم")
    action = models.CharField(max_length=10, choices=ACTIONS, verbose_name="الإجراء")
    model = models.CharField(max_length=60, db_index=True, verbose_name="النموذج")
    model_label = models.CharField(max_length=100, verbose_name="النوع")
    object_id = models.CharField(max_length=40, db_index=True, verbose_name="رقم السجل")
    object_repr = models.CharField(max_length=255, blank=True, verbose_name="الوصف")
    # رقم الكارت مخزّن كرقم عادي (مش ForeignKey) عشان السجل يفضل موجود حتى لو الكارت اتمسح
    card_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True, verbose_name="رقم الكارت")
    changes = models.JSONField(default=dict, blank=True, verbose_name="التغييرات")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "سجل تعديل"
        verbose_name_plural = "سجل التعديلات"

    def __str__(self):
        return f"{self.get_action_display()} {self.model_label} #{self.object_id} بواسطة {self.user_repr or 'النظام'}"

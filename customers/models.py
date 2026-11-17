from django.conf import settings
from django.db import models


class CustomerProfile(models.Model):
    """بيانات إضافية للعميل (إيميل / ملاحظات / منع التسويق).

    العميل نفسه مش جدول منفصل: بنجمّع كل الكروت اللي ليها نفس رقم الموبايل (كود الدولة + الرقم)
    في ملف واحد. الـ phone_key هو الرقم بالأرقام بس (مثلاً 96597687778).
    """

    phone_key = models.CharField(max_length=32, unique=True, db_index=True, verbose_name="مفتاح الموبايل")
    email = models.EmailField(blank=True, verbose_name="الإيميل")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    no_marketing = models.BooleanField(default=False, verbose_name="لا يُرسل له تسويق")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+", verbose_name="عدّل بواسطة",
    )

    class Meta:
        verbose_name = "بيانات عميل"
        verbose_name_plural = "بيانات العملاء"

    def __str__(self):
        return f"+{self.phone_key}"

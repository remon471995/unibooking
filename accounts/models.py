from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


def avatar_upload_to(instance, filename):
    # لاحظ المسافة (4 مسافات) قبل return
    return f"avatars/user_{instance.user_id}/{filename}"


class UserProfile(models.Model):
    DEPARTMENTS = [
        ("sales", "المبيعات"),
        ("cs", "خدمة العملاء"),
        ("ops", "الأوبريشن"),
        ("accounts", "الحسابات"),
        ("hr", "الموارد البشرية"),
        ("it", "IT"),
        ("other", "أخرى"),
    ]

    ROLE_CHOICES = [
        ("admin", "مدير"),
        ("leader", "Team Leader"),
        ("agent", "موظف مبيعات"),
        ("other", "أخرى"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    # الحقل الجديد role مع choices و default لتجنب مشاكل عند المايغريشن
    role = models.CharField("الدور", max_length=20, choices=ROLE_CHOICES, default="agent")

    phone = models.CharField("رقم الموبايل", max_length=30, blank=True)
    department = models.CharField("القسم", max_length=20, choices=DEPARTMENTS, blank=True)
    job_title = models.CharField("المسمى الوظيفي", max_length=100, blank=True)
    address = models.CharField("العنوان", max_length=255, blank=True)
    avatar = models.ImageField("الصورة الشخصية", upload_to=avatar_upload_to, blank=True, null=True)
    notes = models.TextField("ملاحظات", blank=True)

    def __str__(self):
        return f"Profile({self.user})"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)

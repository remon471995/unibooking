from django.db import migrations


class Migration(migrations.Migration):
    """
    This migration used to add `transferbooking.booking_code` a second time
    (0028 already adds it or it already exists). SQLite silently tolerated the duplicate, PostgreSQL does not.
    It is intentionally a no-op now; it stays in the chain so later migrations keep working.
    """

    dependencies = [
        ('core', '0028_rename_date_transferbooking_installment_date_and_more'),
    ]

    operations = [
        # تم تعطيل الإضافة لعدم تكرار إنشاء الحقل في قاعدة البيانات
    ]

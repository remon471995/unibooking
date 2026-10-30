from django.db import migrations


class Migration(migrations.Migration):
    """
    This migration used to add `transferbooking.booking_code` a second time
    (0029 already adds it). SQLite silently tolerated the duplicate, PostgreSQL does not.
    It is intentionally a no-op now; it stays in the chain so later migrations keep working.
    """

    dependencies = [
        ('core', '0029_auto_...'), # تأكد من أن الاعتماد على الميجريشن السابق صحيح
    ]

    operations = [
        # تم مسح الـ AddField الخاطئ لأنه موجود مسبقاً في 0029
    ]

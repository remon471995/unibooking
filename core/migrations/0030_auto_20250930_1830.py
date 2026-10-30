from django.db import migrations


class Migration(migrations.Migration):
    """
    This migration used to add `transferbooking.booking_code` a second time
    (0029 already adds it). SQLite silently tolerated the duplicate, PostgreSQL does not.
    It is intentionally a no-op now; it stays in the chain so later migrations keep working.
    """

    operations = [
        migrations.AddField(
            model_name='transferbooking',
            name='booking_code',
            field=models.CharField(max_length=50, unique=True, blank=True, null=True),
        ),
    ]

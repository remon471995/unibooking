from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_transferbooking_booking_code'),  # غير الرقم لو آخر migration مختلف
    ]

    operations = [
        migrations.AddField(
            model_name='transferbooking',
            name='booking_code',
            field=models.CharField(max_length=50, unique=True, blank=True, null=True),
        ),
    ]

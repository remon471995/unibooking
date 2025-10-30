from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_rename_date_transferbooking_installment_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferbooking',
            name='booking_code',
            field=models.CharField(max_length=50, unique=True, null=True, blank=True),
        ),
    ]

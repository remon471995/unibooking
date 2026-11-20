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
            name="ModificationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(db_index=True, max_length=10)),
                ("booking_id", models.PositiveIntegerField(db_index=True)),
                ("card_id", models.PositiveBigIntegerField(db_index=True)),
                ("ref", models.CharField(blank=True, max_length=60)),
                ("customer", models.CharField(blank=True, max_length=150)),
                ("delta_sell", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("delta_net", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("delta_paid", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("method", models.CharField(blank=True, max_length=10)),
                ("payment_link", models.CharField(blank=True, max_length=500)),
                ("bank_file", models.FileField(blank=True, null=True, upload_to="modifications/banks/")),
                ("invoice_file", models.FileField(blank=True, null=True, upload_to="modifications/invoices/")),
                ("voucher_original", models.FileField(blank=True, null=True, upload_to="modifications/vouchers/")),
                ("note", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(choices=[("pending", "بانتظار الاعتماد"), ("approved", "معتمد"), ("returned", "مرجوع")], db_index=True, default="pending", max_length=10)),
                ("requested_by_name", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_note", models.CharField(blank=True, max_length=255)),
                ("applied_payment_id", models.PositiveIntegerField(blank=True, null=True)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "طلب تعديل",
                "verbose_name_plural": "طلبات التعديل",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]

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
            name="CustomerProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone_key", models.CharField(db_index=True, max_length=32, unique=True, verbose_name="مفتاح الموبايل")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="الإيميل")),
                ("notes", models.TextField(blank=True, verbose_name="ملاحظات")),
                ("no_marketing", models.BooleanField(default=False, verbose_name="لا يُرسل له تسويق")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="عدّل بواسطة")),
            ],
            options={
                "verbose_name": "بيانات عميل",
                "verbose_name_plural": "بيانات العملاء",
            },
        ),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0066_approve_existing_rows"),
    ]

    operations = [
        migrations.CreateModel(
            name="FlightItinerary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(blank=True, max_length=20, verbose_name="المصدر")),
                ("booking_ref", models.CharField(blank=True, max_length=20, verbose_name="مرجع الحجز")),
                ("issue_date", models.DateField(blank=True, null=True, verbose_name="تاريخ إصدار التذكرة")),
                ("trip_type", models.CharField(blank=True, max_length=20, verbose_name="نوع الرحلة")),
                ("has_transit", models.BooleanField(default=False, verbose_name="فيها ترانزيت")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("booking", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="itinerary", to="core.flightbooking")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "خط سير طيران", "verbose_name_plural": "خطوط سير الطيران"},
        ),
        migrations.CreateModel(
            name="FlightPassenger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveSmallIntegerField(default=0)),
                ("name", models.CharField(max_length=120, verbose_name="اسم المسافر")),
                ("ticket_no", models.CharField(blank=True, max_length=30, verbose_name="رقم التذكرة")),
                ("airline_code", models.CharField(blank=True, max_length=4)),
                ("itinerary", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="passengers", to="flightdocs.flightitinerary")),
            ],
            options={"ordering": ["order", "id"]},
        ),
        migrations.CreateModel(
            name="FlightSegment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveSmallIntegerField(default=0)),
                ("airline", models.CharField(blank=True, max_length=100)),
                ("airline_code", models.CharField(blank=True, max_length=4)),
                ("flight_no", models.CharField(blank=True, max_length=10)),
                ("operated_by", models.CharField(blank=True, max_length=100)),
                ("dep_city", models.CharField(blank=True, max_length=80)),
                ("dep_airport", models.CharField(blank=True, max_length=120)),
                ("dep_code", models.CharField(blank=True, max_length=4)),
                ("dep_terminal", models.CharField(blank=True, max_length=30)),
                ("dep_date", models.DateField(blank=True, null=True)),
                ("dep_time", models.TimeField(blank=True, null=True)),
                ("arr_city", models.CharField(blank=True, max_length=80)),
                ("arr_airport", models.CharField(blank=True, max_length=120)),
                ("arr_code", models.CharField(blank=True, max_length=4)),
                ("arr_terminal", models.CharField(blank=True, max_length=30)),
                ("arr_date", models.DateField(blank=True, null=True)),
                ("arr_time", models.TimeField(blank=True, null=True)),
                ("duration", models.CharField(blank=True, max_length=20)),
                ("stops", models.CharField(blank=True, max_length=30)),
                ("cabin", models.CharField(blank=True, max_length=40)),
                ("status", models.CharField(blank=True, max_length=30)),
                ("aircraft", models.CharField(blank=True, max_length=60)),
                ("meal", models.CharField(blank=True, max_length=60)),
                ("layover_before", models.PositiveIntegerField(blank=True, help_text="دقائق الانتظار قبل الرحلة دي (ترانزيت)", null=True)),
                ("pax_info", models.JSONField(blank=True, default=dict)),
                ("itinerary", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="segments", to="flightdocs.flightitinerary")),
            ],
            options={"ordering": ["order", "id"]},
        ),
    ]

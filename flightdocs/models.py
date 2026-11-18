from django.conf import settings
from django.db import models


class FlightItinerary(models.Model):
    """خط سير حجز الطيران (مستخرج من تذكرة PDF أو متراجع يدوي)."""
    booking = models.OneToOneField("core.FlightBooking", on_delete=models.CASCADE, related_name="itinerary")
    source = models.CharField(max_length=20, blank=True, verbose_name="المصدر")
    booking_ref = models.CharField(max_length=20, blank=True, verbose_name="مرجع الحجز")
    issue_date = models.DateField(null=True, blank=True, verbose_name="تاريخ إصدار التذكرة")
    trip_type = models.CharField(max_length=20, blank=True, verbose_name="نوع الرحلة")
    has_transit = models.BooleanField(default=False, verbose_name="فيها ترانزيت")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "خط سير طيران"
        verbose_name_plural = "خطوط سير الطيران"

    def __str__(self):
        return f"خط سير {self.booking_ref or self.booking_id}"


class FlightPassenger(models.Model):
    itinerary = models.ForeignKey(FlightItinerary, on_delete=models.CASCADE, related_name="passengers")
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120, verbose_name="اسم المسافر")
    ticket_no = models.CharField(max_length=30, blank=True, verbose_name="رقم التذكرة")
    airline_code = models.CharField(max_length=4, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class FlightSegment(models.Model):
    itinerary = models.ForeignKey(FlightItinerary, on_delete=models.CASCADE, related_name="segments")
    order = models.PositiveSmallIntegerField(default=0)
    airline = models.CharField(max_length=100, blank=True)
    airline_code = models.CharField(max_length=4, blank=True)
    flight_no = models.CharField(max_length=10, blank=True)
    operated_by = models.CharField(max_length=100, blank=True)
    # تواريخ وأوقات محلية للمطار (مش بنحوّلها لتوقيت السيرفر)
    dep_city = models.CharField(max_length=80, blank=True)
    dep_airport = models.CharField(max_length=120, blank=True)
    dep_code = models.CharField(max_length=4, blank=True)
    dep_terminal = models.CharField(max_length=30, blank=True)
    dep_date = models.DateField(null=True, blank=True)
    dep_time = models.TimeField(null=True, blank=True)
    arr_city = models.CharField(max_length=80, blank=True)
    arr_airport = models.CharField(max_length=120, blank=True)
    arr_code = models.CharField(max_length=4, blank=True)
    arr_terminal = models.CharField(max_length=30, blank=True)
    arr_date = models.DateField(null=True, blank=True)
    arr_time = models.TimeField(null=True, blank=True)
    duration = models.CharField(max_length=20, blank=True)
    stops = models.CharField(max_length=30, blank=True)
    cabin = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=30, blank=True)
    aircraft = models.CharField(max_length=60, blank=True)
    meal = models.CharField(max_length=60, blank=True)
    layover_before = models.PositiveIntegerField(null=True, blank=True, help_text="دقائق الانتظار قبل الرحلة دي (ترانزيت)")
    pax_info = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.flight_no} {self.dep_city}→{self.arr_city}"

# core/models.py
from django.db import models
from django.contrib.auth.models import User
from datetime import date, timedelta
import random, string
from django.utils.crypto import get_random_string
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import transaction  # 👈 جديد


# ==============================
# VOUCHER BASE MIXIN
# ==============================
class VoucherMixin(models.Model):
    booking_ref   = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    voucher_code  = models.CharField(max_length=100, blank=True, null=True, unique=True, db_index=True)
    employee_name = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        if not self.voucher_code and hasattr(self, '_VOUCHER_PREFIX'):
            today = date.today().strftime("%Y%m%d")
            ref = (self.booking_ref or "NOREF").upper()
            random_part = get_random_string(length=4, allowed_chars="0123456789")
            self.voucher_code = f"{self._VOUCHER_PREFIX}{today}{ref}{random_part}"
        super().save(*args, **kwargs)


# ==============================
# MAIN CUSTOMER CARD
# ==============================
class UniBookingCard(models.Model):
    customer_name = models.CharField(max_length=255)
    mobile        = models.CharField(max_length=50)
    nationality   = models.CharField(max_length=100)
    country       = models.CharField(max_length=100)
    ub_code       = models.CharField(max_length=50, unique=True, editable=False, db_index=True)
    created_by    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="cards", db_index=True)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["created_by"]),
            models.Index(fields=["customer_name"]),
            models.Index(fields=["mobile"]),
            models.Index(fields=["country"]),
        ]

    def generate_unique_code(self):
        today_str = date.today().strftime("%Y%m%d")
        while True:
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
            code = f"U{today_str}EMP{random_part}"
            if not UniBookingCard.objects.filter(ub_code=code).exists():
                return code

    def save(self, *args, **kwargs):
        if not self.ub_code:
            self.ub_code = self.generate_unique_code()
        super().save(*args, **kwargs)

    # --- Aggregates ---
    @property
    def total_sell(self):
        hotel_sell  = sum(hb.sell or 0 for hb in self.hotels.all())
        flight_sell = sum(fb.sell_price or 0 for fb in self.flights.all())
        other_sell  = sum(ob.sell_price or 0 for ob in self.others.all())
        return hotel_sell + flight_sell + other_sell

    @property
    def total_net(self):
        hotel_net  = sum(hb.net or 0 for hb in self.hotels.all())
        flight_net = sum(fb.net_price or 0 for fb in self.flights.all())
        other_net  = sum(ob.net_price or 0 for ob in self.others.all())
        return hotel_net + flight_net + other_net

    @property
    def total_paid(self):
        hotel_paid = (
            Payment.objects.filter(booking_hotel__in=self.hotels.all())
            .aggregate(total=Sum('paid_amount'))['total'] or Decimal("0.00")
        )
        flight_paid = (
            FlightPayment.objects.filter(booking_flight__in=self.flights.all())
            .aggregate(total=Sum('paid_amount'))['total'] or Decimal("0.00")
        )
        other_paid = (
            OtherPayment.objects.filter(booking_other__in=self.others.all())
            .aggregate(total=Sum('paid_amount'))['total'] or Decimal("0.00")
        )
        return hotel_paid + flight_paid + other_paid

    @property
    def total_remaining(self):
        return self.total_sell - self.total_paid

    @property
    def total_profit(self):
        return self.total_sell - self.total_net


# ==============================
# HOTEL BOOKING
# ==============================
class HotelBooking(VoucherMixin, models.Model):
    _VOUCHER_PREFIX = "H"

    POLICY_CHOICES = [
        ("refundable", "Refundable"),
        ("refundable_with_penalty", "Refundable with Penalty"),
        ("non_refundable", "Non-Refundable"),
    ]
    PENALTY_TYPE_CHOICES = [
        ("percent", "Percentage (%)"),
        ("amount", "Fixed Amount"),
    ]

    card = models.ForeignKey("UniBookingCard", on_delete=models.CASCADE, related_name="hotels", db_index=True)
    hotel_name    = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    hotel_address = models.CharField(max_length=255, blank=True, null=True)
    country       = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    room_type     = models.CharField(max_length=100, blank=True, null=True)
    meal_plan     = models.CharField(max_length=50, blank=True, null=True)
    provider_name = models.CharField(max_length=150, blank=True, null=True, db_index=True)

    booking_date  = models.DateField(default=timezone.localdate, db_index=True)
    checkin       = models.DateField(blank=True, null=True, db_index=True)
    checkout      = models.DateField(blank=True, null=True, db_index=True)
    nights        = models.IntegerField(default=0)
    rooms_count   = models.IntegerField(default=1)

    # التاريخ المحاسبي (اختياري داخلي للتقارير)
    accounting_date = models.DateField(null=True, blank=True, db_index=True)

    # آخر موعد سداد متفق عليه (ثابت لا يتغير بعد ضبطه)
    agreed_last_due = models.DateField(null=True, blank=True, db_index=True,
                                       help_text="آخر موعد سداد متفق عليه (ثابت)")

    cancellation_policy = models.CharField(
        max_length=50, choices=POLICY_CHOICES, blank=True, null=True, default="refundable"
    )
    refundable_until           = models.DateField(blank=True, null=True)
    cancellation_penalty_value = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    cancellation_penalty_type  = models.CharField(max_length=20, choices=PENALTY_TYPE_CHOICES, blank=True, null=True)

    net  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True)
    sell = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["card"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["employee_name"]),
            models.Index(fields=["country"]),
            models.Index(fields=["net"]),
            models.Index(fields=["sell"]),
            models.Index(fields=["accounting_date"]),
            models.Index(fields=["agreed_last_due"]),
        ]

    def save(self, *args, **kwargs):
        # الافتراضي: من checkin إن وُجد، وإلا تاريخ اليوم
        if not self.accounting_date:
            self.accounting_date = self.checkin or timezone.localdate()
        super().save(*args, **kwargs)

    def clean(self):
        if (self.sell or Decimal("0")) < (self.net or Decimal("0")):
            raise ValidationError("⚠️ سعر البيع لا يمكن أن يكون أقل من سعر النت للفندق.")

    @property
    def profit(self):
        return (self.sell or 0) - (self.net or 0)

    @property
    def total_paid(self):
        return self.payments.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0.00')

    @property
    def remaining_balance(self):
        return (self.sell or 0) - self.total_paid

    def __str__(self):
        return f"Hotel: {self.hotel_name} ({self.voucher_code})"


class Room(models.Model):
    hotel_booking = models.ForeignKey(HotelBooking, on_delete=models.CASCADE, related_name="rooms", db_index=True)
    guest_names = models.TextField(help_text="أسماء النزلاء في هذه الغرفة، مفصولة بفاصلة")

    def __str__(self):
        return f"Room for booking {self.hotel_booking.voucher_code}"


# ==============================
# PAYMENTS (HOTELS)
# ==============================
class Payment(models.Model):
    METHODS = [
        ("cash", "كاش"),
        ("bank", "تحويل بنكي"),
        ("link", "رابط دفع"),
    ]

    booking_hotel = models.ForeignKey("HotelBooking", on_delete=models.CASCADE, related_name="payments", db_index=True)
    employee_name = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    net_price   = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sell_price  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), db_index=True)
    method = models.CharField(max_length=50, choices=METHODS, db_index=True)
    installment_date = models.DateField(null=True, blank=True, db_index=True)
    payment_link    = models.URLField(null=True, blank=True)
    bank_file       = models.FileField(upload_to="payments/banks/", null=True, blank=True)
    invoice_file    = models.FileField(upload_to="payments/invoices/", null=True, blank=True)
    voucher_original= models.FileField(upload_to="payments/vouchers/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["booking_hotel"]),
            models.Index(fields=["employee_name"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["paid_amount"]),
            models.Index(fields=["method"]),
        ]

    def clean(self):
        if (self.sell_price or Decimal("0")) < (self.net_price or Decimal("0")):
            raise ValidationError("⚠️ سعر البيع لا يمكن أن يكون أقل من سعر النت في دفعة الفندق.")

    @property
    def is_editable(self):
        return timezone.now() < self.created_at + timedelta(hours=24)

    def __str__(self):
        return f"{self.get_method_display()} - {self.paid_amount}"

    # 👇 تثبيت agreed_last_due عند أول دفعة تقسيط فقط
    def save(self, *args, **kwargs):
        is_installment = (self.method == "installment" and self.installment_date is not None)
        with transaction.atomic():
            super().save(*args, **kwargs)
            if is_installment:
                b = self.booking_hotel
                if b and not b.agreed_last_due:
                    b.agreed_last_due = self.installment_date
                    b.save(update_fields=["agreed_last_due"])


# ==============================
# FLIGHT BOOKING
# ==============================
class FlightBooking(VoucherMixin, models.Model):
    _VOUCHER_PREFIX = "F"

    card    = models.ForeignKey("UniBookingCard", on_delete=models.CASCADE, related_name="flights", db_index=True)
    airline = models.CharField(max_length=100, db_index=True)
    pnr     = models.CharField(max_length=50, db_index=True)
    booking_date = models.DateField(default=timezone.localdate, db_index=True)

    net_price  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), db_index=True)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), db_index=True)

    # التاريخ المحاسبي
    accounting_date = models.DateField(null=True, blank=True, db_index=True)

    # آخر موعد سداد متفق عليه (ثابت لا يتغير بعد ضبطه)
    agreed_last_due = models.DateField(null=True, blank=True, db_index=True,
                                       help_text="آخر موعد سداد متفق عليه (ثابت)")

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["card"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["employee_name"]),
            models.Index(fields=["airline"]),
            models.Index(fields=["pnr"]),
            models.Index(fields=["net_price"]),
            models.Index(fields=["sell_price"]),
            models.Index(fields=["accounting_date"]),
            models.Index(fields=["agreed_last_due"]),
        ]

    def save(self, *args, **kwargs):
        if not self.accounting_date:
            self.accounting_date = timezone.localdate()
        super().save(*args, **kwargs)

    def clean(self):
        if (self.sell_price or Decimal("0")) < (self.net_price or Decimal("0")):
            raise ValidationError("⚠️ سعر البيع لا يمكن أن يكون أقل من سعر النت للطيران.")

    def __str__(self):
        return f"{self.airline} - {self.pnr}"

    @property
    def profit(self):
        return (self.sell_price or 0) - (self.net_price or 0)

    @property
    def total_paid(self):
        return self.payments.aggregate(total=Sum('paid_amount'))['total'] or Decimal("0.00")

    @property
    def remaining_balance(self):
        return (self.sell_price or 0) - self.total_paid


# ==============================
# FLIGHT PAYMENTS
# ==============================
class FlightPayment(models.Model):
    METHODS = [
        ("cash", "كاش"),
        ("bank", "تحويل بنكي"),
        ("link", "رابط دفع"),
    ]

    booking_flight = models.ForeignKey("FlightBooking", on_delete=models.CASCADE, related_name="payments", db_index=True)
    employee_name  = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    net_price   = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sell_price  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), db_index=True)
    method = models.CharField(max_length=50, choices=METHODS, db_index=True)
    installment_date = models.DateField(null=True, blank=True, db_index=True)
    payment_link    = models.URLField(null=True, blank=True)
    bank_file       = models.FileField(upload_to="payments/flights/banks/", null=True, blank=True)
    invoice_file    = models.FileField(upload_to="payments/flights/invoices/", null=True, blank=True)
    voucher_original= models.FileField(upload_to="payments/flights/vouchers/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["booking_flight"]),
            models.Index(fields=["employee_name"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["paid_amount"]),
            models.Index(fields=["method"]),
        ]

    def clean(self):
        if (self.sell_price or Decimal("0")) < (self.net_price or Decimal("0")):
            raise ValidationError("⚠️ سعر البيع لا يمكن أن يكون أقل من سعر النت في دفعة الطيران.")

    @property
    def is_editable(self):
        return timezone.now() < self.created_at + timedelta(hours=24)

    def __str__(self):
        return f"{self.get_method_display()} - {self.paid_amount}"

    # 👇 تثبيت agreed_last_due عند أول دفعة تقسيط فقط
    def save(self, *args, **kwargs):
        is_installment = (self.method == "installment" and self.installment_date is not None)
        with transaction.atomic():
            super().save(*args, **kwargs)
            if is_installment:
                b = self.booking_flight
                if b and not b.agreed_last_due:
                    b.agreed_last_due = self.installment_date
                    b.save(update_fields=["agreed_last_due"])


# ==============================
# OTHER BOOKING
# ==============================
class OtherBooking(VoucherMixin, models.Model):
    _VOUCHER_PREFIX = "O"

    card = models.ForeignKey(UniBookingCard, on_delete=models.CASCADE, related_name="others", db_index=True)

    SERVICE_CHOICES = [
        ("umrah", "Umrah"),
        ("transfer", "Transfer"),
        ("tours", "Tours"),
        ("rixos", "Rixos"),
        ("cruise", "Cruise"),
        ("visa", "Visa"),
        ("car_rental", "Car Rental"),
        ("access_park", "Access Park"),
    ]

    service_type  = models.CharField(max_length=50, choices=SERVICE_CHOICES, db_index=True)
    provider_name = models.CharField(max_length=150, db_index=True)
    booking_ref   = models.CharField(max_length=100, db_index=True)
    booking_date  = models.DateField(default=timezone.localdate, db_index=True)

    net_price  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True)
    sell_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True)

    # التاريخ المحاسبي
    accounting_date = models.DateField(null=True, blank=True, db_index=True)

    # آخر موعد سداد متفق عليه (ثابت لا يتغير بعد ضبطه)
    agreed_last_due = models.DateField(null=True, blank=True, db_index=True,
                                       help_text="آخر موعد سداد متفق عليه (ثابت)")

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["card"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["employee_name"]),
            models.Index(fields=["service_type"]),
            models.Index(fields=["provider_name"]),
            models.Index(fields=["net_price"]),
            models.Index(fields=["sell_price"]),
            models.Index(fields=["accounting_date"]),
            models.Index(fields=["agreed_last_due"]),
        ]

    def save(self, *args, **kwargs):
        if not self.accounting_date:
            self.accounting_date = timezone.localdate()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_service_type_display()} - {self.provider_name} ({self.voucher_code})"

    @property
    def profit(self):
        return (self.sell_price or 0) - (self.net_price or 0)

    @property
    def total_paid(self):
        return self.payments.aggregate(total=Sum("paid_amount"))['total'] or Decimal("0.00")

    @property
    def remaining_balance(self):
        return (self.sell_price or 0) - self.total_paid


class OtherPayment(models.Model):
    METHODS = [
        ("cash", "كاش"),
        ("bank", "تحويل بنكي"),
        ("link", "رابط دفع"),
    ]

    booking_other = models.ForeignKey("OtherBooking", on_delete=models.CASCADE, related_name="payments", db_index=True)
    employee_name = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    net_price   = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sell_price  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), db_index=True)
    method = models.CharField(max_length=50, choices=METHODS, db_index=True)
    installment_date = models.DateField(null=True, blank=True, db_index=True)
    payment_link    = models.URLField(null=True, blank=True)
    bank_file       = models.FileField(upload_to="payments/others/banks/", null=True, blank=True)
    invoice_file    = models.FileField(upload_to="payments/others/invoices/", null=True, blank=True)
    voucher_original= models.FileField(upload_to="payments/others/vouchers/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["booking_other"]),
            models.Index(fields=["employee_name"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["paid_amount"]),
            models.Index(fields=["method"]),
        ]

    def clean(self):
        if (self.sell_price or Decimal("0")) < (self.net_price or Decimal("0")):
            raise ValidationError("⚠️ سعر البيع لا يمكن أن يكون أقل من سعر النت في دفعة (أخرى).")

    @property
    def is_editable(self):
        return timezone.now() < self.created_at + timedelta(hours=24)

    def __str__(self):
        return f"{self.get_method_display()} - {self.paid_amount}"

    # 👇 تثبيت agreed_last_due عند أول دفعة تقسيط فقط
    def save(self, *args, **kwargs):
        is_installment = (self.method == "installment" and self.installment_date is not None)
        with transaction.atomic():
            super().save(*args, **kwargs)
            if is_installment:
                b = self.booking_other
                if b and not b.agreed_last_due:
                    b.agreed_last_due = self.installment_date
                    b.save(update_fields=["agreed_last_due"])


# ==============================
# Notifications
# ==============================
class Notification(models.Model):
    to_user       = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="notifications"
    )
    to_superusers = models.BooleanField(default=False)
    message       = models.TextField()
    due_date      = models.DateField(null=True, blank=True)
    target_url    = models.CharField(max_length=500, blank=True)
    is_read       = models.BooleanField(default=False)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.message[:60]

from django.db import models
from django.contrib.auth.models import User
from datetime import date, timedelta
import random
import string
from django.utils.crypto import get_random_string
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
import datetime
from django.db import models, transaction




# ==============================
# VOUCHER BASE MIXIN
# ==============================
class VoucherMixin(models.Model):
    booking_ref = models.CharField(max_length=100, blank=True, null=True)
    voucher_code = models.CharField(max_length=100, blank=True, null=True, unique=True)
    employee_name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

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
    mobile = models.CharField(max_length=50, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    ub_code = models.CharField(max_length=50, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

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

    # --- إجماليات البطاقة ---
    @property
    def total_sell(self):
        hotel_sell = sum([hb.sell or 0 for hb in self.hotelbooking_set.all()])
        flight_sell = sum([fb.sell_price or 0 for fb in self.flightbooking_set.all()])
        return hotel_sell + flight_sell

    @property
    def total_net(self):
        hotel_net = sum([hb.net or 0 for hb in self.hotelbooking_set.all()])
        flight_net = sum([fb.net_price or 0 for fb in self.flightbooking_set.all()])
        return hotel_net + flight_net

    @property
    def total_paid(self):
        hotel_paid = (
            Payment.objects.filter(booking_hotel__in=self.hotelbooking_set.all())
            .aggregate(total=Sum('paid_amount'))['total']
            or Decimal("0.00")
        )

        # 🟢 مدفوعات الطيران = سعر البيع (مفيش تقسيط في الطيران)
        flight_paid = sum([fb.sell_price or 0 for fb in self.flightbooking_set.all()])

        return hotel_paid + flight_paid

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

    card = models.ForeignKey(UniBookingCard, on_delete=models.CASCADE)
    hotel_name = models.CharField(max_length=255, blank=True, null=True)
    hotel_address = models.CharField(max_length=255, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    room_type = models.CharField(max_length=100, blank=True, null=True)
    meal_plan = models.CharField(max_length=50, blank=True, null=True)
    provider_name = models.CharField(max_length=150, blank=True, null=True)
    checkin = models.DateField(blank=True, null=True)
    checkout = models.DateField(blank=True, null=True)
    nights = models.IntegerField(default=0)
    rooms_count = models.IntegerField(default=1)
    cancellation_policy = models.CharField(
        max_length=50, choices=POLICY_CHOICES, blank=True, null=True, default="refundable"
    )
    refundable_until = models.DateField(blank=True, null=True)
    cancellation_penalty_value = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    cancellation_penalty_type = models.CharField(max_length=20, choices=PENALTY_TYPE_CHOICES, blank=True, null=True)
    net = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sell = models.DecimalField(max_digits=12, decimal_places=2, default=0)

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
    hotel_booking = models.ForeignKey(HotelBooking, on_delete=models.CASCADE, related_name="rooms")
    guest_names = models.TextField(help_text="أسماء النزلاء في هذه الغرفة، مفصولة بفاصلة")

    def __str__(self):
        return f"Room for booking {self.hotel_booking.voucher_code}"


# ==============================
# FLIGHT BOOKING
# ==============================
import uuid
from django.db import models
import random
import string
from django.utils import timezone

class FlightBooking(models.Model):
    card = models.ForeignKey("UniBookingCard", on_delete=models.CASCADE)

    booking_code = models.CharField(
        max_length=80, unique=True, editable=False, null=True, blank=True
    )

    airline = models.CharField(max_length=100)
    pnr = models.CharField(max_length=50)  # الموظف بيدخله يدوي
    net_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)

    PAYMENT_CHOICES = [
        ("cash", "كاش"),
        ("bank", "تحويل بنكي"),
        ("link", "رابط دفع"),
    ]
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, blank=True, null=True)
    payment_file   = models.FileField(upload_to="payments/flights/", blank=True, null=True)
    payment_link   = models.URLField(blank=True, null=True)

    invoice_file = models.FileField(upload_to="invoices/flights/", blank=True, null=True)
    voucher_file = models.FileField(upload_to="vouchers/flights/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def profit(self):
        return (self.sell_price or 0) - (self.net_price or 0)

    def __str__(self):
        return f"{self.booking_code or '---'} - {self.airline} - {self.pnr}"



# ==============================
# PAYMENTS
# ==============================
class Payment(models.Model):
    METHODS = [
        ("cash", "كاش"),
        ("bank", "تحويل بنكي"),
        ("link", "رابط دفع"),
        ("installment", "تقسيط"),
    ]
    booking_hotel = models.ForeignKey("HotelBooking", on_delete=models.CASCADE, related_name="payments")
    employee_name = models.CharField(max_length=255, blank=True, null=True)
    net_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sell_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    method = models.CharField(max_length=50, choices=METHODS)
    installment_date = models.DateField(null=True, blank=True)
    payment_link = models.URLField(null=True, blank=True)
    bank_file = models.FileField(upload_to="payments/banks/", null=True, blank=True)
    invoice_file = models.FileField(upload_to="payments/invoices/", null=True, blank=True)
    voucher_original = models.FileField(upload_to="payments/vouchers/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_editable(self):
        return timezone.now() < self.created_at + timedelta(hours=24)

    def __str__(self):
        return f"{self.get_method_display()} - {self.paid_amount}"

# ==============================
# TRANSFER & VISA
# ==============================
class TransferBooking(VoucherMixin, models.Model):
    _VOUCHER_PREFIX = "T"
    card = models.ForeignKey(UniBookingCard, on_delete=models.CASCADE)
    pickup = models.CharField(max_length=255, blank=True, null=True)
    dropoff = models.CharField(max_length=255, blank=True, null=True)
    date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"Transfer: {self.pickup} → {self.dropoff} ({self.voucher_code})"


class VisaBooking(VoucherMixin, models.Model):
    _VOUCHER_PREFIX = "V"
    card = models.ForeignKey(UniBookingCard, on_delete=models.CASCADE)
    visa_type = models.CharField(max_length=100, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Visa: {self.visa_type} ({self.voucher_code})"

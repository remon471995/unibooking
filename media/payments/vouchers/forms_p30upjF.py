# core/forms.py
from decimal import Decimal
from urllib.parse import urlparse

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from .models import (
    UniBookingCard,
    HotelBooking,
    FlightBooking,
    OtherBooking,
    Room,
    Payment,
    FlightPayment,
    OtherPayment,
    TargetCycle,
    StaffTarget,
    LeaderTarget,
    BookingAdjustment,
    BookingAmendment,
)


# =================== ثوابت ===================

PAYMENT_METHOD_CHOICES = [
    ("cash", "كاش"),
    ("bank", "تحويل بنكي"),
    ("link", "رابط بنكي"),
]

NATIONALITY_CHOICES = [
    ("كويتي", "كويتي"), ("سعودي", "سعودي"), ("إماراتي", "إماراتي"),
    ("قطري", "قطري"), ("بحريني", "بحريني"), ("عُماني", "عُماني"),
    ("مصري", "مصري"), ("أردني", "أردني"), ("لبناني", "لبناني"),
    ("تركي", "تركي"), ("هندي", "هندي"), ("باكستاني", "باكستاني"),
    ("فلبيني", "فلبيني"), ("أمريكي", "أمريكي"), ("بريطاني", "بريطاني"),
]

COUNTRY_CODE_CHOICES = [
    ("+965", "+965 (الكويت)"), ("+966", "+966 (السعودية)"),
    ("+971", "+971 (الإمارات)"), ("+974", "+974 (قطر)"),
    ("+973", "+973 (البحرين)"), ("+968", "+968 (عُمان)"),
    ("+20", "+20 (مصر)"), ("+962", "+962 (الأردن)"),
    ("+961", "+961 (لبنان)"), ("+90", "+90 (تركيا)"),
    ("+1", "+1 (USA)"), ("+44", "+44 (UK)"),
    ("+91", "+91 (India)"), ("+92", "+92 (Pakistan)"),
    ("+63", "+63 (Philippines)"),
]


def _dec(x):
    try:
        return Decimal(x or "0")
    except Exception:
        return Decimal("0")


# =================== UniBookingCard ===================

class UniBookingCardForm(forms.ModelForm):
    customer_name = forms.CharField(required=True, label="اسم العميل")
    mobile = forms.CharField(required=True, label="موبايل")
    nationality = forms.ChoiceField(choices=NATIONALITY_CHOICES, required=True, label="الجنسية")
    country = forms.ChoiceField(choices=COUNTRY_CODE_CHOICES, required=True, label="كود الدولة")

    class Meta:
        model = UniBookingCard
        fields = ["customer_name", "mobile", "nationality", "country"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cls = (
            "w-full px-3 py-2 rounded-lg bg-white dark:bg-gray-900 "
            "border border-gray-200 dark:border-gray-800 focus:ring-2 focus:ring-blue-500"
        )
        for f in self.fields.values():
            f.widget.attrs.update({"class": cls})
        self.fields["customer_name"].widget.attrs["placeholder"] = "اكتب الاسم الثلاثي"
        self.fields["mobile"].widget.attrs["placeholder"] = "51234567"


# =================== Hotel ===================

class HotelBookingForm(forms.ModelForm):
    class Meta:
        model = HotelBooking
        fields = [
            "booking_date", "booking_ref", "voucher_code",
            "hotel_name", "hotel_address", "country", "room_type", "meal_plan",
            "provider_name", "checkin", "checkout", "rooms_count",
            "accounting_date",
            "cancellation_policy", "refundable_until",
            "cancellation_penalty_value", "cancellation_penalty_type",
        ]
        widgets = {
            "booking_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "checkin": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "checkout": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "refundable_until": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "accounting_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "cancellation_policy": forms.Select(attrs={"class": "form-control"}),
            "cancellation_penalty_type": forms.Select(attrs={"class": "form-control"}),
        }
        labels = {
            "booking_date": "تاريخ الحجز (يحدد شهر التارجت)",
            "accounting_date": "التاريخ المحاسبي (لو مختلف عن تاريخ الحجز)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["booking_date"].required = True
        if not self.initial.get("booking_date"):
            self.initial["booking_date"] = timezone.localdate()
        self.fields["accounting_date"].required = False

        for f in [
            "booking_ref", "hotel_name", "hotel_address", "country",
            "room_type", "meal_plan", "provider_name", "checkin", "checkout", "rooms_count",
            "cancellation_policy",
        ]:
            if f in self.fields:
                self.fields[f].required = True

        for f in ["refundable_until", "cancellation_penalty_value", "cancellation_penalty_type"]:
            if f in self.fields:
                self.fields[f].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("booking_date"):
            cleaned["booking_date"] = timezone.localdate()
        if not cleaned.get("accounting_date"):
            cleaned["accounting_date"] = cleaned["booking_date"]

        ci, co = cleaned.get("checkin"), cleaned.get("checkout")
        if ci and co and co <= ci:
            self.add_error("checkout", "تاريخ الخروج يجب أن يكون بعد تاريخ الدخول.")
        elif ci and co:
            cleaned["nights"] = (co - ci).days

        policy = cleaned.get("cancellation_policy")
        until = cleaned.get("refundable_until")
        pval = cleaned.get("cancellation_penalty_value")
        ptype = cleaned.get("cancellation_penalty_type")

        if policy in ("refundable", "refundable_with_penalty"):
            if not until:
                self.add_error("refundable_until", "يجب تحديد تاريخ الاسترداد.")
            elif ci and until >= ci:
                self.add_error("refundable_until", "لازم يكون قبل تاريخ الدخول.")
            if policy == "refundable_with_penalty":
                if not pval:
                    self.add_error("cancellation_penalty_value", "قيمة الغرامة مطلوبة.")
                if not ptype:
                    self.add_error("cancellation_penalty_type", "نوع الغرامة مطلوب.")
            else:
                cleaned["cancellation_penalty_value"] = None
                cleaned["cancellation_penalty_type"] = None
        elif policy == "non_refundable":
            cleaned["refundable_until"] = None
            cleaned["cancellation_penalty_value"] = None
            cleaned["cancellation_penalty_type"] = None
        return cleaned


class RoomForm(forms.ModelForm):
    guest_names = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "اكتب أسماء النزلاء، كل اسم في سطر"}),
        label="أسماء النزلاء",
        required=True,
    )

    class Meta:
        model = Room
        fields = ["guest_names"]


# =================== دفعات الفندق ===================

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "net_price", "sell_price", "paid_amount", "method",
            "installment_date", "payment_link", "bank_file",
            "invoice_file", "voucher_original", "note",   # 👈 أضف note هنا
        ]
        widgets = {
            "installment_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),   # 👈 ملاحظة كـ textarea بسيطة
        }

    def __init__(self, *args, **kwargs):
        self.booking = kwargs.pop("booking", None)
        self.has_existing = kwargs.pop("has_existing_payments", False)
        super().__init__(*args, **kwargs)

        if "method" in self.fields:
            self.fields["method"].label = "طريقة الدفع"

        # لو في دفعات سابقة: إخفِ حقول أول دفعة
        if self.has_existing:
            for f in ("net_price", "sell_price", "invoice_file", "voucher_original"):
                self.fields.pop(f, None)
        else:
            # أول دفعة: خلي الأسعار مطلوبة
            self.fields["net_price"].required = True
            self.fields["sell_price"].required = True

    def clean_payment_link(self):
        link = self.cleaned_data.get("payment_link")
        if link:
            parsed = urlparse(link)
            if not parsed.scheme:
                link = "http://" + link
        return link

    def clean(self):
        cleaned = super().clean()
        paid = Decimal(cleaned.get("paid_amount") or "0")

        if not self.booking:
            return cleaned

        if hasattr(self.booking, "sell"):
            booking_sell = Decimal(self.booking.sell or 0)
            booking_net  = Decimal(getattr(self.booking, "net", 0) or 0)
        else:
            booking_sell = Decimal(getattr(self.booking, "sell_price", 0) or 0)
            booking_net  = Decimal(getattr(self.booking, "net_price", 0) or 0)

        sell_in_form = cleaned.get("sell_price")
        if sell_in_form is not None:
            try:
                booking_sell = Decimal(sell_in_form)
            except Exception:
                pass

        already = (
            self.booking.payments.aggregate(total=Sum("paid_amount"))["total"]
            or Decimal("0.00")
        )
        if self.instance and self.instance.pk:
            already -= (self.instance.paid_amount or Decimal("0.00"))

        remaining = booking_sell - already
        if remaining < 0:
            remaining = Decimal("0.00")

        if paid > remaining:
            self.add_error("paid_amount", f"المبلغ المدفوع ({paid}) أكبر من المتبقي ({remaining}).")

        if not self.has_existing:
            if paid < booking_sell and not cleaned.get("installment_date"):
                self.add_error("installment_date", "مطلوب عند أول دفعة غير كاملة.")

        due = cleaned.get("installment_date")
        hotel_checkin = getattr(self.booking, "checkin", None)
        if due and hotel_checkin and due > hotel_checkin:
            self.add_error("installment_date", "آخر ميعاد للسداد يجب أن يكون قبل تاريخ دخول الفندق.")

        method = cleaned.get("method")
        if method == "link" and not cleaned.get("payment_link"):
            self.add_error("payment_link", "أدخل رابط السداد عند اختيار طريقة (رابط دفع).")

        return cleaned



# =================== دفعات الطيران ===================

class FlightPaymentForm(forms.ModelForm):
    class Meta:
        model = FlightPayment
        fields = [
            "paid_amount",
            "method",
            "invoice_file",
            "bank_file",
            "voucher_original",
            "payment_link",
            "net_price",
            "sell_price",
            "installment_date",
            "note",              # ✅ ملاحظة
        ]
        widgets = {
            "installment_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2, "class": "w-full"}),  # ✅
        }

    def __init__(self, *args, **kwargs):
        self.booking = kwargs.pop("booking", None)
        self.has_existing = kwargs.pop("has_existing_payments", False)
        super().__init__(*args, **kwargs)

        if "method" in self.fields:
            self.fields["method"].label = "طريقة الدفع"

        if self.has_existing:
            # الدفعات اللاحقة: تثبيت الأسعار من الحجز فقط للعرض
            self.fields["net_price"].disabled = True
            self.fields["sell_price"].disabled = True
            self.fields["net_price"].required = False
            self.fields["sell_price"].required = False
        else:
            # أول دفعة: الأسعار مطلوبة
            self.fields["net_price"].required = True
            self.fields["sell_price"].required = True

    def clean_payment_link(self):
        link = self.cleaned_data.get("payment_link")
        if link:
            parsed = urlparse(link)
            if not parsed.scheme:
                link = "http://" + link
        return link

    def clean(self):
        cleaned = super().clean()
        paid = cleaned.get("paid_amount") or Decimal("0")

        # في الدفعات اللاحقة: ثبّت القيم من الحجز
        if self.booking and self.has_existing:
            cleaned["net_price"] = getattr(self.booking, "net_price", None) or Decimal("0")
            cleaned["sell_price"] = getattr(self.booking, "sell_price", None) or Decimal("0")

        if self.booking:
            target_sell = (
                getattr(self.booking, "sell_price", None)
                or cleaned.get("sell_price")
                or Decimal("0")
            )

            total_paid_so_far = getattr(self.booking, "total_paid", Decimal("0")) or Decimal("0")
            if self.instance and self.instance.pk:
                total_paid_so_far -= (self.instance.paid_amount or Decimal("0"))

            remaining = target_sell - total_paid_so_far
            if remaining < Decimal("0"):
                remaining = Decimal("0")

            if paid > remaining:
                self.add_error(
                    "paid_amount",
                    f"المبلغ المدفوع ({paid}) أكبر من المتبقي ({remaining}).",
                )

            # شرط أول دفعة فقط
            if not self.has_existing:
                sell = cleaned.get("sell_price") or target_sell or Decimal("0")
                if paid < sell and not cleaned.get("installment_date"):
                    self.add_error(
                        "installment_date",
                        "مطلوب عند أول دفعة غير كاملة.",
                    )

        # ✅ لو طريقة الدفع رابط لازم يدخل رابط
        method = cleaned.get("method")
        if method == "link" and not cleaned.get("payment_link"):
            self.add_error("payment_link", "أدخل رابط السداد عند اختيار طريقة (رابط دفع).")

        return cleaned

# =================== إنشاء خدمات أخرى ===================

class OtherBookingForm(forms.ModelForm):
    class Meta:
        model = OtherBooking
        fields = ["service_type", "provider_name", "booking_ref", "booking_date", "accounting_date"]
        widgets = {
            "service_type": forms.Select(attrs={"class": "w-full px-3 py-2 rounded-lg border", "required": "required"}),
            "provider_name": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 rounded-lg border",
                "placeholder": "اسم المورّد",
                "required": "required",
            }),
            "booking_ref": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 rounded-lg border",
                "placeholder": "رقم/مرجع الحجز",
                "required": "required",
            }),
            "booking_date": forms.DateInput(attrs={"type": "date", "class": "w-full px-3 py-2 rounded-lg border"}),
            "accounting_date": forms.DateInput(attrs={"type": "date", "class": "w-full px-3 py-2 rounded-lg border"}),
        }
        labels = {
            "booking_date": "تاريخ الحجز (يحدد شهر التارجت)",
            "accounting_date": "التاريخ المحاسبي (لو مختلف عن تاريخ الحجز)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["booking_date"].required = True
        if not self.initial.get("booking_date"):
            self.initial["booking_date"] = timezone.localdate()
        self.fields["accounting_date"].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("booking_date"):
            cleaned["booking_date"] = timezone.localdate()
        if not cleaned.get("accounting_date"):
            cleaned["accounting_date"] = cleaned["booking_date"]
        if not (cleaned.get("service_type") or "").strip():
            self.add_error("service_type", "اختيار نوع الخدمة إجباري.")
        if not (cleaned.get("provider_name") or "").strip():
            self.add_error("provider_name", "المورّد إجباري.")
        if not (cleaned.get("booking_ref") or "").strip():
            self.add_error("booking_ref", "المرجع إجباري.")
        return cleaned


# =================== دفعات الخدمات الأخرى ===================

class OtherPaymentForm(forms.ModelForm):
    class Meta:
        model = OtherPayment
        fields = [
            "paid_amount",
            "method",
            "invoice_file",
            "bank_file",
            "payment_link",
            "net_price",
            "sell_price",
            "installment_date",
            "voucher_original",
            "note",               # ✅ ملاحظة
        ]
    widgets = {
        "installment_date": forms.DateInput(attrs={"type": "date"}),
        "note": forms.Textarea(attrs={"rows": 2, "class": "w-full"}),  # ✅
    }

    def __init__(self, *args, **kwargs):
        self.booking = kwargs.pop("booking", None)
        self.has_existing = kwargs.pop("has_existing_payments", False)
        super().__init__(*args, **kwargs)

        if "method" in self.fields:
            self.fields["method"].label = "طريقة الدفع"

        if self.has_existing:
            self.fields["net_price"].disabled = True
            self.fields["sell_price"].disabled = True
            self.fields["net_price"].required = False
            self.fields["sell_price"].required = False
        else:
            self.fields["net_price"].required = True
            self.fields["sell_price"].required = True

    def clean_payment_link(self):
        link = self.cleaned_data.get("payment_link")
        if link:
            parsed = urlparse(link)
            if not parsed.scheme:
                link = "http://" + link
        return link

    def clean(self):
        cleaned = super().clean()
        paid = cleaned.get("paid_amount") or Decimal("0")

        if self.booking and self.has_existing:
            cleaned["net_price"] = getattr(self.booking, "net_price", None) or Decimal("0")
            cleaned["sell_price"] = getattr(self.booking, "sell_price", None) or Decimal("0")

        if self.booking:
            target_sell = (
                getattr(self.booking, "sell_price", None)
                or cleaned.get("sell_price")
                or Decimal("0")
            )

            total_paid_so_far = getattr(self.booking, "total_paid", Decimal("0")) or Decimal("0")
            if self.instance and self.instance.pk:
                total_paid_so_far -= (self.instance.paid_amount or Decimal("0"))

            remaining = target_sell - total_paid_so_far
            if remaining < Decimal("0"):
                remaining = Decimal("0")

            if paid > remaining:
                self.add_error(
                    "paid_amount",
                    f"المبلغ المدفوع ({paid}) أكبر من المتبقي ({remaining}).",
                )

            if not self.has_existing:
                sell = cleaned.get("sell_price") or target_sell or Decimal("0")
                if paid < sell and not cleaned.get("installment_date"):
                    self.add_error(
                        "installment_date",
                        "مطلوب عند أول دفعة غير كاملة.",
                    )

        method = cleaned.get("method")
        if method == "link" and not cleaned.get("payment_link"):
            self.add_error("payment_link", "أدخل رابط السداد عند اختيار طريقة (رابط دفع).")

        return cleaned


# =================== إنشاء طيران ===================

class FlightBookingForm(forms.ModelForm):
    class Meta:
        model = FlightBooking
        fields = ["airline", "pnr", "booking_date", "accounting_date"]
        widgets = {
            "airline": forms.TextInput(attrs={"class": "form-control", "placeholder": "شركة الطيران"}),
            "pnr": forms.TextInput(attrs={"class": "form-control", "placeholder": "PNR / Record Locator"}),
            "booking_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "accounting_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }
        labels = {
            "booking_date": "تاريخ الحجز (يحدد شهر التارجت)",
            "accounting_date": "التاريخ المحاسبي (لو مختلف عن تاريخ الحجز)",
        }

    def clean_pnr(self):
        pnr = (self.cleaned_data.get("pnr") or "").strip().upper()
        return pnr


# =================== Targets & Adjustments ===================

class TargetCycleForm(forms.ModelForm):
    class Meta:
        model = TargetCycle
        fields = ["year", "month", "start_date", "end_date", "locked"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class StaffTargetForm(forms.ModelForm):
    class Meta:
        model = StaffTarget
        fields = [
            "cycle", "employee", "leader", "set_by", "grade", "target_amount",
            "thr1", "rate1", "thr2", "rate2", "thr3", "rate3", "notes",
        ]


class LeaderTargetForm(forms.ModelForm):
    class Meta:
        model = LeaderTarget
        fields = ["cycle", "leader", "target_amount", "set_by", "notes"]


class BookingAdjustmentForm(forms.ModelForm):
    class Meta:
        model = BookingAdjustment
        fields = ["booking_type", "booking_id", "amount", "adj_type", "apply_in_cycle", "cycle", "reason"]


# =================== Booking Amendments ===================

from decimal import Decimal
from urllib.parse import urlparse
from django import forms
from django.db.models import Sum
from .models import BookingAmendment, Payment


class BookingAmendmentForm(forms.ModelForm):
    class Meta:
        model = BookingAmendment
        fields = [
            "amendment_type",
            "new_data",
            "client_fee",
            "supplier_penalty",
            "price_diff",
            "notes",
            "status",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "class": "w-full"}),
            "new_data": forms.Textarea(attrs={"rows": 3, "class": "w-full"}),
            "client_fee": forms.NumberInput(attrs={"step": "0.01"}),
            "supplier_penalty": forms.NumberInput(attrs={"step": "0.01"}),
            "price_diff": forms.NumberInput(attrs={"step": "0.01"}),
            "status": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "status" in self.fields:
            self.fields["status"].initial = "requested"


# =================== تعديل دفعات الفندق (بدون موديل مستقل) ===================

# core/forms.py

class PaymentAdjustmentForm(forms.Form):
    delta_net = forms.DecimalField(
        label="فرق صافي الشراء (Net)",
        required=False,
        initial=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
    )
    delta_sell = forms.DecimalField(
        label="فرق سعر البيع (Sell)",
        required=False,
        initial=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
    )
    delta_paid = forms.DecimalField(
        label="فرق المدفوع (تحصيل/استرجاع)",
        required=False,
        initial=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
        help_text="يمكن إدخال رقم سالب في حالة الاسترجاع.",
    )

    method = forms.ChoiceField(
        label="طريقة الدفع",
        choices=PAYMENT_METHOD_CHOICES,   # نفس اللي مستخدمه في الفندق
        required=False,
    )
    payment_link = forms.URLField(
        label="رابط الدفع",
        required=False,
    )
    bank_file = forms.FileField(
        label="إيصال بنكي",
        required=False,
    )
    invoice_file = forms.FileField(
        label="فاتورة",
        required=False,
    )
    voucher_original = forms.FileField(
        label="الفاوتشر الأصلي",
        required=False,
    )

    # ✅ حقل الملاحظة
    note = forms.CharField(
        label="ملاحظة / سبب التعديل",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "w-full"}),
    )

    def clean(self):
        cleaned = super().clean()

        # لو الحقول فاضية رجّعها صفر
        for name in ("delta_net", "delta_sell", "delta_paid"):
            val = cleaned.get(name)
            if val in (None, ""):
                cleaned[name] = Decimal("0.00")

        dpaid = cleaned.get("delta_paid") or Decimal("0.00")
        method = cleaned.get("method")

        # لو في فرق مدفوع لازم يختار طريقة الدفع
        if dpaid != 0 and not method:
            self.add_error("method", "اختر طريقة الدفع عند إدخال فرق في المدفوع.")

        return cleaned


class ModifyAdjustmentForm(PaymentAdjustmentForm):
    """
    نفس حقول PaymentAdjustmentForm بالظبط.
    بنرث منه ونتجاهل أي instance يتبعت من الـ view
    عشان مايحصلش TypeError لأننا مش ModelForm.
    """

    def __init__(self, *args, **kwargs):
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        """
        لو في أي view بينادي form.save() مش يقع.
        حالياً مش بنخزن حاجة في موديل مستقل.
        """
        return self.cleaned_data


# =================== PaymentForm (إضافة دفعة عادية من صفحة إدارة الدفع) ===================

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "net_price",
            "sell_price",
            "paid_amount",
            "method",
            "installment_date",
            "payment_link",
            "bank_file",
            "invoice_file",
            "voucher_original",
            "note",
        ]
        widgets = {
            "installment_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2, "class": "w-full"}),
        }

    def __init__(self, *args, **kwargs):
        self.booking = kwargs.pop("booking", None)
        self.has_existing = kwargs.pop("has_existing_payments", False)
        super().__init__(*args, **kwargs)

        if "method" in self.fields:
            self.fields["method"].label = "طريقة الدفع"

        # لو في دفعات سابقة: إخفِ حقول أول دفعة
        if self.has_existing:
            for f in ("net_price", "sell_price", "invoice_file", "voucher_original"):
                self.fields.pop(f, None)
        else:
            # أول دفعة: خلي الأسعار مطلوبة
            self.fields["net_price"].required = True
            self.fields["sell_price"].required = True

    def clean_payment_link(self):
        link = self.cleaned_data.get("payment_link")
        if link:
            parsed = urlparse(link)
            if not parsed.scheme:
                link = "http://" + link
        return link

    def clean(self):
        cleaned = super().clean()
        paid = Decimal(cleaned.get("paid_amount") or "0")

        if not self.booking:
            return cleaned

        if hasattr(self.booking, "sell"):
            booking_sell = Decimal(self.booking.sell or 0)
            booking_net = Decimal(getattr(self.booking, "net", 0) or 0)
        else:
            booking_sell = Decimal(getattr(self.booking, "sell_price", 0) or 0)
            booking_net = Decimal(getattr(self.booking, "net_price", 0) or 0)

        sell_in_form = cleaned.get("sell_price")
        if sell_in_form is not None:
            try:
                booking_sell = Decimal(sell_in_form)
            except Exception:
                pass

        already = (
            self.booking.payments.aggregate(total=Sum("paid_amount"))["total"]
            or Decimal("0.00")
        )
        if self.instance and self.instance.pk:
            already -= (self.instance.paid_amount or Decimal("0.00"))

        remaining = booking_sell - already
        if remaining < 0:
            remaining = Decimal("0.00")

        if paid > remaining:
            self.add_error(
                "paid_amount",
                f"المبلغ المدفوع ({paid}) أكبر من المتبقي ({remaining}).",
            )

        if not self.has_existing:
            if paid < booking_sell and not cleaned.get("installment_date"):
                self.add_error("installment_date", "مطلوب عند أول دفعة غير كاملة.")

        due = cleaned.get("installment_date")
        hotel_checkin = getattr(self.booking, "checkin", None)
        if due and hotel_checkin and due > hotel_checkin:
            self.add_error(
                "installment_date",
                "آخر ميعاد للسداد يجب أن يكون قبل تاريخ دخول الفندق.",
            )

        method = cleaned.get("method")
        if method == "link" and not cleaned.get("payment_link"):
            self.add_error(
                "payment_link",
                "أدخل رابط السداد عند اختيار طريقة (رابط دفع).",
            )

        return cleaned

from django import forms
from .models import (
    UniBookingCard, HotelBooking, FlightBooking,
    TransferBooking, VisaBooking, Payment, Room,
)

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Sum

class UniBookingCardForm(forms.ModelForm):
    class Meta:
        model = UniBookingCard
        fields = ["customer_name", "mobile", "nationality", "country"]


class HotelBookingForm(forms.ModelForm):
    class Meta:
        model = HotelBooking
        fields = [
            "booking_ref", "voucher_code", "hotel_name", "hotel_address",
            "country", "room_type", "meal_plan", "provider_name",
            "checkin", "checkout", "rooms_count",
            "cancellation_policy", "refundable_until",
            "cancellation_penalty_value", "cancellation_penalty_type",
        ]
        widgets = {
            "checkin": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "checkout": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "refundable_until": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "cancellation_policy": forms.Select(attrs={"class": "form-control"}),
            "cancellation_penalty_type": forms.Select(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        policy = cleaned_data.get("cancellation_policy")
        checkin = cleaned_data.get("checkin")
        checkout = cleaned_data.get("checkout")
        refundable_until = cleaned_data.get("refundable_until")
        penalty_value = cleaned_data.get("cancellation_penalty_value")
        penalty_type = cleaned_data.get("cancellation_penalty_type")

        # 🔹 تحقق من الحقول الإلزامية
        required_fields = [
            "booking_ref", "hotel_name", "hotel_address",
            "country", "room_type", "meal_plan", "provider_name"
        ]
        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, "هذا الحقل إلزامي.")

        # 🔹 تحقق من تواريخ الدخول والخروج
        if checkin and checkout:
            if checkout <= checkin:
                self.add_error("checkout", "تاريخ الخروج يجب أن يكون بعد تاريخ الدخول.")
            else:
                cleaned_data["nights"] = (checkout - checkin).days

        # 🔹 تحقق من سياسة الإلغاء
        if policy == "refundable_with_penalty":
            if not penalty_value:
                self.add_error("cancellation_penalty_value", "يجب إدخال قيمة الجزاء (Penalty).")
            if not penalty_type:
                self.add_error("cancellation_penalty_type", "يجب اختيار نوع الجزاء.")
            if refundable_until and checkin and refundable_until >= checkin:
                self.add_error("refundable_until", "تاريخ الاسترداد يجب أن يكون قبل تاريخ الدخول.")
            if not refundable_until:
                self.add_error("refundable_until", "يجب إدخال تاريخ الاسترداد.")

        if policy == "refundable":
            if not refundable_until:
                self.add_error("refundable_until", "يجب إدخال تاريخ الاسترداد.")
            elif checkin and refundable_until >= checkin:
                self.add_error("refundable_until", "تاريخ الاسترداد يجب أن يكون قبل تاريخ الدخول.")

        if policy == "non_refundable":
            if penalty_value:
                self.add_error("cancellation_penalty_value", "لا يمكن إدخال Penalty عند اختيار Non-Refundable.")
            if penalty_type:
                self.add_error("cancellation_penalty_type", "لا يمكن إدخال Penalty عند اختيار Non-Refundable.")
            if refundable_until:
                self.add_error("refundable_until", "لا يمكن إدخال تاريخ استرداد عند اختيار Non-Refundable.")

        return cleaned_data


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['guest_names']
        widgets = {
            'guest_names': forms.TextInput(attrs={'placeholder': 'أدخل أسماء النزلاء'})
        }



class FlightBookingForm(forms.ModelForm):
    class Meta:
        model = FlightBooking
        fields = [
            "airline", "pnr", "net_price", "sell_price",
            "payment_method", "payment_file", "payment_link",
            "invoice_file", "voucher_file"
        ]

class TransferBookingForm(forms.ModelForm):
    class Meta:
        model = TransferBooking
        fields = ["booking_ref", "voucher_code", "pickup", "dropoff", "date"]


class VisaBookingForm(forms.ModelForm):
    class Meta:
        model = VisaBooking
        fields = ["booking_ref", "voucher_code", "visa_type", "nationality"]


class VoucherUploadForm(forms.Form):
    file = forms.FileField()


class VoucherConfirmForm(forms.Form):
    booking_ref = forms.CharField(required=False)
    # ... إلخ


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            'net_price', 'sell_price', 'paid_amount', 'method', 
            'installment_date', 'payment_link', 'bank_file', 
            'invoice_file', 'voucher_original'
        ]
        widgets = {
            'installment_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.booking = kwargs.pop("booking", None)
        has_existing_payments = kwargs.pop("has_existing_payments", False)
        super().__init__(*args, **kwargs)

        if has_existing_payments:
            # --- التعديل هنا: نقوم بإزالة الحقول تمامًا ---
            self.fields.pop('net_price')
            self.fields.pop('sell_price')
            self.fields.pop('invoice_file')
            self.fields.pop('voucher_original')
        else:
            # للدفعة الأولى، هذه الحقول إجبارية
            self.fields['net_price'].required = True
            self.fields['sell_price'].required = True
            self.fields['invoice_file'].required = True
            self.fields['voucher_original'].required = True

    def clean_paid_amount(self):
        paid_amount = self.cleaned_data.get("paid_amount") or Decimal("0.00")
        sell_price = self.cleaned_data.get("sell_price")

        if self.booking:
            if self.booking.payments.exists():
                sell_price = self.booking.sell
            
            total_paid = self.booking.payments.aggregate(total=Sum('paid_amount'))['total'] or Decimal("0.00")
            remaining = (sell_price or 0) - total_paid

            if paid_amount <= 0:
                raise ValidationError("المبلغ المدفوع يجب أن يكون أكبر من صفر.")

            if paid_amount > remaining:
                raise ValidationError(f"المبلغ المدفوع أكبر من المبلغ المتبقي ({remaining:.2f}).")
        
        return paid_amount

    def clean_installment_date(self):
        due_date = self.cleaned_data.get("installment_date")
        paid_amount = self.cleaned_data.get("paid_amount", 0)
        sell_price = self.cleaned_data.get("sell_price")

        if self.booking and self.booking.payments.exists():
            sell_price = self.booking.sell

        # إذا كان المبلغ المدفوع أقل من سعر البيع، يجب تحديد تاريخ للدفع
        total_paid_after_this = (self.booking.payments.aggregate(total=Sum('paid_amount'))['total'] or Decimal("0.00")) + paid_amount
        if total_paid_after_this < (sell_price or 0):
            if not due_date:
                raise ValidationError("يجب تحديد آخر ميعاد للدفع طالما أن المبلغ لم يكتمل.")
        
            if self.booking and hasattr(self.booking, "checkin") and self.booking.checkin:
                if due_date > self.booking.checkin:
                    raise ValidationError("تاريخ آخر قسط يجب أن يكون قبل تاريخ دخول الفندق.")

        return due_date

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get("method")

        if method == "link" and not cleaned_data.get("payment_link"):
            raise ValidationError("يجب إدخال رابط الدفع عند اختيار (رابط).")

        if method == "bank" or method == "cash":
            if not cleaned_data.get("bank_file"):
                raise ValidationError("يجب رفع إيصال الدفع عند اختيار (تحويل بنكي أو كاش).")

        return cleaned_data
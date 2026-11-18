from django import forms

from core.forms import UniBookingCardForm

from .services import digits


class CardEditForm(UniBookingCardForm):
    """تعديل بيانات العميل على الكارت (الاسم / الجنسية / كود الدولة / الموبايل) مع فحص الرقم."""

    def clean_customer_name(self):
        name = " ".join((self.cleaned_data.get("customer_name") or "").split())
        if len(name) < 3:
            raise forms.ValidationError("اكتب اسم العميل كامل.")
        return name

    def clean_mobile(self):
        raw = (self.cleaned_data.get("mobile") or "").strip()
        if len(digits(raw)) < 7:
            raise forms.ValidationError("رقم الموبايل ناقص (7 أرقام على الأقل).")
        return raw

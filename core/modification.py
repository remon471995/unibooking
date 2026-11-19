"""تسجيل "طلب تعديل" (أسعار / دفعة / ملفات) بحيث يوصل كامل لشاشة مراجعة الداتا انتري.

بدل ما التعديل يتسجل بس لو المدفوع اتغيّر، بنسجّل دائماً سجل (Payment) فيه:
  - ملخص التغيير في الملاحظة: البيع / النت / المدفوع (قبل ← بعد)
  - الملفات: فاتورة / فاوتشر / إثبات دفع / رابط الدفع
  - الموظف اللي عمل التعديل
والسجل بيدخل طابور المراجعة العادي.
"""
from decimal import Decimal


def _m(x):
    return f"{Decimal(x or 0):.2f}"


def _delta(label, old, new):
    d = Decimal(new or 0) - Decimal(old or 0)
    if d == 0:
        return None
    return f"{label} {_m(old)} → {_m(new)} ({'+' if d > 0 else ''}{_m(d)})"


def record_modification(kind, booking, user, data, *, old_sell, old_net, new_sell, new_net):
    """kind: hotel / flight / other.  data: form.cleaned_data بتاع ModifyAdjustmentForm."""
    from .views_review import KINDS  # استيراد متأخر عشان نتجنب دايرة استيراد

    cfg = KINDS[kind]
    dpaid = data.get("delta_paid") or Decimal("0")
    link = data.get("payment_link") or ""
    files = {k: data.get(k) for k in ("bank_file", "invoice_file", "voucher_original")}
    user_note = (data.get("note") or "").strip()

    parts = [
        p for p in (
            _delta("البيع", old_sell, new_sell),
            _delta("النت", old_net, new_net),
            (f"المدفوع {'+' if dpaid > 0 else ''}{_m(dpaid)}" if dpaid != 0 else None),
        ) if p
    ]
    if not (parts or any(files.values()) or link or user_note):
        return None  # مفيش حاجة اتغيّرت

    note = " | ".join(parts + ([user_note] if user_note else [])) or "تعديل من شاشة تعديل الدفع"
    model = cfg["payment"]
    note = note[: model._meta.get_field("note").max_length]

    p = model(**{cfg["fk"]: booking})
    p.paid_amount = dpaid
    p.method = data.get("method") or "cash"
    p.payment_link = link
    p.bank_file = files["bank_file"]
    p.invoice_file = files["invoice_file"]
    p.voucher_original = files["voucher_original"]
    p.employee_name = (user.get_full_name() or user.get_username())
    p.note = note
    p.net_price = getattr(booking, cfg["net"]) or Decimal("0")
    p.sell_price = getattr(booking, cfg["sell"]) or Decimal("0")
    p.save()
    return p

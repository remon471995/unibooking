"""طلبات التعديل: الأجنت بيبعت، والداتا انتري بيعتمد، وبعدين بس بيتنفّذ على الحجز."""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.permissions import can_edit_card
from core.views_review import KINDS, METHOD_LABELS

from .models import ModificationRequest as MR

ZERO = Decimal("0")
logger = logging.getLogger(__name__)


def _m(x):
    return f"{Decimal(x or 0):.2f}"


def _signed(x):
    d = Decimal(x or 0)
    return "بدون تغيير" if d == 0 else f"{'+' if d > 0 else ''}{_m(d)}"


def summary(r):
    """ملخص نصي للتغيير: البيع +20.00 | النت +5.00 | المدفوع +10.00 | ملاحظة"""
    parts = []
    for label, d in (("البيع", r.delta_sell), ("النت", r.delta_net), ("المدفوع", r.delta_paid)):
        if Decimal(d or 0) != 0:
            parts.append(f"{label} {_signed(d)}")
    if r.note:
        parts.append(r.note)
    return " | ".join(parts) or "تعديل"


def _ref(booking):
    return (getattr(booking, "booking_ref", "") or getattr(booking, "voucher_code", "")
            or getattr(booking, "pnr", "") or getattr(booking, "provider_name", "") or f"#{booking.pk}")


def _vals(cfg, booking):
    return (getattr(booking, cfg["sell"]) or ZERO, getattr(booking, cfg["net"]) or ZERO)


# ------------------------------------------------------------------ الأجنت
def submit_modification(kind, booking, user, data):
    """بيرجّع (ok, message). مابيغيّرش الحجز، بيسجّل طلب بس."""
    cfg = KINDS.get(kind)
    if cfg is None:
        return False, "نوع حجز غير معروف."
    if not can_edit_card(user, booking.card):
        return False, "مش مسموح لك تطلب تعديل على الحجز ده."
    if MR.objects.filter(kind=kind, booking_id=booking.pk, status=MR.PENDING).exists():
        return False, "فيه طلب تعديل قبل كده بانتظار اعتماد الداتا انتري. استنى الرد عليه."

    dsell = data.get("delta_sell") or ZERO
    dnet = data.get("delta_net") or ZERO
    dpaid = data.get("delta_paid") or ZERO
    link = (data.get("payment_link") or "").strip()
    note = (data.get("note") or "").strip()[:255]
    files = {k: data.get(k) for k in ("bank_file", "invoice_file", "voucher_original")}
    if not (dsell or dnet or dpaid or link or note or any(files.values())):
        return False, "ما بعتش أي تعديل."

    cur_sell, cur_net = _vals(cfg, booking)
    if cur_sell + dsell < 0 or cur_net + dnet < 0:
        return False, "التعديل هيخلّي السعر أقل من صفر."

    try:
        with transaction.atomic():
            MR.objects.create(
                kind=kind, booking_id=booking.pk, card_id=booking.card_id, ref=_ref(booking)[:60],
                customer=booking.card.customer_name[:150],
                delta_sell=dsell, delta_net=dnet, delta_paid=dpaid,
                method=(data.get("method") or "cash")[:10], payment_link=link[:500],
                bank_file=files["bank_file"], invoice_file=files["invoice_file"],
                voucher_original=files["voucher_original"],
                note=note, requested_by=user, requested_by_name=(user.get_full_name() or user.get_username())[:150],
            )
    except Exception as e:  # مثلاً مشكلة في تخزين الملفات: نعرض السبب بدل صفحة 500
        logger.exception("modreq: failed to save modification request (kind=%s booking=%s)", kind, booking.pk)
        return False, f"تعذّر حفظ الطلب ({type(e).__name__}): {str(e)[:250]}"
    return True, "تم إرسال طلب التعديل للداتا انتري. هيتنفّذ على الحجز بعد الاعتماد."


# ------------------------------------------------------------------ الداتا انتري
@transaction.atomic
def approve(req_id, user):
    r = MR.objects.select_for_update().filter(pk=req_id).first()
    if r is None:
        return False, "الطلب مش موجود."
    if r.status != MR.PENDING:
        return False, "الطلب ده اتراجع قبل كده."
    cfg = KINDS[r.kind]
    booking = cfg["booking"].objects.filter(pk=r.booking_id).first()
    if booking is None:
        return False, "الحجز مش موجود."

    cur_sell, cur_net = _vals(cfg, booking)
    new_sell, new_net = cur_sell + r.delta_sell, cur_net + r.delta_net
    if new_sell < 0 or new_net < 0:
        return False, "التعديل هيخلّي السعر أقل من صفر بعد التغييرات الأخيرة. ارجعه للأجنت."

    setattr(booking, cfg["sell"], new_sell)
    setattr(booking, cfg["net"], new_net)
    booking.save()

    payment_id = None
    if r.delta_paid != 0 or r.payment_link or r.bank_file or r.invoice_file or r.voucher_original:
        p = cfg["payment"](**{cfg["fk"]: booking})
        p.paid_amount = r.delta_paid
        p.method = r.method or "cash"
        p.payment_link = r.payment_link
        p.bank_file = r.bank_file.name if r.bank_file else None
        p.invoice_file = r.invoice_file.name if r.invoice_file else None
        p.voucher_original = r.voucher_original.name if r.voucher_original else None
        p.employee_name = r.requested_by_name
        p.note = summary(r)[: cfg["payment"]._meta.get_field("note").max_length]
        p.net_price, p.sell_price = new_net, new_sell
        p.review_status = p.REVIEW_APPROVED
        p.reviewed_by, p.reviewed_at = user, timezone.now()
        p.save()
        payment_id = p.pk

    r.status, r.reviewed_by, r.reviewed_at = MR.APPROVED, user, timezone.now()
    r.applied_payment_id = payment_id
    r.save()
    return True, "تم اعتماد التعديل وتنفيذه على الحجز."


@transaction.atomic
def return_request(req_id, user, note):
    note = (note or "").strip()
    if not note:
        return False, "اكتب سبب الإرجاع."
    r = MR.objects.select_for_update().filter(pk=req_id).first()
    if r is None or r.status != MR.PENDING:
        return False, "الطلب مش موجود أو اتراجع قبل كده."
    r.status, r.reviewed_by, r.reviewed_at, r.review_note = MR.RETURNED, user, timezone.now(), note[:255]
    r.save()
    return True, "اتّرجع الطلب للأجنت."


# ------------------------------------------------------------------ العرض
def pending_for_review():
    out = []
    for r in MR.objects.filter(status=MR.PENDING).order_by("created_at"):
        cfg = KINDS.get(r.kind)
        booking = cfg["booking"].objects.filter(pk=r.booking_id).first() if cfg else None
        if booking is None:
            continue
        cur_sell, cur_net = _vals(cfg, booking)
        out.append({
            "id": r.pk, "label": cfg["label"], "ref": r.ref, "customer": r.customer, "card_id": r.card_id,
            "agent": r.requested_by_name, "created": r.created_at,
            "cur_sell": cur_sell, "new_sell": cur_sell + r.delta_sell, "dsell": _signed(r.delta_sell),
            "cur_net": cur_net, "new_net": cur_net + r.delta_net, "dnet": _signed(r.delta_net),
            "dpaid": _signed(r.delta_paid), "method": METHOD_LABELS.get(r.method, r.method),
            "invoice": r.invoice_file, "voucher": r.voucher_original, "bank": r.bank_file,
            "link": r.payment_link, "note": r.note,
        })
    return out


def state_for(kind, booking_id):
    """للأجنت: طلب بانتظار الاعتماد؟ أو آخر طلب اتّرجع (وفيه سبب)؟"""
    latest = MR.objects.filter(kind=kind, booking_id=booking_id).first()  # الأحدث (ordering)
    pending = latest if latest and latest.status == MR.PENDING else None
    returned = latest if latest and latest.status == MR.RETURNED else None
    return {
        "pending": pending, "returned": returned,
        "pending_text": summary(pending) if pending else "",
        "returned_text": summary(returned) if returned else "",
    }

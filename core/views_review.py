"""Accounts review cycle.

Agent creates a booking / payment  ->  Data Entry checks sell, net and payments against the invoice
and the payment proof  ->  approved (numbers and payments are locked)  or  returned to the agent with a reason.
A locked item can be reopened only through an unlock request approved by the leader, data entry or a manager.
"""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required
from django.forms import modelform_factory
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    FlightBooking, FlightPayment, HotelBooking, Notification, OtherBooking, OtherPayment,
    Payment, ReviewFields, ReviewLog, UnlockRequest,
)
from .permissions import can_edit_card, manageable_user_ids, role_of

KINDS = {
    "hotel": dict(booking=HotelBooking, sell="sell", net="net", payment=Payment, fk="booking_hotel", label="فندق"),
    "flight": dict(booking=FlightBooking, sell="sell_price", net="net_price", payment=FlightPayment, fk="booking_flight", label="طيران"),
    "other": dict(booking=OtherBooking, sell="sell_price", net="net_price", payment=OtherPayment, fk="booking_other", label="خدمة أخرى"),
}
PENDING, RETURNED, APPROVED = ReviewFields.REVIEW_PENDING, ReviewFields.REVIEW_RETURNED, ReviewFields.REVIEW_APPROVED
REASON_LABELS = {"numbers": "الأرقام", "invoice": "الفاتورة", "voucher": "الفاوتشر", "proof": "إثبات الدفع"}
METHOD_LABELS = {"cash": "كاش", "bank": "تحويل بنكي", "link": "رابط دفع"}


# ---------------------------------------------------------------- helpers
def can_review(user):
    return user.is_superuser or role_of(user) in ("admin", "sales_manager", "data_entry")


def _name(u):
    return (u.get_full_name() or u.username) if u else "—"


def _get(what, kind, pk):
    cfg = KINDS.get(kind)
    if not cfg or what not in ("b", "p"):
        return None, None, None, None
    obj = get_object_or_404(cfg["booking"] if what == "b" else cfg["payment"], pk=pk)
    booking = obj if what == "b" else getattr(obj, cfg["fk"])
    return obj, booking, booking.card, cfg


def _log(obj, action, note, user):
    ReviewLog.objects.create(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk,
        action=action, note=note or "", by=user,
    )


def _notify(user, message, card):
    if user:
        Notification.objects.create(to_user=user, message=message, target_url=f"/cards/{card.pk}/")


def _desc(what, kind, obj, booking, cfg):
    ref = booking.booking_ref or booking.voucher_code or f"#{booking.pk}"
    return f"{cfg['label']} {ref}" + (" (دفعة)" if what == "p" else "")


# ---------------------------------------------------------------- queue
def _booking_item(kind, cfg, b):
    sell, net = getattr(b, cfg["sell"]) or Decimal("0"), getattr(b, cfg["net"]) or Decimal("0")
    pays = list(getattr(b, "payments").all().order_by("created_at"))
    return {
        "what": "b", "kind": kind, "id": b.pk, "label": cfg["label"],
        "ref": b.booking_ref or b.voucher_code or f"#{b.pk}",
        "customer": b.card.customer_name, "card_id": b.card_id,
        "agent": _name(b.card.created_by), "team": b.card.team.name if b.card.team else "—",
        "sell": sell, "net": net, "profit": sell - net, "created": b.created_at, "status": b.review_status,
        "note": b.review_note,
        "payments": [{"method": METHOD_LABELS.get(p.method, p.method), "paid": p.paid_amount, "date": p.installment_date,
                      "invoice": p.invoice_file, "voucher": p.voucher_original, "bank": p.bank_file, "link": p.payment_link,
                      "pending": p.review_status == PENDING} for p in pays],
    }


def _payment_item(kind, cfg, p):
    b = getattr(p, cfg["fk"])
    return {
        "what": "p", "kind": kind, "id": p.pk, "label": cfg["label"] + " — دفعة",
        "ref": b.booking_ref or b.voucher_code or f"#{b.pk}",
        "customer": b.card.customer_name, "card_id": b.card_id,
        "agent": _name(b.card.created_by), "team": b.card.team.name if b.card.team else "—",
        "paid": p.paid_amount, "method": METHOD_LABELS.get(p.method, p.method), "date": p.installment_date,
        "invoice": p.invoice_file, "voucher": p.voucher_original, "bank": p.bank_file, "link": p.payment_link,
        "created": p.created_at, "status": p.review_status, "note": p.review_note,
    }


@login_required
def review_queue(request):
    reviewer = can_review(request.user)
    ids = manageable_user_ids(request.user)
    leader = (not reviewer) and ids is not None and len(ids) > 1
    if not (reviewer or leader):
        return HttpResponseForbidden("🚫 المراجعة متاحة للداتا انتري والمدراء والليدرز.")

    pending_b, pending_p, returned = [], [], []
    if reviewer:
        for kind, cfg in KINDS.items():
            qs = cfg["booking"].objects.select_related("card__created_by", "card__team")
            for b in qs.filter(review_status=PENDING).order_by("created_at"):
                pending_b.append(_booking_item(kind, cfg, b))
            for b in qs.filter(review_status=RETURNED).order_by("-reviewed_at"):
                returned.append(_booking_item(kind, cfg, b))
            pq = cfg["payment"].objects.select_related(f"{cfg['fk']}__card__created_by", f"{cfg['fk']}__card__team")
            for p in pq.filter(review_status=PENDING).exclude(**{f"{cfg['fk']}__review_status": PENDING}).order_by("created_at"):
                pending_p.append(_payment_item(kind, cfg, p))
            for p in pq.filter(review_status=RETURNED).order_by("-reviewed_at"):
                it = _payment_item(kind, cfg, p)
                returned.append(it)
        pending_b.sort(key=lambda x: x["created"])
        pending_p.sort(key=lambda x: x["created"])

    # unlock requests: reviewers see all, leaders only their people
    unlocks = []
    for r in UnlockRequest.objects.filter(status="requested").select_related("requested_by"):
        obj = r.content_type.get_object_for_this_type(pk=r.object_id) if r.content_type.model_class() else None
        if obj is None:
            continue
        booking = obj if isinstance(obj, (HotelBooking, FlightBooking, OtherBooking)) else None
        if booking is None:
            for cfg in KINDS.values():
                if isinstance(obj, cfg["payment"]):
                    booking = getattr(obj, cfg["fk"])
        card = booking.card
        if not reviewer and (card.created_by_id not in ids or r.requested_by_id == request.user.id):
            continue
        unlocks.append({
            "id": r.pk, "reason": r.reason, "by": _name(r.requested_by), "created": r.created_at,
            "what_label": ("دفعة " if not isinstance(obj, (HotelBooking, FlightBooking, OtherBooking)) else "حجز ")
                          + (booking.booking_ref or booking.voucher_code or f"#{booking.pk}"),
            "customer": card.customer_name, "card_id": card.pk,
        })

    return render(request, "core/review.html", {
        "reviewer": reviewer, "pending_b": pending_b, "pending_p": pending_p,
        "returned": returned, "unlocks": unlocks,
    })


# ---------------------------------------------------------------- approve / return
@login_required
@require_POST
def review_action(request):
    if not can_review(request.user):
        return HttpResponseForbidden("غير مسموح")
    what, kind = request.POST.get("what"), request.POST.get("kind")
    obj, booking, card, cfg = _get(what, kind, request.POST.get("pk"))
    if obj is None:
        messages.error(request, "عنصر غير معروف.")
        return redirect("review_queue")
    if obj.review_status != PENDING:
        messages.error(request, "العنصر ده اتراجع قبل كده.")
        return redirect("review_queue")

    action = request.POST.get("action")
    note = (request.POST.get("note") or "").strip()
    now = timezone.now()
    desc = _desc(what, kind, obj, booking, cfg)

    if action == "approve":
        needed = ("chk_sell", "chk_net", "chk_docs", "chk_pay") if what == "b" else ("chk_amount", "chk_method", "chk_docs")
        if not all(request.POST.get(k) for k in needed):
            messages.error(request, "علّم على كل بنود المطابقة قبل الاعتماد.")
            return redirect("review_queue")
        obj.review_status, obj.review_note, obj.reviewed_by, obj.reviewed_at = APPROVED, "", request.user, now
        obj.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
        _log(obj, "approved", note, request.user)
        if what == "b":
            for p in getattr(booking, "payments").filter(review_status=PENDING):
                p.review_status, p.review_note, p.reviewed_by, p.reviewed_at = APPROVED, "", request.user, now
                p.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
                _log(p, "approved", "مع اعتماد الحجز", request.user)
        _notify(card.created_by, f"تم اعتماد {desc} وقفل الأرقام.", card)
        messages.success(request, f"تم اعتماد {desc}.")
    elif action == "return":
        reasons = [r for r in request.POST.getlist("reason") if r in REASON_LABELS]
        if not note and not reasons:
            messages.error(request, "حدد إيه الغلط (أرقام / فاتورة / فاوتشر / إثبات دفع) أو اكتب السبب.")
            return redirect("review_queue")
        text = ("[" + "، ".join(REASON_LABELS[r] for r in reasons) + "] " if reasons else "") + note
        text = text.strip()
        obj.review_status, obj.review_note, obj.reviewed_by, obj.reviewed_at = RETURNED, text, request.user, now
        obj.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
        _log(obj, "returned", text, request.user)
        if what == "b" and set(reasons) & {"invoice", "voucher", "proof"}:
            # a wrong document lives on the payment, so the pending payments go back to the agent with it
            for p in getattr(booking, "payments").filter(review_status=PENDING):
                p.review_status, p.review_note, p.reviewed_by, p.reviewed_at = RETURNED, text, request.user, now
                p.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
                _log(p, "returned", text, request.user)
        _notify(card.created_by, f"تم إرجاع {desc} للتصحيح: {text}", card)
        messages.success(request, f"تم إرجاع {desc} للأجنت.")
    return redirect("review_queue")


# ---------------------------------------------------------------- agent fixes
class _NumbersForm(forms.Form):
    sell = forms.DecimalField(label="سعر البيع", min_value=Decimal("0"), max_digits=12, decimal_places=2)
    net = forms.DecimalField(label="سعر النت", min_value=Decimal("0"), max_digits=12, decimal_places=2)


def _may_fix(user, card):
    # the data entry reviewer never edits the numbers he is reviewing
    return can_edit_card(user, card) and role_of(user) != "data_entry"


@login_required
def booking_fix(request, kind, pk):
    obj, booking, card, cfg = _get("b", kind, pk)
    if obj is None:
        return redirect("dashboard")
    if not _may_fix(request.user, card):
        messages.error(request, "غير مسموح.")
        return redirect("card_detail", pk=card.pk)
    if obj.is_locked:
        messages.error(request, "الحجز معتمد ومقفول. اطلب فتحه الأول.")
        return redirect("card_detail", pk=card.pk)

    old_sell, old_net = getattr(obj, cfg["sell"]), getattr(obj, cfg["net"])
    form = _NumbersForm(request.POST or None, initial={"sell": old_sell, "net": old_net})
    if request.method == "POST" and form.is_valid():
        new_sell, new_net = form.cleaned_data["sell"], form.cleaned_data["net"]
        setattr(obj, cfg["sell"], new_sell)
        setattr(obj, cfg["net"], new_net)
        was_returned = obj.review_status == RETURNED
        obj.review_status = PENDING
        obj.save()
        # keep the payments' sell / net snapshots equal to the booking numbers (the app assumes that)
        getattr(obj, "payments").update(sell_price=new_sell, net_price=new_net)
        _log(obj, "fixed", f"بيع {old_sell} → {new_sell} | نت {old_net} → {new_net}", request.user)
        messages.success(request, "تم حفظ التصحيح وإرسال الحجز للمراجعة." if was_returned else "تم حفظ الأرقام.")
        return redirect("card_detail", pk=card.pk)
    docs = [{
        "id": p.pk, "method": METHOD_LABELS.get(p.method, p.method), "paid": p.paid_amount, "status": p.review_status,
        "invoice": p.invoice_file, "voucher": p.voucher_original, "bank": p.bank_file,
        "editable": p.review_status != APPROVED,
    } for p in getattr(obj, "payments").all().order_by("created_at")]
    return render(request, "core/review_fix.html", {
        "form": form, "title": f"تصحيح أرقام {_desc('b', kind, obj, booking, cfg)}",
        "note": obj.review_note if obj.review_status == RETURNED else "", "card": card, "multipart": False,
        "docs": docs, "kind": kind,
    })


_PAY_FIELDS = ["paid_amount", "method", "installment_date", "payment_link", "invoice_file", "voucher_original", "bank_file"]
_PAY_LABELS = {
    "paid_amount": "المبلغ المدفوع", "method": "طريقة الدفع", "installment_date": "آخر ميعاد للسداد",
    "payment_link": "رابط الدفع", "invoice_file": "الفاتورة", "voucher_original": "الفاوتشر الأصلي",
    "bank_file": "إثبات الدفع (تحويل / إيصال)",
}


def _due_limits(kind, booking):
    """(min date, max date, why) for the last-payment date.
    Hotel: not after check-in, and not after the last refund date when the rate is refundable."""
    min_d = booking.booking_date
    max_d, why = None, ""
    if kind == "hotel":
        max_d, why = booking.checkin, "تاريخ الدخول"
        if booking.cancellation_policy in ("refundable", "refundable_with_penalty") and booking.refundable_until:
            if not max_d or booking.refundable_until < max_d:
                max_d, why = booking.refundable_until, "آخر يوم استرداد"
    return min_d, max_d, why


@login_required
def payment_fix(request, kind, pk):
    obj, booking, card, cfg = _get("p", kind, pk)
    if obj is None:
        return redirect("dashboard")
    if not _may_fix(request.user, card):
        messages.error(request, "غير مسموح.")
        return redirect("card_detail", pk=card.pk)
    if obj.is_locked:
        messages.error(request, "الدفعة معتمدة ومقفولة. اطلب فتحها الأول.")
        return redirect("card_detail", pk=card.pk)

    sell_total = getattr(booking, cfg["sell"]) or Decimal("0")
    is_first = not getattr(booking, "payments").filter(pk__lt=obj.pk).exists()
    min_d, max_d, why = _due_limits(kind, booking)

    Form = modelform_factory(cfg["payment"], fields=_PAY_FIELDS, labels=_PAY_LABELS, widgets={
        "installment_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")})
    form = Form(request.POST or None, request.FILES or None, instance=obj)
    attrs = form.fields["installment_date"].widget.attrs
    if min_d:
        attrs["min"] = min_d.isoformat()
    if max_d:
        attrs["max"] = max_d.isoformat()

    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        paid, method, due, link = cd["paid_amount"], cd["method"], cd.get("installment_date"), cd.get("payment_link")
        if paid < 0:
            form.add_error("paid_amount", "المبلغ لازم يكون موجب.")
        if method == "link" and not link:
            form.add_error("payment_link", "رابط الدفع مطلوب لما الطريقة رابط دفع.")
        if is_first and paid < sell_total and not due:
            form.add_error("installment_date", "ده أول دفعة وهي أقل من سعر البيع، فلازم تحدد آخر ميعاد للسداد.")
        if due:
            if min_d and due < min_d:
                form.add_error("installment_date", f"آخر ميعاد للسداد مينفعش يكون قبل تاريخ الحجز ({min_d:%Y-%m-%d}).")
            if max_d and due > max_d:
                form.add_error("installment_date", f"آخر ميعاد للسداد لازم يكون في {why} ({max_d:%Y-%m-%d}) أو قبله.")
        if not form.errors:
            was_returned = obj.review_status == RETURNED
            p = form.save(commit=False)
            if method != "link":
                p.payment_link = ""
            p.review_status = PENDING
            p.save()
            _log(p, "fixed", f"المبلغ {p.paid_amount} — {METHOD_LABELS.get(p.method, p.method)}", request.user)
            if was_returned:
                msg = "تم حفظ تصحيح الدفعة."
                if booking.review_status == RETURNED:
                    msg += " لما تخلص كل التصحيحات اضغط «إعادة إرسال للمراجعة» على الحجز."
                messages.success(request, msg)
            else:
                messages.success(request, "تم حفظ الدفعة.")
            return redirect("card_detail", pk=card.pk)
    return render(request, "core/review_fix.html", {
        "form": form, "title": f"تصحيح دفعة — {_desc('p', kind, obj, booking, cfg)}",
        "note": obj.review_note if obj.review_status == RETURNED else "", "card": card, "multipart": True,
        "pay": {"first": is_first, "sell_total": str(sell_total),
                "hint": (f"آخر ميعاد للسداد لازم يكون في {why} ({max_d:%Y-%m-%d}) أو قبله." if max_d else "")},
    })


# ---------------------------------------------------------------- unlock (reopen a locked item)
@login_required
@require_POST
def unlock_request(request):
    what, kind = request.POST.get("what"), request.POST.get("kind")
    obj, booking, card, cfg = _get(what, kind, request.POST.get("pk"))
    reason = (request.POST.get("reason") or "").strip()
    if obj is None or not can_edit_card(request.user, card):
        messages.error(request, "غير مسموح.")
        return redirect("dashboard")
    if not obj.is_locked:
        messages.info(request, "العنصر مش مقفول، تقدر تعدّله مباشرة.")
        return redirect("card_detail", pk=card.pk)
    if not reason:
        messages.error(request, "اكتب سبب طلب التعديل.")
        return redirect("card_detail", pk=card.pk)
    ct = ContentType.objects.get_for_model(obj)
    if UnlockRequest.objects.filter(content_type=ct, object_id=obj.pk, status="requested").exists():
        messages.info(request, "في طلب تعديل مفتوح بالفعل.")
        return redirect("card_detail", pk=card.pk)
    UnlockRequest.objects.create(content_type=ct, object_id=obj.pk, reason=reason, requested_by=request.user)
    _log(obj, "unlock_requested", reason, request.user)
    messages.success(request, "تم إرسال طلب التعديل للموافقة (الليدر أو الداتا انتري أو المدير).")
    return redirect("card_detail", pk=card.pk)


@login_required
@require_POST
def unlock_decide(request):
    req = get_object_or_404(UnlockRequest, pk=request.POST.get("id"), status="requested")
    obj = req.content_type.get_object_for_this_type(pk=req.object_id)
    booking = obj if isinstance(obj, (HotelBooking, FlightBooking, OtherBooking)) else None
    cfg = None
    what = "b" if booking else "p"
    if booking is None:
        for k, c in KINDS.items():
            if isinstance(obj, c["payment"]):
                booking, cfg, kind = getattr(obj, c["fk"]), c, k
    else:
        for k, c in KINDS.items():
            if isinstance(obj, c["booking"]):
                cfg, kind = c, k
    card = booking.card
    ids = manageable_user_ids(request.user)
    allowed = can_review(request.user) or (ids is not None and card.created_by_id in ids)
    if not allowed or req.requested_by_id == request.user.id:
        return HttpResponseForbidden("غير مسموح")

    desc = _desc(what, kind, obj, booking, cfg)
    decision = request.POST.get("decision")
    now = timezone.now()
    req.decided_by, req.decided_at = request.user, now
    if decision == "approve":
        req.status = "approved"
        note = f"فُتح للتعديل بموافقة {_name(request.user)}: {req.reason}"
        obj.review_status, obj.review_note, obj.reviewed_by, obj.reviewed_at = RETURNED, note, request.user, now
        obj.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
        _log(obj, "unlock_approved", req.reason, request.user)
        _notify(req.requested_by, f"تمت الموافقة على فتح {desc} للتعديل.", card)
        messages.success(request, f"تم فتح {desc} للأجنت.")
    else:
        req.status = "rejected"
        _log(obj, "unlock_rejected", req.reason, request.user)
        _notify(req.requested_by, f"تم رفض طلب تعديل {desc}.", card)
        messages.success(request, "تم رفض الطلب.")
    req.save()
    return redirect("review_queue")


@login_required
@require_POST
def resubmit(request):
    """Agent finished the corrections (numbers and/or documents) and sends the booking back to review."""
    obj, booking, card, cfg = _get("b", request.POST.get("kind"), request.POST.get("pk"))
    if obj is None or not _may_fix(request.user, card):
        messages.error(request, "غير مسموح.")
        return redirect("dashboard")
    if obj.review_status != RETURNED:
        messages.info(request, "الحجز مش مرجوع.")
        return redirect("card_detail", pk=card.pk)
    still = getattr(obj, "payments").filter(review_status=RETURNED).count()
    obj.review_status = PENDING
    obj.save(update_fields=["review_status"])
    _log(obj, "resubmitted", "", request.user)
    if still:
        messages.warning(request, f"اتبعت للمراجعة، بس لسه فيه {still} دفعة مرجوعة لازم تصلّحها.")
    else:
        messages.success(request, "تم إرسال الحجز للمراجعة.")
    return redirect("card_detail", pk=card.pk)

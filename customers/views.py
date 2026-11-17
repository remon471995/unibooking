import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.models import UniBookingCard
from core.permissions import is_sales_side, role_of, sees_performance

from .models import CustomerProfile
from .services import SEGMENT_LABELS, build_customers, card_ids_for_key, digits, phone_key

SORTS = {
    "sell": ("إجمالي البيع", lambda c: c["sell"]),
    "profit": ("الربح", lambda c: c["profit"]),
    "bookings": ("عدد الحجوزات", lambda c: c["bookings"]),
    "cards": ("عدد الكروت", lambda c: c["cards"]),
    "last": ("آخر حجز", lambda c: c["last"]),
}


def _csv_safe(v):
    """منع حقن الصيغ في Excel: أي قيمة بتبدأ بـ = + - @ نحط قدامها '"""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def _export_csv(rows):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="customers.csv"'
    resp.write("\ufeff")  # عشان Excel يقرا العربي صح
    w = csv.writer(resp)
    w.writerow(["الاسم", "الموبايل", "الإيميل", "الجنسية", "التصنيف", "عدد الكروت", "عدد الحجوزات",
                "إجمالي البيع", "الربح", "أول حجز", "آخر حجز", "تسويق مسموح"])
    for c in rows:
        w.writerow([
            _csv_safe(c["name"]), "+" + c["key"], _csv_safe(c["email"]), _csv_safe(c["nationality"]),
            c["segment_label"], c["cards"], c["bookings"], c["sell"], c["profit"],
            c["first"].date() if c["first"] else "", c["last"].date() if c["last"] else "",
            "لا" if c["no_marketing"] else "نعم",
        ])
    return resp


@login_required
def customer_list(request):
    # التحليل والتصدير للمبيعات (ليدر / سوبر فايزر / مدير) — نفس صلاحية صفحة الأداء
    if not sees_performance(request.user):
        raise PermissionDenied

    rows = build_customers()
    all_count = len(rows)
    stats = {
        "customers": all_count,
        "vip": sum(1 for c in rows if c["segment"] == "vip"),
        "repeat": sum(1 for c in rows if c["segment"] == "repeat"),
        "sell": sum(c["sell"] for c in rows),
    }

    q = (request.GET.get("q") or "").strip()
    segment = request.GET.get("segment") or ""
    marketing = request.GET.get("marketing") or ""
    sort = request.GET.get("sort") if request.GET.get("sort") in SORTS else "sell"

    if q:
        ql, qd = q.lower(), digits(q)
        rows = [
            c for c in rows
            if any(ql in n.lower() for n in [c["name"]] + c["other_names"])
            or (qd and qd in c["key"])
            or (c["email"] and ql in c["email"].lower())
        ]
    if segment in SEGMENT_LABELS:
        rows = [c for c in rows if c["segment"] == segment]
    if marketing == "ok":  # للحملات: اللي مسموح تسويق ليه
        rows = [c for c in rows if not c["no_marketing"]]
    elif marketing == "email":  # مسموح + عنده إيميل
        rows = [c for c in rows if not c["no_marketing"] and c["email"]]

    rows.sort(key=lambda c: (SORTS[sort][1](c) is None, SORTS[sort][1](c) or 0), reverse=True)

    if request.GET.get("export") == "csv":
        return _export_csv(rows)

    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("export", None)
    return render(request, "customers/customer_list.html", {
        "page": page, "stats": stats, "shown": len(rows), "querystring": params.urlencode(),
        "sorts": [(k, v[0]) for k, v in SORTS.items()], "segments": SEGMENT_LABELS.items(),
        "f": {"q": q, "segment": segment, "marketing": marketing, "sort": sort},
    })


@login_required
def customer_by_card(request, card_id):
    card = get_object_or_404(UniBookingCard, pk=card_id)
    key = phone_key(card.country, card.mobile)
    if not key:
        return redirect("card_detail", pk=card.pk)
    return redirect("customers:detail", key=key)


def _booking_rows(cards):
    rows = []
    for card in cards:
        for h in card.hotels.all():
            rows.append({"kind": "فندق", "title": h.hotel_name or "—", "ref": h.booking_ref or h.voucher_code or "",
                         "date": h.booking_date, "period": f"{h.checkin or ''} → {h.checkout or ''}" if h.checkin else "",
                         "sell": h.sell, "net": h.net, "paid": h.total_paid, "remaining": h.remaining_balance,
                         "review": h.get_review_status_display(), "card": card})
        for f in card.flights.all():
            rows.append({"kind": "طيران", "title": f.airline, "ref": f.pnr, "date": f.booking_date, "period": "",
                         "sell": f.sell_price, "net": f.net_price, "paid": f.total_paid, "remaining": f.remaining_balance,
                         "review": f.get_review_status_display(), "card": card})
        for o in card.others.all():
            rows.append({"kind": o.get_service_type_display(), "title": o.provider_name,
                         "ref": getattr(o, "booking_ref", "") or getattr(o, "voucher_code", "") or "",
                         "date": o.booking_date, "period": "", "sell": o.sell_price, "net": o.net_price,
                         "paid": o.total_paid, "remaining": o.remaining_balance,
                         "review": o.get_review_status_display(), "card": card})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


@login_required
def customer_detail(request, key):
    if not key.isdigit():
        raise Http404
    ids = card_ids_for_key(key)
    if not ids:
        raise Http404
    cards = list(
        UniBookingCard.objects.filter(id__in=ids)
        .select_related("created_by", "team")
        .prefetch_related("hotels", "flights", "others")
        .order_by("-created_at")
    )
    bookings = _booking_rows(cards)

    names = []
    for c in cards:
        n = (c.customer_name or "").strip()
        if n and n not in names:
            names.append(n)
    totals = {
        "sell": sum((b["sell"] or 0) for b in bookings),
        "net": sum((b["net"] or 0) for b in bookings),
        "paid": sum((b["paid"] or 0) for b in bookings),
        "remaining": sum((b["remaining"] or 0) for b in bookings),
    }
    totals["profit"] = totals["sell"] - totals["net"]

    segment = next((c for c in build_customers() if c["key"] == key), None)
    profile = CustomerProfile.objects.filter(phone_key=key).first()
    can_edit = is_sales_side(request.user) or role_of(request.user) == "data_entry"
    return render(request, "customers/customer_detail.html", {
        "key": key, "names": names, "cards": cards, "bookings": bookings, "totals": totals,
        "segment": segment, "profile": profile, "can_edit": can_edit,
        "sees_money": sees_performance(request.user),
        "employees": sorted({c.created_by.get_full_name() or c.created_by.get_username() for c in cards}),
        "nationality": next((c.nationality for c in cards if c.nationality), ""),
    })


@login_required
@require_POST
def customer_update(request, key):
    if not key.isdigit():
        raise Http404
    if not (is_sales_side(request.user) or role_of(request.user) == "data_entry"):
        raise PermissionDenied
    email = (request.POST.get("email") or "").strip()
    if email:
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "الإيميل غير صحيح.")
            return redirect("customers:detail", key=key)
    p, _ = CustomerProfile.objects.get_or_create(phone_key=key)
    p.email = email
    p.notes = (request.POST.get("notes") or "").strip()
    p.no_marketing = request.POST.get("no_marketing") == "on"
    p.updated_by = request.user
    p.save()
    messages.success(request, "تم حفظ بيانات العميل.")
    return redirect("customers:detail", key=key)


@login_required
@require_GET
def customer_lookup(request):
    """بيدوّر على عميل سابق بالموبايل (كود الدولة + الرقم) عشان فورم الكارت الجديد يتعبّى تلقائي."""
    key = phone_key(request.GET.get("country"), request.GET.get("mobile"))
    if len(key) < 8:  # رقم قصير جداً، مفيش داعي نبحث
        return JsonResponse({"found": False})
    ids = card_ids_for_key(key)
    if not ids:
        return JsonResponse({"found": False})
    last = (
        UniBookingCard.objects.filter(id__in=ids)
        .select_related("created_by").order_by("-created_at").first()
    )
    profile = CustomerProfile.objects.filter(phone_key=key).first()
    return JsonResponse({
        "found": True,
        "name": last.customer_name,
        "nationality": last.nationality,
        "email": profile.email if profile else "",
        "cards": len(ids),
        "last_date": last.created_at.strftime("%Y-%m-%d"),
        "last_employee": last.created_by.get_full_name() or last.created_by.get_username(),
        "url": reverse("customers:detail", args=[key]),
    })

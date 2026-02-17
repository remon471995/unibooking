# core/views_accounts.py
from decimal import Decimal
from datetime import date
import csv
import re

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Sum, Q, Count
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import (
    HotelBooking, FlightBooking, OtherBooking,
    Payment, FlightPayment, OtherPayment,
)

D0 = Decimal("0.00")

# ======================== أدوات H/F/O ========================

PREFIX_MAP = {"hotel": "H", "flight": "F", "other": "O"}
# شكل كود H/F/O الصحيح: حرف النوع + 8 أرقام تاريخ + مرجع حروف/أرقام
HFO_RE = re.compile(r'^[HFO]\d{8}[A-Z0-9]+$')

def _clean_ref(val) -> str:
    """تنظيف المرجع ليصبح حروف/أرقام Uppercase فقط."""
    return re.sub(r'[^A-Z0-9]', '', (str(val or '')).upper())

def _ymd(d) -> str:
    """تحويل التاريخ لصيغة YYYYMMDD (يدعم date/datetime/string)."""
    if not d:
        return ""
    try:
        return d.strftime("%Y%m%d")
    except Exception:
        s = str(d)[:10]  # "YYYY-MM-DD"
        return s.replace("-", "")

def compose_hfo(kind: str, booking_date, ref_value: str) -> str:
    """تجميع كود H/F/O = حرف النوع + تاريخ الحجز + المرجع المنظَّف."""
    prefix = PREFIX_MAP.get((kind or "").lower())
    ymd = _ymd(booking_date)
    base = _clean_ref(ref_value)
    if prefix and ymd and base:
        return f"{prefix}{ymd}{base}"
    return ""

def split_ref_hfo(kind: str, booking_date, raw_ref: str, voucher_code: str):
    """
    يعيد (pnr_ref, hfo_code) بعد الفصل الذكي:
    - لو raw_ref أصلاً على شكل H/F/O ننقله لعمود H/F/O ونفضّي المرجع.
    - وإلا نستخدم voucher_code لو صحيح شكليًا.
    - وإلا نكوّن H/F/O من النوع + التاريخ + المرجع.
    """
    raw_ref = (raw_ref or "").strip()
    vcode = (voucher_code or "").strip()

    # تنظيف للعرض في عمود المرجع (لكن من غير ما نضيّع الأصل)
    ref_clean_for_match = _clean_ref(raw_ref)

    # 1) المرجع نفسه على شكل H/F/O؟
    if ref_clean_for_match and HFO_RE.match(ref_clean_for_match):
        return ("-", ref_clean_for_match)

    # 2) كود مخزَّن صالح شكليًا؟
    vcode_clean = _clean_ref(vcode)
    if vcode_clean and HFO_RE.match(vcode_clean):
        return (raw_ref or "-", vcode_clean)

    # 3) كوِّن كود H/F/O من المرجع الحالي
    auto = compose_hfo(kind, booking_date, raw_ref)
    return (raw_ref or "-", auto or "-")

# ======================== مراجع حقيقية لكل نوع ========================

def compute_ref_hotel(b) -> str:
    """مرجع الفندق الحقيقي (بدون voucher_code)."""
    candidates = [
        "booking_no", "booking_number",
        "reservation_no", "reservation_number", "reservation_code",
        "booking_ref", "booking_reference",
        "supplier_ref", "hotel_ref",
        "reference", "ref",
   ]
    for attr in candidates:
        v = getattr(b, attr, None)
        if v:
            return str(v)
    return ""

def compute_ref_flight(b) -> str:
    """مرجع الطيران = PNR أساسًا، بدون استخدام voucher_code."""
    for attr in ["pnr", "reference", "ref", "booking_ref"]:
        v = getattr(b, attr, None)
        if v:
            return str(v)
    return ""

def compute_ref_other(b) -> str:
    """
    مرجع (أخرى) = reference_number ثم booking_ref ثم reference/ref/...
    (بدون استخدام voucher_code).
    """
    for attr in ["reference_number", "booking_ref", "reference", "ref", "pnr", "booking_no", "booking_number"]:
        v = getattr(b, attr, None)
        if v:
            return str(v)
    return ""

# ======================== صلاحيات ========================

def _can_view_accounts(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = (getattr(getattr(user, "profile", None), "role", "") or "").upper()
    return role in {"LEADER", "ACCOUNTANT", "SUPERVISOR", "MANAGER", "ADMIN"}

# ======================== دفتر الأستاذ العام ========================

@login_required
@user_passes_test(_can_view_accounts)
def accounts_ledger_view(request):
    """
    صفحة موحّدة لعرض: فندق/طيران/أخرى + إجماليات + فلاتر + CSV

    ترتيب الأعمدة (حسب طلبك):
    تاريخ/وقت الإنشاء، تاريخ الحجز، الموظف، اسم العميل، الجنسية، الموبايل،
    PNR/المرجع، كود H/F/O، النوع، المورّد، التفصيل، الدولة، الليالي، الغرف، إدارة.
    """

    # -------- الفلاتر --------
    start_date_str = (request.GET.get("from") or "").strip()
    end_date_str   = (request.GET.get("to") or "").strip()
    customer_q     = (request.GET.get("customer") or "").strip()
    employee_q     = (request.GET.get("employee") or "").strip()
    type_q         = (request.GET.get("type") or "").strip()  # hotel | flight | other | ''

    date_from = parse_date(start_date_str) if start_date_str else None
    date_to   = parse_date(end_date_str) if end_date_str else None

    # -------- QuerySets --------
    h_qs = (HotelBooking.objects
            .select_related("card", "card__created_by")
            .prefetch_related("rooms")
            .annotate(rooms_total=Count("rooms")))
    f_qs = FlightBooking.objects.select_related("card", "card__created_by")
    o_qs = OtherBooking.objects.select_related("card", "card__created_by")

    # تاريخ الحجز
    if date_from:
        h_qs = h_qs.filter(booking_date__gte=date_from)
        f_qs = f_qs.filter(booking_date__gte=date_from)
        o_qs = o_qs.filter(booking_date__gte=date_from)
    if date_to:
        h_qs = h_qs.filter(booking_date__lte=date_to)
        f_qs = f_qs.filter(booking_date__lte=date_to)
        o_qs = o_qs.filter(booking_date__lte=date_to)

    # اسم العميل
    if customer_q:
        h_qs = h_qs.filter(card__customer_name__icontains=customer_q)
        f_qs = f_qs.filter(card__customer_name__icontains=customer_q)
        o_qs = o_qs.filter(card__customer_name__icontains=customer_q)

    # الموظف (username/first_name/last_name + employee_name لو موجود)
    if employee_q:
        base_q = (
            Q(card__created_by__username__icontains=employee_q) |
            Q(card__created_by__first_name__icontains=employee_q) |
            Q(card__created_by__last_name__icontains=employee_q)
        )
        h_qs = h_qs.filter(base_q | Q(employee_name__icontains=employee_q)) if hasattr(HotelBooking, "employee_name") else h_qs.filter(base_q)
        f_qs = f_qs.filter(base_q | Q(employee_name__icontains=employee_q)) if hasattr(FlightBooking, "employee_name") else f_qs.filter(base_q)
        o_qs = o_qs.filter(base_q | Q(employee_name__icontains=employee_q)) if hasattr(OtherBooking, "employee_name") else o_qs.filter(base_q)

    # -------- إجماليات المدفوع --------
    paid_h_map = {
        r["booking_hotel_id"]: r["total"]
        for r in Payment.objects
                       .filter(booking_hotel__in=h_qs)
                       .values("booking_hotel_id")
                       .annotate(total=Sum("paid_amount"))
    }
    paid_f_map = {
        r["booking_flight_id"]: r["total"]
        for r in FlightPayment.objects
                              .filter(booking_flight__in=f_qs)
                              .values("booking_flight_id")
                              .annotate(total=Sum("paid_amount"))
    }
    paid_o_map = {
        r["booking_other_id"]: r["total"]
        for r in OtherPayment.objects
                             .filter(booking_other__in=o_qs)
                             .values("booking_other_id")
                             .annotate(total=Sum("paid_amount"))
    }

    # -------- بناء الصفوف --------
    rows = []

    def _employee_of(b):
        if getattr(b, "employee_name", None):
            return b.employee_name
        if getattr(b, "card", None) and getattr(b.card, "created_by", None):
            full = (b.card.created_by.get_full_name() or "").strip()
            return full or b.card.created_by.username
        return "-"

    # فندق
    if not type_q or type_q == "hotel":
        for b in h_qs:
            sell = b.sell or D0
            net  = b.net or D0
            paid = paid_h_map.get(b.id, D0)

            # الغرف (من annotate أو prefetch fallback)
            rooms_val = getattr(b, "rooms_total", None)
            if rooms_val in (None, "") and hasattr(b, "rooms"):
                try:
                    rooms_val = b.rooms.count()
                except Exception:
                    rooms_val = "-"

            # المرجع + كود H (مع الفصل الذكي)
            ref_val = compute_ref_hotel(b)
            pnr_val, h_code = split_ref_hfo("hotel", b.booking_date, ref_val, getattr(b, "voucher_code", None))

            rows.append({
                "type": "فندق",
                "provider": getattr(b, "provider_name", "-"),
                "item": getattr(b, "hotel_name", "-"),
                "country": getattr(b, "country", "-"),
                "rooms": rooms_val if rooms_val not in (None, "") else "-",
                "nights": getattr(b, "nights", "-"),

                "pnr": pnr_val,
                "hfo": h_code,
                "booking_date": b.booking_date,
                "created_at": b.created_at,
                "last_due": getattr(b, "agreed_last_due", None),

                "customer": b.card.customer_name if b.card else "-",
                "mobile": b.card.mobile if b.card else "-",
                "nationality": b.card.nationality if b.card else "-",
                "employee": _employee_of(b),

                "sell": sell,
                "net": net,
                "profit": sell - net,
                "paid": paid,
                "remain": sell - paid,

                "card_url": reverse("card_detail", args=[b.card_id]) if b.card_id else "#",
                "details_url": reverse("hotel_payment", args=[b.pk]),
                "kind": "hotel",
            })

    # طيران
    if not type_q or type_q == "flight":
        for b in f_qs:
            sell = (getattr(b, "sell_price", None) or D0)
            net  = (getattr(b, "net_price", None) or D0)
            paid = paid_f_map.get(b.id, D0)

            ref_val = compute_ref_flight(b)  # PNR الحقيقي
            pnr_val, f_code = split_ref_hfo("flight", b.booking_date, ref_val, getattr(b, "voucher_code", None))

            rows.append({
                "type": "طيران",
                "provider": getattr(b, "provider_name", "-"),
                "item": getattr(b, "airline", "-"),
                "country": getattr(b, "country", "-"),
                "rooms": "-",
                "nights": "-",

                "pnr": pnr_val,
                "hfo": f_code,
                "booking_date": b.booking_date,
                "created_at": b.created_at,
                "last_due": getattr(b, "agreed_last_due", None),

                "customer": b.card.customer_name if b.card else "-",
                "mobile": b.card.mobile if b.card else "-",
                "nationality": b.card.nationality if b.card else "-",
                "employee": _employee_of(b),

                "sell": sell,
                "net": net,
                "profit": sell - net,
                "paid": paid,
                "remain": sell - paid,

                "card_url": reverse("card_detail", args=[b.card_id]) if b.card_id else "#",
                "details_url": reverse("flight_payment", args=[b.pk]),
                "kind": "flight",
            })

    # أخرى
    if not type_q or type_q == "other":
        for b in o_qs:
            sell = (getattr(b, "sell_price", None) or D0)
            net  = (getattr(b, "net_price", None) or D0)
            paid = paid_o_map.get(b.id, D0)

            # مرجع الأخرى الآن يشمل booking_ref (حسب نموذجك)
            ref_val = compute_ref_other(b)
            pnr_val, o_code = split_ref_hfo("other", b.booking_date, ref_val, getattr(b, "voucher_code", None))

            rows.append({
                "type": getattr(b, "service_type", None) and b.get_service_type_display() or "أخرى",
                "provider": getattr(b, "provider_name", "-"),
                "item": getattr(b, "service_name", None) or getattr(b, "notes", "-"),
                "country": getattr(b, "country", "-"),
                "rooms": "-",
                "nights": "-",

                "pnr": pnr_val,
                "hfo": o_code,
                "booking_date": b.booking_date,
                "created_at": b.created_at,
                "last_due": getattr(b, "agreed_last_due", None),

                "customer": b.card.customer_name if b.card else "-",
                "mobile": b.card.mobile if b.card else "-",
                "nationality": b.card.nationality if b.card else "-",
                "employee": _employee_of(b),

                "sell": sell,
                "net": net,
                "profit": sell - net,
                "paid": paid,
                "remain": sell - paid,

                "card_url": reverse("card_detail", args=[b.card_id]) if b.card_id else "#",
                "details_url": reverse("other_payment", args=[b.pk]),
                "kind": "other",
            })

    # ترتيب + تقسيم صفحات
    rows.sort(key=lambda r: r.get("created_at") or timezone.now(), reverse=True)
    paginator = Paginator(rows, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    # إجماليات أعلى الصفحة
    totals = {
        "net":   sum((r["net"]   for r in rows), D0),
        "sell":  sum((r["sell"]  for r in rows), D0),
        "paid":  sum((r["paid"]  for r in rows), D0),
    }
    totals["remain"] = totals["sell"] - totals["paid"]
    totals["profit"] = totals["sell"] - totals["net"]

    # تصدير CSV (بنفس ترتيب العرض)
    if (request.GET.get("export") or "").lower() == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="accounts_ledger.csv"'
        writer = csv.writer(resp)
        writer.writerow([
            "Created At", "Booking Date", "Employee", "Customer", "Nationality", "Mobile",
            "PNR/Ref", "H/F/O", "Type", "Provider", "Item", "Country", "Nights", "Rooms",
            "Net", "Sell", "Paid", "Remaining", "Profit",
        ])
        for r in rows:
            writer.writerow([
                r["created_at"], r["booking_date"], r["employee"], r["customer"], r["nationality"], r["mobile"],
                r["pnr"], r["hfo"], r["type"], r["provider"], r["item"], r["country"], r["nights"], r["rooms"],
                f'{r["net"]:.2f}', f'{r["sell"]:.2f}', f'{r["paid"]:.2f}', f'{r["remain"]:.2f}', f'{r["profit"]:.2f}',
            ])
        return resp

    context = {
        "bookings_page": page_obj,
        "totals": totals,
        "filter_from": start_date_str,
        "filter_to": end_date_str,
        "filter_customer": customer_q,
        "filter_employee": employee_q,
        "filter_type": type_q,
    }
    return render(request, "core/accounts_ledger.html", context)

# ======================== تحويل زر "تفاصيل" ========================

@login_required
@user_passes_test(_can_view_accounts)
def account_booking_detail(request, kind: str, pk: int):
    kind = (kind or "").lower()
    if kind == "hotel":
        return redirect("hotel_payment", booking_pk=pk)
    if kind == "flight":
        return redirect("flight_payment", booking_pk=pk)
    if kind == "other":
        return redirect("other_payment", pk=pk)
    return HttpResponseForbidden("نوع الحجز غير معروف.")

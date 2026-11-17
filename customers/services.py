"""تجميع الكروت في ملفات عملاء (حسب رقم الموبايل) وحساب الإجماليات والتصنيف."""
import math
from collections import Counter
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, DecimalField, IntegerField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.models import FlightBooking, HotelBooking, OtherBooking, UniBookingCard

from .models import CustomerProfile

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DEC = DecimalField(max_digits=16, decimal_places=2)

SEGMENT_LABELS = {"vip": "VIP", "repeat": "متكرر", "new": "جديد"}


def digits(s):
    return "".join(ch for ch in str(s or "").translate(_AR_DIGITS) if ch.isdigit())


def phone_key(country_code, mobile):
    """كود الدولة + الموبايل بالأرقام بس (بنشيل الأصفار اللي في الأول، وكود الدولة لو اتكرر)."""
    cc = digits(country_code)
    m = digits(mobile).lstrip("0")
    if cc and m.startswith(cc) and len(m) - len(cc) >= 7:
        m = m[len(cc):]
    return cc + m


def _sum_sub(model, field):
    sq = (model.objects.filter(card=OuterRef("pk")).order_by()
          .values("card").annotate(s=Sum(field)).values("s"))
    return Coalesce(Subquery(sq, output_field=_DEC), Value(Decimal("0.00"), output_field=_DEC), output_field=_DEC)


def _count_sub(model):
    sq = (model.objects.filter(card=OuterRef("pk")).order_by()
          .values("card").annotate(c=Count("pk")).values("c"))
    return Coalesce(Subquery(sq, output_field=IntegerField()), Value(0), output_field=IntegerField())


def _card_rows():
    return (
        UniBookingCard.objects.annotate(
            sell_h=_sum_sub(HotelBooking, "sell"),
            sell_f=_sum_sub(FlightBooking, "sell_price"),
            sell_o=_sum_sub(OtherBooking, "sell_price"),
            net_h=_sum_sub(HotelBooking, "net"),
            net_f=_sum_sub(FlightBooking, "net_price"),
            net_o=_sum_sub(OtherBooking, "net_price"),
            n_h=_count_sub(HotelBooking),
            n_f=_count_sub(FlightBooking),
            n_o=_count_sub(OtherBooking),
        )
        .order_by("-created_at")  # أحدث كارت الأول (عشان الاسم الأحدث يطلع)
        .values("id", "customer_name", "mobile", "country", "nationality", "created_at",
                "sell_h", "sell_f", "sell_o", "net_h", "net_f", "net_o", "n_h", "n_f", "n_o")
    )


def build_customers():
    """بيرجّع قايمة ملفات العملاء (واحد لكل رقم موبايل) بإجمالياتهم وتصنيفهم."""
    groups = {}
    for r in _card_rows():
        key = phone_key(r["country"], r["mobile"])
        if not key:
            continue
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "key": key, "names": Counter(), "nationalities": Counter(),
                "cards": 0, "bookings": 0, "sell": Decimal("0"), "net": Decimal("0"),
                "first": None, "last": None,
            }
        g["names"][(r["customer_name"] or "").strip()] += 1
        if r["nationality"]:
            g["nationalities"][r["nationality"]] += 1
        g["cards"] += 1
        g["bookings"] += r["n_h"] + r["n_f"] + r["n_o"]
        g["sell"] += r["sell_h"] + r["sell_f"] + r["sell_o"]
        g["net"] += r["net_h"] + r["net_f"] + r["net_o"]
        d = r["created_at"]
        g["first"] = d if g["first"] is None or d < g["first"] else g["first"]
        g["last"] = d if g["last"] is None or d > g["last"] else g["last"]

    profiles = {p.phone_key: p for p in CustomerProfile.objects.all()}
    customers = []
    for key, g in groups.items():
        names = [n for n, _ in g["names"].most_common() if n]
        g["name"] = names[0] if names else "—"
        g["other_names"] = names[1:]
        g["nationality"] = g["nationalities"].most_common(1)[0][0] if g["nationalities"] else ""
        g["profit"] = g["sell"] - g["net"]
        p = profiles.get(key)
        g["email"] = p.email if p else ""
        g["no_marketing"] = bool(p and p.no_marketing)
        customers.append(g)

    _assign_segments(customers)
    return customers


def _assign_segments(customers):
    """VIP = أعلى X% في إجمالي البيع (نسبة مش رقم، لأن العملة مختلفة). متكرر = أكتر من كارت."""
    top_percent = getattr(settings, "CUSTOMERS_VIP_TOP_PERCENT", 10)
    paying = sorted((c for c in customers if c["sell"] > 0), key=lambda c: c["sell"], reverse=True)
    n_vip = max(1, math.ceil(len(paying) * top_percent / 100)) if paying else 0
    vip_keys = {c["key"] for c in paying[:n_vip]}
    for c in customers:
        if c["key"] in vip_keys:
            c["segment"] = "vip"
        elif c["cards"] >= 2:
            c["segment"] = "repeat"
        else:
            c["segment"] = "new"
        c["segment_label"] = SEGMENT_LABELS[c["segment"]]


def card_ids_for_key(key):
    """كل الكروت اللي رقمها بيطلع نفس المفتاح."""
    return [
        c["id"] for c in UniBookingCard.objects.values("id", "mobile", "country")
        if phone_key(c["country"], c["mobile"]) == key
    ]

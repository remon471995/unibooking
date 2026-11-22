"""ملخص الحجز/الكارت اللي التذكرة مربوطة بيه، بيتحط تلقائي في أول رسالة (من غير أسعار)."""
from django.apps import apps
from django.urls import reverse

ALLOWED_MODELS = {"unibookingcard", "hotelbooking", "flightbooking", "otherbooking"}


def _d(x):
    return x.strftime("%Y-%m-%d") if x else "—"


def _itinerary_lines(booking):
    try:
        it = booking.itinerary          # من تطبيق flightdocs (لو متركّب وفي خط سير)
        out = []
        pax = [p.name + (f" ({p.ticket_no})" if p.ticket_no else "") for p in it.passengers.all()]
        if pax:
            out.append("المسافرين: " + "، ".join(pax))
        for s in it.segments.all():
            t = s.dep_time.strftime("%H:%M") if s.dep_time else ""
            out.append(f"{s.flight_no}  {s.dep_city} ← {s.arr_city}  {_d(s.dep_date)} {t}".strip())
        return out
    except Exception:
        return []


def _card_bookings_lines(card):
    lines = []
    for h in card.hotels.all():
        lines.append(f"• فندق {h.voucher_code} — {h.hotel_name}")
    for f in card.flights.all():
        lines.append(f"• طيران {f.voucher_code} — PNR {f.pnr} ({f.airline})")
    for o in card.others.all():
        lines.append(f"• {o.get_service_type_display()} {o.voucher_code} — {getattr(o, 'provider_name', '') or ''}".rstrip(" —"))
    return lines


def related_summary(app_label, model, obj_id):
    """بيرجّع (نص الملخص, رابط الكارت). فاضي لو النوع مش مسموح أو الحجز مش موجود."""
    if app_label != "core" or model not in ALLOWED_MODELS:
        return "", ""
    try:
        obj = apps.get_model(app_label, model).objects.get(pk=obj_id)
        card = obj if model == "unibookingcard" else obj.card
    except Exception:
        return "", ""

    lines = [f"العميل: {card.customer_name} — موبايل: {card.mobile or '—'} — كارت: {card.ub_code}"]
    try:
        if model == "hotelbooking":
            lines += [
                f"حجز فندق: {obj.voucher_code}",
                f"الفندق: {obj.hotel_name} ({obj.country or '—'})",
                f"Ref: {obj.booking_ref or '—'}   |   المورد: {obj.provider_name or '—'}",
                f"الدخول: {_d(obj.checkin)}  ←  الخروج: {_d(obj.checkout)}" + (f"  ({obj.nights} ليلة)" if obj.nights else ""),
            ]
        elif model == "flightbooking":
            lines += [f"حجز طيران: {obj.voucher_code}", f"PNR: {obj.pnr}   |   {obj.airline}"]
            lines += _itinerary_lines(obj)
        elif model == "otherbooking":
            lines += [
                f"{obj.get_service_type_display()}: {obj.voucher_code}",
                f"المزوّد: {getattr(obj, 'provider_name', '') or '—'}",
            ]
        else:
            rows = _card_bookings_lines(card)
            if rows:
                lines.append("الحجوزات على الكارت:")
                lines += rows
    except Exception:
        pass
    return "\n".join(lines) + "\n\nالمطلوب: ", reverse("card_detail", args=[card.pk])

import datetime as dt
import json
import logging

from django.conf import settings
from django.db import transaction

from .formatting import MAX_SEGMENTS, TRIP_LABELS, build_voucher_view, clean_payload
from .models import FlightItinerary, FlightPassenger, FlightSegment

logger = logging.getLogger(__name__)

MAX_JSON_BYTES = 300_000

DEFAULT_COMPANY = {
    "name": "AL KHAMEES TRAVEL & TOURISM",
    "address": "RONA COMPLEX, OFFICE #31-32, OPP MCDONALDS, KHAITAN",
    "phone": "+965 1899777",
    "email": "info@alkhameestravel.com",
    "logo": "logo_khamees.png",
}


def company_profile():
    """بيانات شركتك على الفاوتشر. عدّلها من settings.py: COMPANY_PROFILE = {...}"""
    return {**DEFAULT_COMPANY, **getattr(settings, "COMPANY_PROFILE", {})}


def _d(v):
    return dt.date.fromisoformat(v) if v else None


def _t(v):
    return dt.time.fromisoformat(v) if v else None


def itinerary_block_reason(booking):
    """سبب منع رفع/تغيير خط السير (أو None لو مسموح).

    القاعدة:
      - حجز معتمد = مقفول: ممنوع أي تغيير (لازم طلب فتح الأول).
      - لو خط السير اتسجل قبل كده: مايتغيّرش إلا لو الحجز رجع للتصحيح.
    """
    if booking.is_locked:
        return "الحجز معتمد ومقفول، مايتعدّلش فيه خط السير. اطلب فتح للتعديل الأول."
    if FlightItinerary.objects.filter(booking=booking).exists() and booking.review_status != booking.REVIEW_RETURNED:
        return "خط السير اتسجل قبل كده ومايتغيّرش، إلا لو الحجز رجع للتصحيح من الداتا انتري."
    return None


def _summary(data_or_it):
    """سطر مختصر لخط السير (للسجل)."""
    if isinstance(data_or_it, dict):
        segs = data_or_it.get("segments", [])
        pax = [p["name"] for p in data_or_it.get("passengers", [])]
        parts = [f'{s.get("flight_no", "")} {s.get("dep_city", "")}→{s.get("arr_city", "")} {s.get("dep_date", "")} {s.get("dep_time", "")}'.strip() for s in segs]
    else:
        pax = [p.name for p in data_or_it.passengers.all()]
        parts = [f"{s.flight_no} {s.dep_city}→{s.arr_city} {s.dep_date or ''} {s.dep_time.strftime('%H:%M') if s.dep_time else ''}".strip()
                 for s in data_or_it.segments.all()]
    return " | ".join(parts) + (" || " + ", ".join(pax) if pax else "")


def _audit(it, action, old, new):
    """بيسجّل في سجل التعديلات (لو تطبيق audit متركّب). مابيبوّظش الحفظ."""
    try:
        from django.apps import apps
        if not apps.is_installed("audit"):
            return
        from audit.signals import _write
        it.card_id = it.booking.card_id  # عشان السجل يتربط بالكارت
        _write(it, action, {"خط السير": {"label": "خط السير", "old": old or None, "new": new}})
    except Exception:
        logger.exception("flightdocs: audit write failed")


@transaction.atomic
def save_itinerary(booking, data, user=None):
    """بيحفظ/يستبدل خط سير الحجز من بيانات (dict) متنضّفة. بيرفض لو الحجز مقفول أو خط السير متسجّل."""
    if itinerary_block_reason(booking):
        return None
    data = clean_payload(data)
    if not data or not data["segments"]:
        return None
    existing = FlightItinerary.objects.filter(booking=booking).first()
    old_summary = _summary(existing) if existing else ""
    it, _ = FlightItinerary.objects.update_or_create(
        booking=booking,
        defaults={
            "source": data["source"], "booking_ref": data["booking_ref"], "issue_date": _d(data["issue_date"]),
            "trip_type": data["trip_type"], "has_transit": data["has_transit"],
            "created_by": user if user and getattr(user, "is_authenticated", False) else None,
        },
    )
    it.passengers.all().delete()
    it.segments.all().delete()
    FlightPassenger.objects.bulk_create([
        FlightPassenger(itinerary=it, order=i, **p) for i, p in enumerate(data["passengers"])
    ])
    FlightSegment.objects.bulk_create([
        FlightSegment(
            itinerary=it, order=i,
            **{k: v for k, v in s.items() if k not in ("dep_date", "dep_time", "arr_date", "arr_time")},
            dep_date=_d(s["dep_date"]), dep_time=_t(s["dep_time"]),
            arr_date=_d(s["arr_date"]), arr_time=_t(s["arr_time"]),
        )
        for i, s in enumerate(data["segments"][:MAX_SEGMENTS])
    ])
    _audit(it, "update" if existing else "create", old_summary, _summary(data))
    return it


def save_itinerary_from_post(booking, raw_json, user=None):
    """بيتنادى بعد حفظ حجز الطيران. مابيبوّظش الحفظ لو حصل أي خطأ."""
    if not raw_json or len(raw_json) > MAX_JSON_BYTES:
        return None
    try:
        return save_itinerary(booking, json.loads(raw_json), user)
    except Exception:
        logger.exception("flightdocs: failed to save itinerary for booking %s", getattr(booking, "pk", None))
        return None


def route_text(segs, trip_type):
    """المسار المعروض: ذهاب وعودة = كويت ⇄ مانشستر، غير كده سلسلة المدن."""
    if not segs:
        return ""
    journeys = []
    for s in segs:
        if not journeys or s.get("layover_before") is None:
            journeys.append([s])
        else:
            journeys[-1].append(s)
    origin = journeys[0][0].get("dep_city", "")
    if trip_type == "round_trip" and len(journeys) == 2:
        return f'{origin} ⇄ {journeys[0][-1].get("arr_city", "")}'
    cities = [origin]
    for j in journeys:
        if j[0].get("dep_city", "") != cities[-1]:
            cities.append(j[0].get("dep_city", ""))
        cities.append(j[-1].get("arr_city", ""))
    return " → ".join(c for c in cities if c)


def voucher_context(booking):
    try:
        it = booking.itinerary
    except FlightItinerary.DoesNotExist:
        it = None
    if it is None:
        return None
    passengers = [{"name": p.name, "ticket_no": p.ticket_no} for p in it.passengers.all()]
    segs = []
    for s in it.segments.all():
        d = {f.name: getattr(s, f.name) for f in s._meta.concrete_fields}
        segs.append(d)
    journeys = build_voucher_view(segs, passengers, it.trip_type)
    ar, en = TRIP_LABELS.get(it.trip_type, ("", ""))
    return {
        "booking": booking, "itinerary": it, "passengers": passengers, "journeys": journeys,
        "trip_label_ar": ar, "trip_label_en": en, "has_transit": it.has_transit,
        "route": route_text(segs, it.trip_type),
        "company": company_profile(),
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

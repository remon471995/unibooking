"""تنظيف بيانات التذكرة (اللي جاية من المتصفح) وتجهيزها لعرض الفاوتشر. من غير Django (سهل الاختبار)."""
import datetime as dt
import re

MAX_PASSENGERS = 60
MAX_SEGMENTS = 12

TRIP_LABELS = {
    "one_way": ("ذهاب فقط", "One way"),
    "round_trip": ("ذهاب وعودة", "Round trip"),
    "multi_city": ("وجهات متعددة", "Multi-city"),
}


def _s(v, n):
    return str(v if v is not None else "").strip()[:n]


def _date(v):
    try:
        return dt.date.fromisoformat(str(v)[:10]).isoformat()
    except (ValueError, TypeError):
        return ""


def _time(v):
    m = re.match(r"^(\d{1,2}):(\d{2})", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def clean_payload(data):
    """بيرجّع dict نضيف أو None لو الشكل غلط. بيحدّد الأطوال والعدد عشان ما يتخزنش حاجة عشوائية."""
    if not isinstance(data, dict):
        return None
    out = {
        "source": _s(data.get("source"), 20),
        "booking_ref": _s(data.get("booking_ref"), 20),
        "issue_date": _date(data.get("issue_date")),
        "airline": _s(data.get("airline"), 100),
        "pnr": _s(data.get("pnr"), 20),
        "trip_type": _s(data.get("trip_type"), 20) if data.get("trip_type") in TRIP_LABELS else "",
        "has_transit": bool(data.get("has_transit")),
        "passengers": [], "segments": [],
    }
    for p in (data.get("passengers") or [])[:MAX_PASSENGERS]:
        if isinstance(p, dict) and _s(p.get("name"), 120):
            out["passengers"].append({
                "name": _s(p.get("name"), 120), "ticket_no": _s(p.get("ticket_no"), 30),
                "airline_code": _s(p.get("airline_code"), 4),
            })
    for s in (data.get("segments") or [])[:MAX_SEGMENTS]:
        if not isinstance(s, dict):
            continue
        pax = {}
        for name, info in list((s.get("pax_info") or {}).items())[:MAX_PASSENGERS]:
            if isinstance(info, dict):
                extras = info.get("extras") if isinstance(info.get("extras"), list) else []
                pax[_s(name, 120)] = {
                    "baggage": _s(info.get("baggage"), 120), "seat": _s(info.get("seat"), 10),
                    "extras": [_s(x, 120) for x in extras[:10] if _s(x, 120)],
                }
        lay = s.get("layover_before")
        out["segments"].append({
            "airline": _s(s.get("airline"), 100), "airline_code": _s(s.get("airline_code"), 4),
            "flight_no": _s(s.get("flight_no"), 10).replace(" ", ""), "operated_by": _s(s.get("operated_by"), 100),
            "dep_city": _s(s.get("dep_city"), 80), "dep_airport": _s(s.get("dep_airport"), 120),
            "dep_code": _s(s.get("dep_code"), 4), "dep_terminal": _s(s.get("dep_terminal"), 30),
            "dep_date": _date(s.get("dep_date")), "dep_time": _time(s.get("dep_time")),
            "arr_city": _s(s.get("arr_city"), 80), "arr_airport": _s(s.get("arr_airport"), 120),
            "arr_code": _s(s.get("arr_code"), 4), "arr_terminal": _s(s.get("arr_terminal"), 30),
            "arr_date": _date(s.get("arr_date")), "arr_time": _time(s.get("arr_time")),
            "duration": _s(s.get("duration"), 20), "stops": _s(s.get("stops"), 30),
            "cabin": _s(s.get("cabin"), 40), "status": _s(s.get("status"), 30),
            "aircraft": _s(s.get("aircraft"), 60), "meal": _s(s.get("meal"), 60),
            "layover_before": int(lay) if isinstance(lay, (int, float)) and 0 <= lay < 10000 else None,
            "pax_info": pax,
        })
    return out


# ------------------------------------------------------------------ voucher view-model
def fmt_date(d):
    return d.strftime("%a %d %b %Y") if d else ""


def fmt_time(t):
    return t.strftime("%H:%M") if t else ""


def fmt_minutes(m):
    return f"{m // 60}h {m % 60:02d}m" if m is not None else ""


def fmt_flight_no(s):
    m = re.match(r"^([A-Z0-9]{2})(\d{1,4})$", s or "")
    return f"{m.group(1)} {m.group(2)}" if m else (s or "")


def build_voucher_view(segments, passengers, trip_type):
    """segments: dicts فيها dep_date/arr_date (date أو None) و dep_time/arr_time (time أو None).
    بيرجّع رحلات متجمّعة (ذهاب / عودة) كل واحدة فيها segments مع الترانزيت."""
    journeys, cur = [], None
    for s in segments:
        if cur is None or s.get("layover_before") is None:
            cur = {"segments": []}
            journeys.append(cur)
        dep_d, arr_d = s.get("dep_date"), s.get("arr_date")
        rows = []
        for p in passengers:
            info = (s.get("pax_info") or {}).get(p["name"], {})
            if info:
                rows.append({"name": p["name"], "baggage": info.get("baggage", ""), "seat": info.get("seat", ""),
                             "extras": "، ".join(info.get("extras", []))})
        cur["segments"].append({
            "flight_no": fmt_flight_no(s.get("flight_no")), "airline": s.get("airline", ""),
            "operated_by": s.get("operated_by", ""),
            "dep_city": s.get("dep_city", ""), "dep_airport": s.get("dep_airport", ""),
            "dep_code": s.get("dep_code", ""), "dep_terminal": s.get("dep_terminal", ""),
            "dep_time": fmt_time(s.get("dep_time")), "dep_date": fmt_date(dep_d),
            "arr_city": s.get("arr_city", ""), "arr_airport": s.get("arr_airport", ""),
            "arr_code": s.get("arr_code", ""), "arr_terminal": s.get("arr_terminal", ""),
            "arr_time": fmt_time(s.get("arr_time")), "arr_date": fmt_date(arr_d),
            "arr_next_day": bool(dep_d and arr_d and arr_d != dep_d),
            "duration": s.get("duration", ""), "stops": s.get("stops", ""),
            "cabin": s.get("cabin", ""), "status": s.get("status", ""),
            "aircraft": s.get("aircraft", ""), "meal": s.get("meal", ""),
            "layover": fmt_minutes(s.get("layover_before")) if s.get("layover_before") is not None else "",
            "pax_rows": rows,
        })
    labels = {1: [""], 2: ["الذهاب / Outbound", "العودة / Return"]}
    for i, j in enumerate(journeys):
        if trip_type == "round_trip" and len(journeys) == 2:
            j["label"] = labels[2][i]
        elif trip_type == "multi_city":
            j["label"] = f"الرحلة {i + 1} / Trip {i + 1}"
        else:
            j["label"] = ""
    return journeys

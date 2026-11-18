"""استخراج بيانات تذاكر الطيران (PDF) وتحويلها لشكل موحّد.

الصيغ المدعومة حالياً:
  - amadeus : "Your trip" من Amadeus (الخميس / أيفل / أي وكالة بنفس القالب)
  - jazeera : "Your Jazeera Airways Itinerary"

الناتج (dict) :
  source, booking_ref, issue_date (YYYY-MM-DD), airline, pnr, passengers[], segments[],
  trip_type, has_transit, warnings[]
أي صيغة غير معروفة بترجع segments فاضية + تحذير، والموظف يكمّل يدوي.
"""
import datetime as dt
import re
from collections import OrderedDict

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

NAME_RE = re.compile(r"^[A-Z][A-Z' \-]*/[A-Z][A-Z' \-]*$")
DATE_HDR_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
DEP_ARR_RE = re.compile(r"^(Departure|Arrival)\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{1,2}:\d{2})\s+(.+)$")
PLACE_RE = re.compile(r"^(?P<city>[^,(]+?),?\s*\((?P<airport>.+?)\)\s*(?:Terminal:?\s*(?P<term>.+))?$")
FLIGHT_RE = re.compile(
    r"^(?P<airline>.+?)\s+(?P<code>[A-Z0-9]{2})\s?(?P<num>\d{1,4})\b\s*(?:\(Operated by\s*(?P<op>.+?)\))?\s*$")
AMADEUS_LABELS = ("Departure", "Arrival", "Duration", "Booking status", "Class",
                  "Baggage allowance", "Seat", "Equipment", "Flight meal")
STOP_LINES = ("General Information", "Baggage Policy", "Data Protection Notice")


# ------------------------------------------------------------------ helpers
def _month(name):
    return MONTHS.get((name or "")[:3].lower())


def _mk_date(day, month_name, year):
    m = _month(month_name)
    if not m:
        return None
    try:
        return dt.date(int(year), m, int(day))
    except ValueError:
        return None


def _is_ascii(s):
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def extract_text(file_or_path, x_tolerance=1.5):
    import pdfplumber
    with pdfplumber.open(file_or_path) as pdf:
        return "\n".join((p.extract_text(x_tolerance=x_tolerance) or "") for p in pdf.pages)


def _clean_lines(text):
    out = []
    for raw in text.splitlines():
        l = re.sub(r"\s+", " ", raw).strip()
        if not l or l == "." or re.match(r"^Page \d+ of \d+$", l):
            continue
        if not _is_ascii(l):  # أسطر عربية/رموز (زي تنبيه الوكالة) بنتجاهلها
            continue
        out.append(l)
    return out


def _split_name_value(line):
    """'2 Piece(s) for ALAZEMI/MOHAMMAD MR' -> ('ALAZEMI/MOHAMMAD MR', '2 Piece(s)')"""
    m = re.match(r"^(?P<val>.+?)\s+for\s+(?P<name>\S.*)$", line)
    return (m["name"].strip(), m["val"].strip()) if m else (None, line)


def _pretty_airport(s):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s or "").strip()


# ------------------------------------------------------------------ trip analysis
def _seg_dt(seg, kind):
    d, t = seg.get(f"{kind}_date"), seg.get(f"{kind}_time")
    if not (d and t):
        return None
    try:
        return dt.datetime.combine(dt.date.fromisoformat(d), dt.time.fromisoformat(t))
    except ValueError:
        return None


def analyze_trip(segments):
    """بيحسب: نوع الرحلة (ذهاب / ذهاب وعودة / وجهات متعددة) والترانزيت وأوقات الانتظار."""
    segs = sorted(segments, key=lambda s: _seg_dt(s, "dep") or dt.datetime.max)
    journeys, layovers = [], []
    for s in segs:
        if journeys:
            prev = journeys[-1][-1]
            a, d = _seg_dt(prev, "arr"), _seg_dt(s, "dep")
            same_place = (prev.get("arr_city", "").strip().lower() == s.get("dep_city", "").strip().lower()) \
                and prev.get("arr_city")
            if a and d and same_place and dt.timedelta(0) <= d - a < dt.timedelta(hours=24):
                journeys[-1].append(s)
                s["layover_before"] = int((d - a).total_seconds() // 60)
                layovers.append(s["layover_before"])
                continue
        s["layover_before"] = None
        journeys.append([s])
    if not segs:
        trip = ""
    elif len(journeys) == 1:
        trip = "one_way"
    elif len(journeys) == 2 and journeys[0][0].get("dep_city", "").lower() == journeys[1][-1].get("arr_city", "").lower():
        trip = "round_trip"
    else:
        trip = "multi_city"
    return segs, trip, bool(layovers)


# ------------------------------------------------------------------ Amadeus
def _parse_amadeus(lines):
    flat = " ".join(lines)
    out = {"source": "amadeus", "passengers": [], "segments": [], "warnings": []}

    m = re.search(r"Booking ref:\s*([A-Z0-9]{5,8})", flat)
    out["booking_ref"] = m.group(1) if m else ""
    m = re.search(r"Document Issue Date:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", flat)
    d = _mk_date(*m.groups()) if m else None
    out["issue_date"] = d.isoformat() if d else ""

    # --- travelers
    names = []
    for i, l in enumerate(lines):
        if l.startswith("Traveler "):
            first = l[len("Traveler "):].strip()
            if NAME_RE.match(first):
                names.append(first)
            for nxt in lines[i + 1:]:
                if NAME_RE.match(nxt):
                    names.append(nxt)
                else:
                    break
            break

    # --- tickets
    tickets = OrderedDict()
    for m in re.finditer(r"E-ticket\s+([A-Z0-9]{2})\s+(\d{3}-?\d{10})\s+for\s+([A-Z][A-Z' \-]*/[A-Z][A-Z' \-]*?)(?=\s+E-ticket|\s*$)", "\n".join(lines), re.M):
        tickets[m.group(3).strip()] = (m.group(1), m.group(2))
    pnr_m = re.search(r"([A-Z0-9]{2}) \(([^)]+)\):\s*([A-Z0-9]{5,8})", flat)
    out["airline"] = pnr_m.group(2).strip() if pnr_m else ""
    out["pnr"] = pnr_m.group(3) if pnr_m else out["booking_ref"]

    for n in tickets:
        if n not in names:
            names.append(n)
    for n in names:
        code, tno = tickets.get(n, ("", ""))
        out["passengers"].append({"name": n, "ticket_no": tno, "airline_code": code})

    # --- segments
    i, n_lines = 0, len(lines)
    while i < n_lines:
        m = DATE_HDR_RE.match(lines[i])
        if not m:
            i += 1
            continue
        year = int(m.group(3))
        i += 1
        header = []
        while i < n_lines and not lines[i].startswith("Departure"):
            if not lines[i].startswith("Scan for check-in") and not DATE_HDR_RE.match(lines[i]):
                header.append(lines[i])
            elif DATE_HDR_RE.match(lines[i]):
                break
            i += 1
        if i >= n_lines or not lines[i].startswith("Departure"):
            continue
        hm = FLIGHT_RE.match(" ".join(header))
        seg = {
            "airline": hm["airline"].strip() if hm else " ".join(header),
            "airline_code": hm["code"] if hm else "",
            "flight_no": (hm["code"] + hm["num"]) if hm else "",
            "operated_by": (hm["op"] or "").strip() if hm else "",
            "pax_info": {}, "layover_before": None,
        }
        cur_label = None
        while i < n_lines and not lines[i].startswith(STOP_LINES) and not DATE_HDR_RE.match(lines[i]):
            l = lines[i]
            dm = DEP_ARR_RE.match(l)
            if dm:
                kind = dm[1].lower()[:3]            # dep / arr
                day, mon, hhmm, rest = dm[2], dm[3], dm[4], dm[5]
                d0 = _mk_date(day, mon, year)
                seg[f"_{kind}_raw"] = (d0, hhmm)
                pm = PLACE_RE.match(rest.strip())
                seg[f"{kind}_city"] = (pm["city"].strip() if pm else rest).strip()
                seg[f"{kind}_airport"] = pm["airport"].strip() if pm else ""
                seg[f"{kind}_terminal"] = (pm["term"] or "").strip() if pm else ""
                cur_label = None
            else:
                label = next((lb for lb in AMADEUS_LABELS if l.startswith(lb + " ") or l == lb), None)
                if label:
                    cur_label, val = label, l[len(label):].strip()
                    _apply_amadeus_value(seg, cur_label, val)
                elif cur_label in ("Baggage allowance", "Seat"):
                    _apply_amadeus_value(seg, cur_label, l)
            i += 1
        # التواريخ (مع التعامل مع تغيّر السنة)
        dep_raw, arr_raw = seg.pop("_dep_raw", None), seg.pop("_arr_raw", None)
        if dep_raw and dep_raw[0]:
            seg["dep_date"], seg["dep_time"] = dep_raw[0].isoformat(), dep_raw[1].zfill(5)
        if arr_raw and arr_raw[0]:
            a = arr_raw[0]
            if dep_raw and dep_raw[0] and a < dep_raw[0]:
                a = a.replace(year=a.year + 1)
            seg["arr_date"], seg["arr_time"] = a.isoformat(), arr_raw[1].zfill(5)
        out["segments"].append(seg)
    return out


def _apply_amadeus_value(seg, label, val):
    if label == "Duration":
        m = re.match(r"^(\d{1,2}:\d{2})\s*(?:\((.+)\))?", val)
        seg["duration"] = m.group(1) if m else val
        seg["stops"] = (m.group(2) or "").strip() if m else ""
    elif label == "Booking status":
        seg["status"] = val
    elif label == "Class":
        seg["cabin"] = val
    elif label == "Equipment":
        seg["aircraft"] = val
    elif label == "Flight meal":
        seg["meal"] = val
    elif label == "Baggage allowance":
        name, bag = _split_name_value(val)
        if name:
            seg["pax_info"].setdefault(name, {})["baggage"] = bag
    elif label == "Seat":
        m = re.match(r"^(\S+)\s+confirmed\s+for\s+(.+)$", val)
        if m:
            seg["pax_info"].setdefault(m.group(2).strip(), {})["seat"] = m.group(1)


# ------------------------------------------------------------------ Jazeera
def _jazeera_segments(pdf_path):
    """الجدول في ملف جزيرة بيتقرا بالإحداثيات (الأعمدة)."""
    import pdfplumber
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
    hdr_names = ["Flight", "From", "To", "Departure", "Arrival", "Class"]
    hdr = None
    for w in words:
        if w["text"] == "Flight":
            line = [x for x in words if abs(x["top"] - w["top"]) < 3 and x["text"] in hdr_names]
            if len({x["text"] for x in line}) >= 5:
                hdr = {x["text"]: x for x in line}
                break
    if not hdr:
        return rows
    cols = [hdr[n]["x0"] for n in hdr_names]
    top0 = hdr["Flight"]["bottom"] + 1
    stop = [w["top"] for w in words if w["text"] == "*" and w["top"] > top0]
    bottom = min(stop) if stop else top0 + 200
    body = [w for w in words if top0 <= w["top"] < bottom]

    def col_of(w):
        idx = 0
        for k, x in enumerate(cols):
            if w["x0"] >= x - 4:
                idx = k
        return idx

    flights = []
    fcol = [w for w in body if col_of(w) == 0]
    fcol.sort(key=lambda w: (w["top"], w["x0"]))
    i = 0
    while i < len(fcol):
        if re.fullmatch(r"[A-Z0-9]{2}", fcol[i]["text"]) and i + 1 < len(fcol) and re.fullmatch(r"\d{1,4}", fcol[i + 1]["text"]):
            flights.append((fcol[i]["top"], fcol[i]["text"], fcol[i + 1]["text"]))
            i += 2
        else:
            i += 1
    for k, (ftop, code, num) in enumerate(flights):
        lo = top0 if k == 0 else (flights[k - 1][0] + ftop) / 2
        hi = bottom if k == len(flights) - 1 else (ftop + flights[k + 1][0]) / 2
        cells = {n: [] for n in hdr_names}
        for w in body:
            if lo <= w["top"] < hi:
                cells[hdr_names[col_of(w)]].append(w)

        def lines_of(name):
            ws = sorted(cells[name], key=lambda w: (round(w["top"]), w["x0"]))
            res, cur, last = [], [], None
            for w in ws:
                if last is not None and abs(w["top"] - last) > 3:
                    res.append(" ".join(cur)); cur = []
                cur.append(w["text"]); last = w["top"]
            if cur:
                res.append(" ".join(cur))
            return res

        rows.append({"code": code, "num": num, "from": lines_of("From"), "to": lines_of("To"),
                     "dep": lines_of("Departure"), "arr": lines_of("Arrival"), "class": lines_of("Class")})
    return rows


def _parse_jazeera(lines, pdf_path):
    flat = "\n".join(lines)
    out = {"source": "jazeera", "airline": "Jazeera Airways", "passengers": [], "segments": [], "warnings": []}
    m = re.search(r"^([A-Z0-9]{6})\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(.+?)\s+(CONFIRMED|TICKETED|HOLD|CANCELLED|CANCELED)\s*$", flat, re.M)
    names_line = ""
    if m:
        out["booking_ref"] = out["pnr"] = m.group(1)
        d = _mk_date(m.group(2), m.group(3), m.group(4))
        out["issue_date"] = d.isoformat() if d else ""
        names_line = m.group(5)
        status = m.group(6).capitalize()
    else:
        out["booking_ref"] = out["pnr"] = ""
        out["issue_date"] = ""
        status = ""

    # أقسام SSR والأمتعة
    sec = None
    ssr, bag = [], []
    row_re = re.compile(r"^(?P<name>.+?)\s+(?P<fl>[A-Z0-9]{2}\s?\d{1,4})\s+(?P<route>[A-Z]{6})\s+(?P<rest>.+)$")
    for l in lines:
        if l.startswith("Special Service Information"):
            sec = "ssr"; continue
        if l.startswith("Baggage Allowance"):
            sec = "bag"; continue
        if l.startswith(("Receipts and Payments", "Fare Rules", "* For handling")):
            sec = None; continue
        mm = row_re.match(l)
        if mm and sec == "ssr":
            ssr.append(mm)
        elif mm and sec == "bag":
            bag.append(mm)

    pax_names = []
    for mm in bag + ssr:
        if mm["name"] not in pax_names:
            pax_names.append(mm["name"])
    if not pax_names and names_line:
        pax_names = [n.strip() for n in re.split(r"\s*,\s*", names_line) if n.strip()]
    out["passengers"] = [{"name": n, "ticket_no": "", "airline_code": "J9"} for n in pax_names]

    for r in _jazeera_segments(pdf_path):
        seg = {"airline": "Jazeera Airways", "airline_code": r["code"], "flight_no": r["code"] + r["num"],
               "operated_by": "", "pax_info": {}, "layover_before": None, "status": status.capitalize() if status else ""}
        seg["dep_city"] = r["from"][0] if r["from"] else ""
        seg["dep_airport"] = _pretty_airport(r["from"][1]) if len(r["from"]) > 1 else ""
        seg["dep_terminal"] = ""
        to = r["to"]
        seg["arr_city"] = to[0] if to else ""
        term = [x for x in to if x.lower().startswith("terminal")]
        rest = [x for x in to[1:] if not x.lower().startswith("terminal")]
        seg["arr_airport"] = _pretty_airport(rest[0]) if rest else ""
        seg["arr_terminal"] = term[0].split(None, 1)[1] if term and len(term[0].split(None, 1)) > 1 else ""
        for kind, key in (("dep", "dep"), ("arr", "arr")):
            ln = r[key]
            tm = re.match(r"^(\d{2})(\d{2})\s*hr$", ln[0]) if ln else None
            dm = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$", ln[1]) if len(ln) > 1 else None
            if tm and dm:
                d0 = _mk_date(dm.group(1), dm.group(2), dm.group(3))
                if d0:
                    seg[f"{kind}_date"] = d0.isoformat()
                    seg[f"{kind}_time"] = f"{tm.group(1)}:{tm.group(2)}"
        seg["cabin"] = r["class"][0] if r["class"] else ""
        fl = f'{r["code"]} {r["num"]}'
        for mm in bag:
            if mm["fl"].replace(" ", "") == fl.replace(" ", ""):
                seg["pax_info"].setdefault(mm["name"], {})["baggage"] = mm["rest"].strip()
                seg["dep_code"], seg["arr_code"] = mm["route"][:3], mm["route"][3:]
        for mm in ssr:
            if mm["fl"].replace(" ", "") == fl.replace(" ", ""):
                code, _, desc = mm["rest"].partition(" ")
                seg["pax_info"].setdefault(mm["name"], {}).setdefault("extras", []).append(desc.strip() or code)
        out["segments"].append(seg)
    return out


# ------------------------------------------------------------------ public API
def parse_ticket_pdf(file_or_path):
    """file_or_path: مسار أو file-like. بيرجّع dict بالبيانات + warnings."""
    try:
        text = extract_text(file_or_path)
    except Exception as e:  # ملف تالف / مش PDF
        return {"source": "", "segments": [], "passengers": [], "warnings": [f"تعذّر قراءة الملف: {e}"]}
    lines = _clean_lines(text)
    flat = " ".join(lines)
    if not lines:
        return {"source": "", "segments": [], "passengers": [],
                "warnings": ["الملف ما فيهوش نص (ممكن يكون صورة ممسوحة). كمّل البيانات يدوي."]}

    if "Jazeera Airways Itinerary" in flat:
        if hasattr(file_or_path, "seek"):
            file_or_path.seek(0)
        out = _parse_jazeera(lines, file_or_path)
    elif "Your trip" in flat and ("Document Issue Date" in flat or "Booking ref" in flat):
        out = _parse_amadeus(lines)
    else:
        return {"source": "", "segments": [], "passengers": [],
                "warnings": ["صيغة الملف غير معروفة. كمّل البيانات يدوي (وابعت الملف عشان نضيف دعمه)."]}

    segs, trip, transit = analyze_trip(out["segments"])
    out["segments"], out["trip_type"], out["has_transit"] = segs, trip, transit
    for s in out["segments"]:  # ترتيب
        s.setdefault("pax_info", {})

    w = out["warnings"]
    if not out["segments"]:
        w.append("ما قدرتش أستخرج رحلات من الملف.")
    for i, s in enumerate(out["segments"], 1):
        missing = [k for k in ("flight_no", "dep_city", "arr_city", "dep_date", "dep_time", "arr_date", "arr_time") if not s.get(k)]
        if missing:
            w.append(f"الرحلة {i}: بيانات ناقصة ({', '.join(missing)}).")
    if not out["passengers"]:
        w.append("ما لقيتش أسماء مسافرين.")
    tk = [p for p in out["passengers"] if p.get("ticket_no")]
    if out["source"] == "amadeus" and out["passengers"] and len(tk) != len(out["passengers"]):
        w.append("عدد أرقام التذاكر لا يساوي عدد المسافرين.")
    if not out.get("pnr"):
        w.append("ما لقيتش PNR.")
    return out

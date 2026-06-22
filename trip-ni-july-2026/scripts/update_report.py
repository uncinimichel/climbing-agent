#!/usr/bin/env python3
"""Build the trip dashboard: free weather (climatology + forecast) ranking with
per-venue flights for BOTH travellers folded into the same table.

Weather signals (free, no key):
  1. CLIMATOLOGY — typical late-July conditions per venue (Open-Meteo archive).
     Ranks the venues now, months ahead.
  2. FORECAST — Open-Meteo 16-day forecast; shown once the trip enters range.

Flights (Google Flights via SerpApi, key from SERPAPI_KEY / gitignored .env):
  For the TOP-N ranked venues we price a representative round-trip for Michel
  (from London) and Dan (from Belfast) into that venue's airport, with view/book
  links. NI venues: Dan is local. UK-mainland: Michel drives. To stay within the
  SerpApi quota we price only the top N venues, one representative combo each.

Outputs: index.html (Pages), daily-report.md, history/<date>.md. Stdlib only.
"""
import csv
import difflib
import json
import math
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
HISTORY = ROOT / "history"
DAILY = ROOT / "daily-report.md"
INDEX = REPO_ROOT / "index.html"

_cfg = json.loads((ROOT / "venues.json").read_text())
TRIP_NAME = _cfg["trip"]
TARGET_START = date.fromisoformat(_cfg["target_window"]["start"])
TARGET_END = date.fromisoformat(_cfg["target_window"]["end"])
VENUES = _cfg["venues"]
FLIGHTS_CFG = json.loads((ROOT / "flights.json").read_text())
FLIGHTS_DATA = json.loads((ROOT / "flights-latest.json").read_text())

CLIMO_YEARS = [2021, 2022, 2023, 2024]
GRAPH_START = TARGET_START - timedelta(days=2)   # 2 days before the trip
GRAPH_END = TARGET_END + timedelta(days=2)       # 2 days after
SITE_URL = "https://multi-pitch.com/"
MP_MAP_URL = "https://multi-pitch.com/map/"
MP_DATA_URL = "https://multi-pitch.com/data/data.json"   # live climb DB (S3-backed)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1N4Xs-aSGFc8-ibysqpdCvQIfMH4Rjx4n5WQnqITGPC8/edit"
CLIMBING_CSV = REPO_ROOT / "climbing-trips.csv"
REPO_URL = "https://github.com/uncinimichel/climbing-agent"


# ---- Data-driven source links (no hardcoded rows/URLs) --------------------
def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)   # keep parenthetical tokens (e.g. "Llanberis")
    return [t for t in s.split() if t not in ("the", "de", "of", "ni", "la", "el")]


def _load_sheet_rows():
    """(sheet_row, area_name) parsed from the venue spreadsheet CSV — true row numbers."""
    rows = []
    try:
        for i, r in enumerate(csv.reader(CLIMBING_CSV.open()), start=1):
            if i >= 3 and r and r[0].strip():     # rows 1-2 are banner/header
                rows.append((i, r[0].strip()))
    except Exception:
        pass
    return rows


SHEET_ROWS = _load_sheet_rows()
MP_CLIMBS = []   # populated at build time from MP_DATA_URL


def match_sheet_row(name):
    """Find the spreadsheet row a venue came from by fuzzy-matching its area name."""
    vt = _norm(name)
    for row, area in SHEET_ROWS:
        at = _norm(area)
        if at and all(any(difflib.SequenceMatcher(None, a, x).ratio() >= 0.8 for x in vt) for a in at):
            return row
    return None


def _haversine(la1, lo1, la2, lo2):
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def nearby_climbs(v, km=50):
    """multi-pitch.com climbs within `km` of the venue, nearest first (from data.json)."""
    out = []
    for c in MP_CLIMBS:
        try:
            la, lo = map(float, c.get("geoLocation", "").split(","))
        except Exception:
            continue
        d = _haversine(v["lat"], v["lon"], la, lo)
        if d <= km:
            out.append((round(d), c.get("cliff", "?")))
    return sorted(out)


def load_mp_climbs():
    try:
        return _get(MP_DATA_URL).get("climbs", [])
    except Exception:
        return []

TOP_N_FLIGHTS = 4
_TO = FLIGHTS_CFG["route"].get("traveller_origins", {})
ORIGIN = {
    "michel": ",".join(_TO.get("michel", FLIGHTS_CFG["route"]["origin_airports"])),   # London
    "dan": ",".join(_TO.get("dan", FLIGHTS_CFG["route"]["dest_airports"])),           # Belfast + Dublin
}
ORIGIN_CITY = {"michel": "London", "dan": "Belfast/Dublin"}
REP = max(FLIGHTS_CFG["combos"], key=lambda c: c["nights"])        # representative round-trip
REP_OUT_LBL = f"{date.fromisoformat(REP['out']):%a %d %b}"          # e.g. "Fri 24 Jul"
REP_BACK_LBL = f"{date.fromisoformat(REP['back']):%a %d %b}"        # e.g. "Tue 28 Jul"
COMBO_LABELS = ", ".join(f"{c['out'][5:]}→{c['back'][5:]} ({c['nights']}n)" for c in FLIGHTS_CFG["combos"])


def weather_url(v):
    """Detailed forecast for the venue (Windy, by coordinates)."""
    return f"https://www.windy.com/?{v['lat']},{v['lon']},9"

WMO = {
    0: "☀️ clear", 1: "🌤️ mostly clear", 2: "⛅ partly cloudy", 3: "☁️ overcast",
    45: "🌫️ fog", 48: "🌫️ rime fog", 51: "🌦️ drizzle", 53: "🌦️ drizzle",
    55: "🌧️ heavy drizzle", 61: "🌧️ light rain", 63: "🌧️ rain", 65: "🌧️ heavy rain",
    71: "🌨️ snow", 73: "🌨️ snow", 75: "❄️ heavy snow", 80: "🌦️ showers",
    81: "🌦️ showers", 82: "⛈️ violent showers", 95: "⛈️ storm", 96: "⛈️ storm", 99: "⛈️ storm",
}

FLAGS = {
    "Northern Ireland": "🇬🇧", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Italy": "🇮🇹", "Austria": "🇦🇹", "Spain": "🇪🇸", "Croatia": "🇭🇷", "France": "🇫🇷", "Ireland": "🇮🇪",
}


def flag(country):
    return FLAGS.get(country, "📍")


def _dotenv():
    f = REPO_ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_dotenv()
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")


def _get(url, retries=4):
    """GET JSON with retries — APIs rate-limit bursts; never silently lose a sample."""
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


# ---- Weather --------------------------------------------------------------
def forecast(lat, lon):
    return _get(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,windspeed_10m_max"
        "&timezone=auto&forecast_days=16"
    )["daily"]


def climatology(lat, lon):
    """Typical trip-window conditions over recent years — ONE ranged request, filtered."""
    d = _get(
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={CLIMO_YEARS[0]}-07-15&end_date={CLIMO_YEARS[-1]}-07-31"
        "&daily=temperature_2m_max,precipitation_sum,windspeed_10m_max&timezone=auto"
    )["daily"]
    tmaxs, winds, rain_days, total = [], [], 0, 0
    per_day = {}   # day-of-month -> {"t","p","w"} lists for the graph window
    for t, tx, pr, wd in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"],
                             d.get("windspeed_10m_max", [None] * len(d["time"]))):
        dd = date.fromisoformat(t)
        if dd.month != TARGET_START.month or tx is None:
            continue
        if GRAPH_START.day <= dd.day <= GRAPH_END.day:          # graph window (trip ±2)
            e = per_day.setdefault(dd.day, {"t": [], "p": [], "w": []})
            e["t"].append(tx)
            e["p"].append(pr or 0)
            e["w"].append(wd or 0)
        if TARGET_START.day <= dd.day <= TARGET_END.day:        # trip window aggregate
            total += 1
            tmaxs.append(tx)
            winds.append(wd or 0)
            if (pr or 0) >= 3:
                rain_days += 1
    if not total:
        return None
    series = []
    for day in range(GRAPH_START.day, GRAPH_END.day + 1):
        pd = per_day.get(day)
        if not pd:
            continue
        series.append({"day": day,
                       "tmax": round(sum(pd["t"]) / len(pd["t"])),
                       "precip": round(sum(pd["p"]) / len(pd["p"]), 1),
                       "wind": round(sum(pd["w"]) / len(pd["w"])),
                       "trip": TARGET_START.day <= day <= TARGET_END.day})
    return {"tmax": round(sum(tmaxs) / len(tmaxs)), "rain_pct": round(100 * rain_days / total),
            "wind": round(sum(winds) / len(winds)), "days": total, "series": series}


def seasonal(lat, lon):
    """Sub-seasonal (45-day) outlook for the trip window from Open-Meteo's free
    Seasonal Forecast API (CFS ensemble, no key). Averages the ensemble members."""
    d = _get(
        "https://seasonal-api.open-meteo.com/v1/seasonal"
        f"?latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_max,precipitation_sum&forecast_days=45&timezone=auto"
    )["daily"]
    times = d["time"]
    tkeys = [k for k in d if k.startswith("temperature_2m_max")]
    pkeys = [k for k in d if k.startswith("precipitation_sum")]
    tmaxs, precs, wet, total = [], [], 0, 0
    for i, day in enumerate(times):
        if not (TARGET_START <= date.fromisoformat(day) <= TARGET_END):
            continue
        tvals = [d[k][i] for k in tkeys if i < len(d[k]) and d[k][i] is not None]
        pvals = [d[k][i] for k in pkeys if i < len(d[k]) and d[k][i] is not None]
        if not tvals:
            continue
        total += 1
        tmaxs.append(sum(tvals) / len(tvals))
        mp = sum(pvals) / len(pvals) if pvals else 0
        precs.append(mp)
        if mp >= 3:
            wet += 1
    if not total:
        return None
    return {"tmax": round(sum(tmaxs) / len(tmaxs)), "rain_pct": round(100 * wet / total),
            "precip": round(sum(precs) / len(precs), 1), "members": max(1, len(tkeys))}


def day_score(code, mm, prob):
    s = 100.0 - (prob or 0) * 0.8 - (mm or 0) * 6
    if code is not None and code >= 61:
        s = min(s, 25)
    if code in (95, 96, 99):
        s = min(s, 15)
    return max(0.0, min(100.0, s))


def climo_score(c):
    s = 100 - c["rain_pct"] * 0.9
    s -= max(0, 10 - c["tmax"]) * 1.5
    s -= max(0, c["tmax"] - 32) * 1.5
    return max(0, min(100, round(s)))


def evaluate(v):
    res = {"venue": v, "ok": True, "climo": None, "fc": None, "seasonal": None}
    try:
        res["climo"] = climatology(v["lat"], v["lon"])
    except Exception:
        res["climo"] = None
    try:
        res["seasonal"] = seasonal(v["lat"], v["lon"])
    except Exception:
        res["seasonal"] = None
    try:
        d = forecast(v["lat"], v["lon"])
        days = d["time"]
        valid = [i for i in range(len(days)) if d["temperature_2m_max"][i] is not None]
        in_win = [i for i in valid if TARGET_START <= date.fromisoformat(days[i]) <= TARGET_END]
        if in_win:
            scores = [day_score(d["weathercode"][i], d["precipitation_sum"][i],
                                d["precipitation_probability_max"][i]) for i in in_win]
            codes = [d["weathercode"][i] for i in in_win]
            res["fc"] = {
                "score": round(sum(scores) / len(scores)),
                "tmax": round(sum(d["temperature_2m_max"][i] for i in in_win) / len(in_win)),
                "rain_prob": max((d["precipitation_probability_max"][i] or 0) for i in in_win),
                "sky": WMO.get(max(set(codes), key=codes.count), "?"),
                "in_window": True, "horizon": days[-1],
            }
        else:
            res["fc"] = {"in_window": False, "horizon": days[-1] if days else "?"}
    except Exception:
        res["fc"] = None

    fc, sea = res["fc"], res["seasonal"]
    if fc and fc.get("in_window"):
        res["score"], res["basis"] = fc["score"], "live forecast (trip window)"
    elif res["climo"]:
        cs = climo_score(res["climo"])
        if sea:
            # gentle blend: climatology dominant, 45-day outlook nudges it
            ss = climo_score({"tmax": sea["tmax"], "rain_pct": sea["rain_pct"]})
            res["score"] = round(0.7 * cs + 0.3 * ss)
            res["basis"] = "typical July + 45-day outlook"
        else:
            res["score"], res["basis"] = cs, "typical July (climatology)"
    else:
        res["score"], res["basis"] = -1, "no data"
    return res


def prio_num(v):
    for ch in v.get("priority", "9"):
        if ch.isdigit():
            return int(ch)
    return 9


def rank(results):
    ok = [r for r in results if r.get("ok") and r["score"] >= 0]
    ok.sort(key=lambda r: (-r["score"], prio_num(r["venue"])))
    return ok + [r for r in results if r not in ok]


# ---- Flights (SerpApi / Google Flights) -----------------------------------
def skyscanner_url(dep, arr, out_date, back_date):
    def yymmdd(s):
        return f"{date.fromisoformat(s):%y%m%d}"
    return (f"https://www.skyscanner.net/transport/flights/"
            f"{dep.lower()}/{arr.lower()}/{yymmdd(out_date)}/{yymmdd(back_date)}/")


def _hhmm(t):
    # "2026-07-24 06:25" -> "06:25"
    return t[-5:] if t and len(t) >= 5 else "—"


def serp_flights(dep, arr, out_date, back_date):
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": dep, "arrival_id": arr,
        "outbound_date": out_date, "return_date": back_date,
        "currency": "GBP", "hl": "en", "gl": "uk", "type": "1",
        "adults": FLIGHTS_CFG["route"]["passengers"], "api_key": SERPAPI_KEY,
    })
    data = _get(f"https://serpapi.com/search.json?{q}", retries=2)
    opts = []
    for o in (data.get("best_flights") or []) + (data.get("other_flights") or []):
        price = o.get("price")
        legs = o.get("flights") or []
        if price is None or not legs:
            continue
        dep_ap = legs[0].get("departure_airport", {})
        arr_ap = legs[-1].get("arrival_airport", {})
        opts.append({
            "price": round(price), "airline": legs[0].get("airline", "?"),
            "from": dep_ap.get("id", dep.split(",")[0]), "to": arr_ap.get("id", arr),
            "dep": _hhmm(dep_ap.get("time")), "arr": _hhmm(arr_ap.get("time")),
            "stops": max(0, len(legs) - 1),
        })
    if not opts:
        return None
    # rank by best value: price plus a £40 penalty per stop (a cheap 1-stop can
    # beat a pricey nonstop, but stops are penalised). Bolded option = best value.
    opts.sort(key=lambda x: x["price"] + 40 * x["stops"])
    seen, uniq = set(), []
    for o in opts:
        k = (o["from"], o["dep"], o["price"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    top = uniq[:3]
    google = (data.get("search_metadata") or {}).get("google_flights_url")
    return {
        "mode": "fly", "to": arr, "options": top,
        "view_url": google or skyscanner_url(top[0]["from"], arr, out_date, back_date),
        "book_url": skyscanner_url(top[0]["from"], arr, out_date, back_date),
    }


def traveller_flight(venue, who):
    """Return a flight cell dict for one traveller to this venue."""
    t = venue.get("travel", {}).get(who, {})
    mode = t.get("mode")
    if mode in ("local", "drive"):
        return {"mode": mode}
    if mode == "fly" and SERPAPI_KEY:
        try:
            f = serp_flights(ORIGIN[who], t["to"], REP["out"], REP["back"])
            if f:
                return f
        except Exception:
            pass
    # no key / no result / error: still offer a search link so it's actionable
    if mode == "fly":
        return {"mode": "fly", "options": [], "to": t.get("to"),
                "book_url": skyscanner_url(ORIGIN[who].split(",")[0], t["to"], REP["out"], REP["back"])}
    return {"mode": "unknown"}


def attach_flights(ranked):
    """Price flights for the top-N venues (both travellers); cache to flights-latest.json."""
    cache = {}
    for r in ranked[:TOP_N_FLIGHTS]:
        if not r.get("ok") or r["score"] < 0:
            continue
        v = r["venue"]
        r["flights"] = {w: traveller_flight(v, w) for w in ("michel", "dan")}
        cache[v["name"]] = r["flights"]
    # persist (so history captures prices and a no-key run can reuse them)
    FLIGHTS_DATA["rep_combo"] = REP
    FLIGHTS_DATA["venues"] = cache
    FLIGHTS_DATA["checked_at"] = (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                                  + (" (Google Flights/SerpApi)" if SERPAPI_KEY else " (no key — links only)"))
    (ROOT / "flights-latest.json").write_text(json.dumps(FLIGHTS_DATA, indent=2) + "\n")


# ---- HTML -----------------------------------------------------------------
def score_color(s):
    if s < 0:
        return "#9aa4b2"
    return "#16a34a" if s >= 70 else "#d97706" if s >= 45 else "#dc2626"


def maps_url(v):
    return f"https://www.google.com/maps/search/?api=1&query={v['lat']},{v['lon']}"


def source_links(v):
    """Per-venue links back to the raw sources — all derived at build time:
    multi-pitch.com climbs near the venue (from data.json) + its spreadsheet row (from CSV)."""
    nb = nearby_climbs(v)
    if nb:
        title = "nearest: " + ", ".join(f"{c} ({d}km)" for d, c in nb[:3])
        mp = (f"<a class='src' href='{MP_MAP_URL}' target='_blank' rel='noopener' "
              f"title='{title}'>🧗 {len(nb)} on multi-pitch</a>")
    else:
        mp = f"<a class='src' href='{MP_MAP_URL}' target='_blank' rel='noopener'>🧗 multi-pitch map</a>"
    row = match_sheet_row(v["name"])
    if row:
        sheet = (f"<a class='src' href='{SHEET_URL}#gid=0&range={row}:{row}' "
                 f"target='_blank' rel='noopener'>📋 sheet row {row}</a>")
    else:
        sheet = "<span class='src dim'>📋 not in sheet</span>"
    return f"{mp} · {sheet}"


def flight_html(f):
    if not f:
        return "<span class='dim'>—</span>"
    if f["mode"] == "local":
        return "🚗 <b>local</b><div class='vsub'>Dan lives here</div>"
    if f["mode"] == "drive":
        return "🚗 drive / train"
    opts = f.get("options") or []
    url = f.get("view_url") or f.get("book_url")
    dates = f"<div class='fdates'>🛫 {REP_OUT_LBL} · 🛬 {REP_BACK_LBL}</div>"
    if not opts:
        return (dates + f"<span class='dim'>to {f.get('to','?')}</span> "
                f"<a class='flink' href='{url}' target='_blank' rel='noopener'>search ↗</a>" if url else dates + "—")
    out = [dates]
    for i, o in enumerate(opts):
        st = "direct" if o["stops"] == 0 else f"{o['stops']}-stop"
        strong = "b" if i == 0 else "span"
        out.append(f"<div class='opt'><{strong}>£{o['price']}</{strong}> "
                   f"<span class='t' title='outbound time'>{o['dep']}→{o['arr']}</span> "
                   f"<span class='vsub'>{o['from']} · {o['airline'][:8]} · {st}</span></div>")
    out.append(f"<a class='flink' href='{url}' target='_blank' rel='noopener'>book ↗</a>")
    return "".join(out)


def weather_mini_svg(series, W=300, H=104):
    """Per-row SVG: daily rain bars + high-temp line + wind line over the trip ±2 days.
    Scales to the cell (viewBox); axis/labels use currentColor so dark mode adapts."""
    if not series:
        return ""
    padL, padR, padT, padB = 7, 24, 10, 18
    n = len(series)
    plotW = W - padL - padR
    bw = plotW / n
    plotH = H - padT - padB
    base = padT + plotH
    pmax = max([s["precip"] for s in series] + [6.0])
    tmn = min(s["tmax"] for s in series)
    tmx = max(s["tmax"] for s in series)
    trng = max(1, tmx - tmn)
    wmx = max([s.get("wind", 0) for s in series] + [1])
    parts = [f"<line x1='{padL}' y1='{base:.0f}' x2='{W-padR}' y2='{base:.0f}' "
             f"stroke='currentColor' stroke-width='1' opacity='.18'/>"]
    trip = [i for i, s in enumerate(series) if s["trip"]]
    if trip:
        x0 = padL + trip[0] * bw
        x1 = padL + (trip[-1] + 1) * bw
        parts.append(f"<rect x='{x0:.1f}' y='{padT}' width='{x1-x0:.1f}' height='{plotH}' "
                     f"fill='rgba(37,99,235,.13)' rx='4'/>")
        parts.append(f"<text x='{(x0+x1)/2:.0f}' y='{padT+8}' text-anchor='middle' font-size='8' "
                     f"fill='#2563eb' opacity='.8'>trip</text>")
    pts, wpts = [], []
    for i, s in enumerate(series):
        x = padL + i * bw
        bh = plotH * (s["precip"] / pmax)
        col = "#16a34a" if s["precip"] < 3 else "#d97706" if s["precip"] < 8 else "#dc2626"
        parts.append(f"<rect x='{x+bw*0.2:.1f}' y='{base-bh:.1f}' width='{bw*0.6:.1f}' "
                     f"height='{max(bh,1.0):.1f}' fill='{col}' opacity='.85' rx='1.5'>"
                     f"<title>{s['day']} Jul · {s['precip']}mm rain · {s['tmax']}°C · 💨{s.get('wind',0)}km/h</title></rect>")
        pts.append(f"{x+bw/2:.1f},{padT+plotH*(1-(s['tmax']-tmn)/trng):.1f}")
        wpts.append(f"{x+bw/2:.1f},{padT+plotH*(1-s.get('wind',0)/wmx):.1f}")
        parts.append(f"<text x='{x+bw/2:.1f}' y='{H-5}' text-anchor='middle' font-size='8.5' "
                     f"fill='currentColor' opacity='.55'>{s['day']}</text>")
    parts.append(f"<polyline points='{' '.join(wpts)}' fill='none' stroke='#3b82f6' "
                 f"stroke-width='1.4' stroke-dasharray='3 2' opacity='.9'/>")
    parts.append(f"<polyline points='{' '.join(pts)}' fill='none' stroke='#e6792b' stroke-width='1.8'/>")
    for p in pts:
        cx, cy = p.split(",")
        parts.append(f"<circle cx='{cx}' cy='{cy}' r='1.8' fill='#e6792b'/>")
    # temp range labels on the right axis
    parts.append(f"<text x='{W-padR+3}' y='{padT+4}' font-size='8.5' fill='#e6792b'>{tmx}°</text>")
    parts.append(f"<text x='{W-padR+3}' y='{base}' font-size='8.5' fill='#e6792b'>{tmn}°</text>")
    return (f"<svg class='wxsvg' viewBox='0 0 {W} {H}' width='100%' preserveAspectRatio='xMidYMid meet' "
            f"role='img' aria-label='daily rain, temperature and wind'>{''.join(parts)}</svg>")


def graph_legend():
    return ("<div class='glegend'>"
            "<span><i class='sw rain'></i>rain (mm)</span>"
            "<span><i class='sw temp'></i>high °C</span>"
            "<span><i class='sw wind'></i>wind (km/h)</span>"
            "<span><i class='sw trip'></i>trip days</span></div>")


def weather_card(r):
    c = r.get("climo") or {}
    fc = r.get("fc")
    sea = r.get("seasonal")
    num = (f"<b>{c.get('tmax','?')}°C</b> · {c.get('rain_pct','?')}% wet days · 💨{c.get('wind','?')} km/h"
           if c else "—")
    live = (f" · live: {fc['sky']} {fc['tmax']}°C/{fc['rain_prob']}%" if fc and fc.get("in_window") else "")
    outlook = ""
    if sea and not (fc and fc.get("in_window")):
        dry = "mostly dry" if sea["rain_pct"] <= 30 else "mixed" if sea["rain_pct"] <= 55 else "wet"
        outlook = (f"<div class='outlook'>🔭 <b>45-day outlook:</b> {sea['tmax']}°C · {sea['rain_pct']}% wet days · "
                   f"{dry} <span class='vsub'>(experimental {sea['members']}-member ensemble)</span></div>")
    graph = weather_mini_svg(c.get("series"), W=340, H=140) if c.get("series") else ""
    return (f"<div class='wxnum'>{num}{live} · "
            f"<a class='flink' href='{weather_url(r['venue'])}' target='_blank' rel='noopener'>full forecast ↗</a></div>"
            f"{outlook}{graph_legend()}{graph}")


def flights_card(r):
    fl = r.get("flights") or {}
    cols = ""
    for who, lbl in (("michel", "✈️ Michel — from London"),
                     ("dan", "✈️ Dan — from Belfast / Dublin")):
        cols += f"<div class='fcol'><h4>{lbl}</h4>{flight_html(fl.get(who))}</div>"
    return f"<div class='flights'>{cols}</div>"


def venue_card(n, r):
    v = r["venue"]
    if not r.get("ok") or r["score"] < 0:
        return (f"<div class='vcard'><div class='vhead'><span class='rank'>{n}</span>"
                f"<span class='vname'>{flag(v['country'])} {v['name']}<small>{v['country']}</small></span>"
                f"<span class='pill' style='background:#9aa4b2'>n/a</span></div>"
                f"<p class='why dim'>No weather data available right now.</p></div>")
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, f"{n}")
    best = n == 1
    tag = "<span class='tag'>📍 best option right now</span>" if best else ""
    why = f"<p class='why'>{v.get('why','')}</p>" if best else ""
    return (
        f"<div class='vcard{' best' if best else ''}'>{tag}"
        f"<div class='vhead'><span class='rank'>{medal}</span>"
        f"<span class='vname'>{flag(v['country'])} "
        f"<a href='{maps_url(v)}' target='_blank' rel='noopener'>{v['name']} 🗺️</a>"
        f"<small>{v['country']} · {v.get('style','')}</small></span>"
        f"<span class='pill' style='background:{score_color(r['score'])}'>{r['score']}</span></div>"
        f"{why}{weather_card(r)}{flights_card(r)}"
        f"<div class='srcs'>{source_links(v)}</div></div>"
    )


def build_html(ranked, now, banner):
    cards = "\n".join(venue_card(n, r) for n, r in enumerate(ranked, 1))
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Climbing Trip Planner — Michel &amp; Dan · ~24 Jul 2026</title>
<style>
:root{{--bg:#eef1f6;--card:#fff;--ink:#1f2733;--dim:#7b8694;--line:#e6eaf0;--accent:#2563eb;
--shadow:0 1px 3px rgba(16,24,40,.08),0 2px 8px rgba(16,24,40,.05);}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0b0f17;--card:#141a24;--ink:#e7edf5;--dim:#8b97a7;
--line:#222c3a;--accent:#5b9dff;--shadow:0 1px 3px rgba(0,0,0,.5);}}}}
*{{box-sizing:border-box}}html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;padding:24px 16px}}
.wrap{{max-width:820px;margin:0 auto}}
h1{{font-size:22px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}}
.lead{{color:var(--dim);font-size:14px;margin:0}}.lead b{{color:var(--ink)}}
.links{{margin:8px 0 0;font-size:13.5px}}
.links a{{color:var(--accent);text-decoration:none;font-weight:600}}.links a:hover{{text-decoration:underline}}
.banner{{margin:16px 0;padding:12px 15px;border-radius:12px;font-size:13.5px;line-height:1.45;
background:#fff7e6;border:1px solid #f3d18a;color:#7a5a12}}
@media(prefers-color-scheme:dark){{.banner{{background:#241d0e;border-color:#5c4a1e;color:#e7cf94}}}}
.banner.ok{{background:#e9f9ef;border-color:#a6e3bd;color:#176436}}
@media(prefers-color-scheme:dark){{.banner.ok{{background:#0f2418;border-color:#235c39;color:#86e0a6}}}}
.vcard{{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);
padding:16px 18px;margin:0 0 16px}}
.vcard.best{{border:2px solid var(--accent)}}
.tag{{display:inline-block;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;
color:var(--accent);background:rgba(37,99,235,.1);padding:3px 9px;border-radius:20px;margin-bottom:8px}}
.vhead{{display:flex;align-items:center;gap:10px}}
.rank{{font-size:21px;font-weight:800;min-width:30px;text-align:center}}
.vname{{font-weight:800;font-size:17px;flex:1;line-height:1.2}}
.vname a{{color:inherit;text-decoration:none}}.vname a:hover{{color:var(--accent)}}
.vname small{{display:block;font-weight:500;font-size:12px;color:var(--dim);margin-top:2px}}
.pill{{color:#fff;font-weight:800;font-size:16px;padding:5px 12px;border-radius:10px;align-self:flex-start}}
.why{{font-size:13.5px;line-height:1.5;color:var(--ink);margin:10px 0 4px}}.why.dim{{color:var(--dim)}}
.wxnum{{font-size:13.5px;margin:10px 0 4px}}
.outlook{{font-size:12.5px;background:rgba(91,157,255,.1);border:1px solid rgba(91,157,255,.3);
border-radius:8px;padding:6px 10px;margin:0 0 6px}}
.glegend{{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--dim);margin:2px 0 2px}}
.glegend i{{display:inline-block;width:16px;height:9px;border-radius:2px;margin-right:5px;vertical-align:middle}}
.sw.rain{{background:linear-gradient(90deg,#16a34a,#d97706,#dc2626)}}
.sw.temp{{height:0;border-top:2px solid #e6792b}}
.sw.wind{{height:0;border-top:2px dashed #3b82f6}}
.sw.trip{{background:rgba(37,99,235,.18)}}
.wxsvg{{display:block;margin:4px 0 8px;width:100%;max-width:520px;height:auto}}
.flights{{display:flex;gap:12px;flex-wrap:wrap}}
.fcol{{flex:1;min-width:215px;background:rgba(127,127,127,.05);border:1px solid var(--line);
border-radius:12px;padding:10px 12px}}
.fcol h4{{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim)}}
.fdates{{font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px}}
.opt{{margin-bottom:3px;font-size:13px}}.opt .t{{font-variant-numeric:tabular-nums;color:var(--ink)}}
.vsub{{color:var(--dim);font-size:12px}}
.flink{{color:var(--accent);text-decoration:none;font-weight:600;font-size:12.5px}}
.flink:hover{{text-decoration:underline}}
.srcs{{margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);font-size:11.5px}}
.src{{color:var(--accent);text-decoration:none;font-weight:600}}.src:hover{{text-decoration:underline}}
.src.dim{{color:var(--dim);font-weight:400}}
.dim{{color:var(--dim)}}
footer{{color:var(--dim);font-size:12px;text-align:center;margin-top:6px;line-height:1.7}}
footer a{{color:var(--accent);text-decoration:none}}
@media(max-width:560px){{.fcol{{min-width:100%}} .wxsvg{{max-width:100%}}}}
</style></head><body><div class="wrap">
<header>
<h1>🧗 Climbing Trip Planner — where should Michel &amp; Dan go?</h1>
<p class="lead">Multi-pitch trip <b>Fri 24 – Tue 28 Jul 2026</b> · ranked best-first · updated {now:%a %d %b %Y, %H:%M UTC}</p>
<div class="links"><a href="{SITE_URL}" target="_blank" rel="noopener">🧗 multi-pitch.com</a> ·
<a href="{SHEET_URL}" target="_blank" rel="noopener">📋 venue spreadsheet</a> ·
<span class="dim">🗺️ tap a venue name for Maps</span></div>
</header>
<div class="banner {banner[0]}">{banner[1]}</div>
{cards}
<footer>Score 0–100 (higher = drier). Weather = typical late-July, avg {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]} (live forecast within 16 days). Flights = top {TOP_N_FLIGHTS} venues, best value, outbound times (book ↗ for return/dates). Dan local in NI.<br>
Weather: Open-Meteo (free). Flights: Google Flights via SerpApi, updated daily.<br>
<a href="{SITE_URL}" target="_blank" rel="noopener">multi-pitch.com</a> ·
<a href="{SHEET_URL}" target="_blank" rel="noopener">venue spreadsheet</a> ·
<a href="{REPO_URL}" target="_blank" rel="noopener">source &amp; daily history</a></footer>
</div></body></html>
"""


def build_md(ranked, now, banner):
    def fcell(f):
        if not f:
            return "—"
        if f["mode"] == "local":
            return "local (Dan)"
        if f["mode"] == "drive":
            return "drive/train"
        url = f.get("view_url") or f.get("book_url")
        opts = f.get("options") or []
        if not opts:
            return f"[search]({url})" if url else "n/a"
        parts = "; ".join(f"£{o['price']} {o['dep']}→{o['arr']} {o['from']} {'direct' if o['stops']==0 else str(o['stops'])+'st'}" for o in opts)
        return f"{parts} [book]({url})"

    lines = [f"# {TRIP_NAME}", "",
             f"**Updated:** {now:%Y-%m-%d %H:%M UTC} · ranked best-first.", "",
             f"> {banner[1]}", "",
             f"**Links:** [multi-pitch.com]({SITE_URL}) · [venue spreadsheet]({SHEET_URL}) · "
             f"[live dashboard](https://uncinimichel.github.io/climbing-agent/)", "",
             "## 🏆 Venues + flights (best first)", "",
             "| # | Venue | Score | Typical July | ✈️ Michel (London) | ✈️ Dan (Belfast) |",
             "|---|---|---|---|---|---|"]
    for n, r in enumerate(ranked, 1):
        v = r["venue"]
        if not r.get("ok") or r["score"] < 0:
            lines.append(f"| {n} | {v['name']} | – | – | – | – |")
            continue
        c = r.get("climo")
        cstr = f"{c['tmax']}°C, {c['rain_pct']}% wet" if c else "–"
        fl = r.get("flights") or {}
        nb = nearby_climbs(v)
        row = match_sheet_row(v["name"])
        src = (f"[mp map]({MP_MAP_URL})" + (f" ({len(nb)})" if nb else "")
               + (f" · [sheet r{row}]({SHEET_URL}#gid=0&range={row}:{row})" if row else " · not in sheet"))
        lines.append(f"| {n} | {flag(v['country'])} {v['name']}<br><sub>{src}</sub> | {r['score']} | {cstr} | {fcell(fl.get('michel'))} | {fcell(fl.get('dan'))} |")
    lines += ["", f"_Flights: top {TOP_N_FLIGHTS} venues, return {REP['out']}→{REP['back']} ({REP['nights']}n); "
              f"date options: {COMBO_LABELS}. Use the book links to adjust. Rendered dashboard: "
              "https://uncinimichel.github.io/climbing-agent/_"]
    return "\n".join(lines) + "\n"


def main():
    global MP_CLIMBS
    MP_CLIMBS = load_mp_climbs()
    print(f"multi-pitch climbs loaded: {len(MP_CLIMBS)}")
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    results = [evaluate(v) for v in VENUES]
    ranked = rank(results)
    attach_flights(ranked)

    in_window = any(r.get("fc") and r["fc"].get("in_window") for r in ranked)
    horizon = next((r["fc"]["horizon"] for r in ranked if r.get("fc")), "?")
    if in_window:
        banner = ("ok", "✅ Trip dates are within the 16-day forecast — venues ranked on the <b>actual trip-window forecast</b>.")
    else:
        days_out = (TARGET_START - now.date()).days
        has_sea = any(r.get("seasonal") for r in ranked)
        sea_txt = (" blended with the <b>45-day sub-seasonal outlook</b> (shown per venue)" if has_sea else "")
        banner = ("", f"📅 Trip is {days_out} days out — beyond the 16-day live forecast (reaches {horizon}). "
                      f"Ranked on <b>typical late-July weather</b> ({CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]}){sea_txt}. "
                      f"Full live forecast fills in from ~8 July.")

    INDEX.write_text(build_html(ranked, now, banner))
    md = build_md(ranked, now, banner)
    DAILY.write_text(md)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(md)
    print(f"Wrote index.html, daily-report.md, history/{today}.md")
    print("Ranking:", " > ".join(r["venue"]["name"] for r in ranked if r.get("ok") and r["score"] >= 0))


if __name__ == "__main__":
    main()

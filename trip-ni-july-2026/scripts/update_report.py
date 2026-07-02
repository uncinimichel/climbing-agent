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
def maps_url(v):
    return f"https://www.google.com/maps/search/?api=1&query={v['lat']},{v['lon']}"


def wx_band(rain_pct):
    """Weather → dry/mixed/wet band (same thresholds as the seasonal-outlook copy)."""
    if rain_pct is None:
        return ("Mixed", "mix")
    return ("Dry", "go") if rain_pct <= 30 else ("Mixed", "mix") if rain_pct <= 55 else ("Wet", "wet")


def arc_color(band_cls):
    return {"go": "#C4FF5C", "mix": "#C8A44A", "wet": "#B94438"}.get(band_cls, "#C8A44A")


_GRADE_NORM = {"VDiff": "VD", "V Diff": "VD", "Diff": "D", "Mod": "M", "Moderate": "M",
               "Severe": "S", "Hard Severe": "HS", "Very Severe": "VS", "Hard Very Severe": "HVS"}
GRADE_ORDER = ["M", "D", "VD", "S", "HS", "VS", "HVS", "E1", "E2", "E3", "E4", "E5", "E6", "E7"]


def _grade_norm(g):
    g = (g or "").strip()
    return _GRADE_NORM.get(g, g)


def grade_range(cards):
    idx = sorted({GRADE_ORDER.index(_grade_norm(c["tradGrade"]))
                  for c in cards if _grade_norm(c.get("tradGrade")) in GRADE_ORDER})
    if not idx:
        return ""
    lo, hi = GRADE_ORDER[idx[0]], GRADE_ORDER[idx[-1]]
    return lo if lo == hi else f"{lo}–{hi}"


def _climb_flags(c):
    labels = [("seepage", "Seepage after rain"), ("loose", "Loose rock"), ("abseil", "Abseil descent"),
              ("tidal", "Tidal"), ("boat", "Boat approach"), ("polished", "Polished rock")]
    return [txt for key, txt in labels if c.get(key)]


def nearby_climb_cards(v, km=60, limit=6):
    """Full climb dicts (image + grade + flags) for multi-pitch.com routes near the venue."""
    out = []
    for c in MP_CLIMBS:
        try:
            la, lo = map(float, c.get("geoLocation", "").split(","))
        except Exception:
            continue
        d = _haversine(v["lat"], v["lon"], la, lo)
        if d <= km:
            img = (c.get("tileImage") or {}).get("url")
            out.append((round(d), {
                "cliff": c.get("cliff", "?"),
                "route": c.get("routeName", ""),
                "grade": c.get("originalGrade") or c.get("tradGrade") or "",
                "tradGrade": c.get("tradGrade", ""),
                "pitches": c.get("pitches"),
                "length": c.get("length"),
                "approach": c.get("approachTime"),
                "dist": round(d),
                "img": (SITE_URL.rstrip("/") + "/" + img) if img else None,
                "flags": _climb_flags(c),
            }))
    out.sort(key=lambda x: x[0])
    return [c for _, c in out[:limit]]


# ---- Accommodation + guidebook: MOCK sample data (flights & weather are live) ----
# Stays are illustrative placeholders near each venue, labelled "sample" in the UI.
def _booking(town):
    return "https://www.booking.com/searchresults.html?ss=" + urllib.parse.quote(town)


def _amazon(q):
    return "https://www.amazon.co.uk/s?k=" + urllib.parse.quote(q)


MOCK_STAYS = {
    "Fair Head": ("Ballycastle", "£", [
        ("Marine Hotel", "Hotel · Ballycastle · 20min to crag", 4, 98, ["Sea views", "Drying room", "Restaurant"]),
        ("Fair Head Campsite", "Campsite · Coolanlough · at the crag", 2, 12, ["Climber-run", "Walk to routes", "Basic"]),
    ], ("Fair Head — A Rock Climbing Guide", "NIMC", 25)),
    "Mournes": ("Newcastle", "£", [
        ("Slieve Donard Resort", "Hotel · Newcastle · 20min to crags", 5, 115, ["Mountain views", "Spa", "Restaurant"]),
        ("Meelmore Lodge", "Bunkhouse · Bryansford · 10min to crags", 2, 28, ["Climber-friendly", "Campsite", "Café"]),
    ], ("Mourne Mountains — Rock Climbs", "NIMC", 20)),
    "Dolomites": ("Cortina d'Ampezzo", "€", [
        ("Rifugio Scoiattoli", "Mountain hut · Cinque Torri · at the routes", 3, 65, ["Half-board", "At the crag", "Cable car"]),
        ("Camping Cortina", "Campsite · Cortina · valley base", 2, 30, ["Cheap base", "Shuttle", "Restaurant"]),
    ], ("Dolomites — Rockfax", "Rockfax", 30)),
    "East Tyrol": ("Lienz", "€", [
        ("Hotel Traube", "Hotel · Lienz · valley base", 4, 105, ["Central", "Breakfast", "Restaurant"]),
        ("Camping Falken", "Campsite · Lienz · 5min to centre", 2, 26, ["Cheap base", "Pool", "Family-run"]),
    ], ("Osttirol — Alpinkletterfuehrer", "Panico", 34)),
    "Lake District": ("Keswick", "£", [
        ("The Borrowdale Hotel", "Hotel · Borrowdale · 10min to crags", 4, 110, ["Valley base", "Drying room", "Restaurant"]),
        ("Borrowdale YHA", "Hostel · Borrowdale · under the crags", 2, 32, ["Climber classic", "Self-catering", "Cheap"]),
    ], ("Lake District — Rockfax", "Rockfax", 28)),
    "Snowdonia": ("Llanberis", "£", [
        ("The Heights", "Inn · Llanberis · 10min to the Pass", 3, 78, ["Climber pub", "Drying room", "Bar"]),
        ("Ynys Ettws (CC hut)", "Hut · Llanberis Pass · at the crags", 2, 15, ["Members' hut", "Walk to routes", "Basic"]),
    ], ("Llanberis — Climbers Club Guide", "Climbers Club", 25)),
    "Arran": ("Brodick", "£", [
        ("Auchrannie Resort", "Hotel · Brodick · 40min to Cir Mhor", 4, 120, ["Pool", "Restaurant", "Spa"]),
        ("Glen Rosa Campsite", "Campsite · Glen Rosa · start of the walk-in", 1, 10, ["At the glen", "Basic", "Cheap"]),
    ], ("Arran — SMC Climbers Guide", "SMC", 24)),
    "Picos": ("Arenas de Cabrales", "€", [
        ("Hotel Picos de Europa", "Hotel · Arenas de Cabrales · gorge base", 3, 72, ["Mountain base", "Breakfast", "Bar"]),
        ("Refugio de Urriellu", "Mountain hut · below Naranjo · at the routes", 2, 18, ["Half-board", "At the wall", "Alpine"]),
    ], ("Picos de Europa — Rockfax", "Rockfax", 30)),
    "Paklenica": ("Starigrad", "€", [
        ("Hotel Alan", "Hotel · Starigrad · 10min to the canyon", 4, 88, ["Sea + mountains", "Pool", "Restaurant"]),
        ("NP Paklenica Camp", "Campsite · canyon mouth · at the crag", 2, 22, ["At the crag", "Cheap", "Shaded"]),
    ], ("Paklenica — Climbing Guide", "Astroida", 28)),
}


def mock_stays(v):
    key = next((k for k in MOCK_STAYS if k in v["name"]), None)
    if not key:
        return [], None
    town, cur, rows, guide = MOCK_STAYS[key]
    hotels = [{"name": n, "type": t, "stars": s, "price": f"{cur}{p}",
               "tags": tags, "book": _booking(town)} for (n, t, s, p, tags) in rows]
    g = {"title": guide[0], "pub": guide[1], "price": f"£{guide[2]}", "url": _amazon(guide[0])}
    return hotels, g


def _short_name(name):
    return name.split("(")[0].split(",")[0].strip()


def venue_payload(n, r):
    """One venue's data as a plain dict → embedded as JSON and rendered client-side."""
    v = r["venue"]
    ok = bool(r.get("ok") and r["score"] >= 0)
    c = r.get("climo") or {}
    fc = r.get("fc")
    sea = r.get("seasonal")
    cards = nearby_climb_cards(v) if ok else []
    rain = c.get("rain_pct")
    tag, tcls = wx_band(rain)
    grades = grade_range(cards)
    live = bool(fc and fc.get("in_window"))
    fl = r.get("flights") or {}

    def fallback_flight(who):
        cfg = v.get("travel", {}).get(who, {})
        m = cfg.get("mode")
        if m in ("local", "drive"):
            return {"mode": m}
        if m == "fly" and cfg.get("to"):
            return {"mode": "fly", "options": [], "to": cfg["to"],
                    "book_url": skyscanner_url(ORIGIN[who].split(",")[0], cfg["to"], REP["out"], REP["back"])}
        return {"mode": "unknown"}

    mf = fl.get("michel") or fallback_flight("michel")
    md = fl.get("dan") or fallback_flight("dan")

    # quick-facts strip (data-driven; capped at 5)
    facts = []
    if cards:
        tallest = max(cards, key=lambda x: x.get("length") or 0)
        if tallest.get("length"):
            facts.append({"lbl": "Max height", "val": f"{tallest['length']}m", "sub": tallest["cliff"]})

    def travel_fact(who, label, f):
        cfg = v.get("travel", {}).get(who, {})
        mode = cfg.get("mode")
        if mode == "local":
            return {"lbl": label, "val": "Local", "sub": "£0 transport"}
        if mode == "drive":
            return {"lbl": label, "val": "Drive", "sub": "self-drive"}
        opts = (f or {}).get("options") or []
        if opts:
            return {"lbl": label, "val": f"£{opts[0]['price']}", "sub": "return flight"}
        return {"lbl": label, "val": "Fly", "sub": f"to {cfg.get('to', '?')}"}

    facts.append(travel_fact("michel", "Travel · Michel", mf))
    facts.append(travel_fact("dan", "Travel · Dan", md))
    if cards:
        facts.append({"lbl": "Routes", "val": str(len(cards)), "sub": "on multi-pitch.com"})
    if grades:
        facts.append({"lbl": "Grades", "val": grades, "sub": "trad"})
    facts = facts[:5]

    # weather chart series: enrich climatology days with weekday labels
    series = []
    for s in (c.get("series") or []):
        try:
            wd = date(TARGET_START.year, TARGET_START.month, s["day"]).strftime("%a")
        except Exception:
            wd = str(s["day"])
        series.append({"day": s["day"], "lbl": wd, "tmax": s["tmax"],
                       "precip": s["precip"], "wind": s.get("wind", 0), "trip": s["trip"]})

    hotels, guide = mock_stays(v)
    return {
        "rank": n, "name": v["name"], "shortName": _short_name(v["name"]),
        "country": v["country"], "flag": flag(v["country"]), "rock": v.get("rock", ""),
        "style": v.get("style", ""), "why": v.get("why", ""), "basis": r.get("basis", ""),
        "score": r["score"] if ok else -1, "tag": tag, "tagCls": tcls, "arcColor": arc_color(tcls),
        "wx": {"tmax": c.get("tmax"), "rain": rain, "wind": c.get("wind"),
               "sky": (fc.get("sky") if live else ""), "live": live,
               "liveTemp": (fc.get("tmax") if live else None),
               "liveRain": (fc.get("rain_prob") if live else None)},
        "seasonal": ({"tmax": sea["tmax"], "rain": sea["rain_pct"], "members": sea["members"]}
                     if sea and not live else None),
        "series": series,
        "chartLabel": ("Live forecast — trip window" if live
                       else f"Typical late-July daily pattern (avg {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]})"),
        "grades": grades, "hero": (cards[0]["img"] if cards else None), "climbs": cards,
        "facts": facts,
        "flights": {"michel": mf, "dan": md},
        "hotels": hotels, "guide": guide,
        "maps": maps_url(v), "weather": weather_url(v), "mpMap": MP_MAP_URL,
    }


PAGE_HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>multi·pitch — Live Trip Hub · Michel &amp; Dan · ~24 Jul 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#0C0D10; --ink2:#12141B; --ink3:#191C27; --ink4:#20243A; --seam:#252840;
  --chalk:#EAE6DD; --chalk2:#9B9890; --chalk3:#5A5860;
  --go:#6CB268; --go-d:rgba(108,178,104,.14); --amb:#C8A44A; --amb-d:rgba(200,164,74,.13);
  --wet:#B94438; --wet-d:rgba(185,68,56,.13); --spike:#C4FF5C;
  --r:6px; --r-lg:12px; --left:256px; --right:288px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;background:var(--ink);color:var(--chalk)}
body{font-family:'Inter',sans-serif;font-size:13px;line-height:1.5;display:flex;flex-direction:column}
.top{height:48px;background:var(--ink2);border-bottom:1px solid var(--seam);display:flex;align-items:center;padding:0 16px;gap:12px;flex-shrink:0}
.logo{font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:var(--chalk);letter-spacing:-.2px;white-space:nowrap}
.logo b{color:var(--go);font-weight:800}
.divider-v{width:1px;height:20px;background:var(--seam)}
.ctx{display:flex;align-items:center;gap:5px;overflow:hidden}
.pill{display:flex;align-items:center;gap:5px;background:var(--ink3);border:1px solid var(--seam);border-radius:20px;padding:4px 11px;font-size:12px;font-weight:500;color:var(--chalk);white-space:nowrap}
.sep{color:var(--chalk3);font-size:11px}
.top-right{margin-left:auto;display:flex;gap:7px;flex-shrink:0}
.btn-g{background:transparent;border:1px solid var(--seam);border-radius:var(--r);padding:5px 12px;font-size:11px;font-weight:500;color:var(--chalk2);cursor:pointer;transition:all .15s;text-decoration:none;display:inline-flex;align-items:center;white-space:nowrap}
.btn-g:hover{border-color:var(--chalk3);color:var(--chalk)}
.btn-p{background:var(--go);border:none;border-radius:var(--r);padding:5px 14px;font-size:11px;font-weight:700;color:#0C0D10;cursor:pointer;transition:opacity .15s;text-decoration:none;display:inline-flex;align-items:center;white-space:nowrap}
.btn-p:hover{opacity:.85}
.databar{background:var(--ink3);border-bottom:1px solid var(--seam);padding:6px 16px;font-size:11.5px;color:var(--chalk2);display:flex;align-items:center;gap:14px;flex-shrink:0;line-height:1.4}
.databar .msg{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.databar b{color:var(--chalk);font-weight:600}
.databar.ok .msg b{color:#86e0a6}
.databar .upd{color:var(--chalk3);font-size:10px;white-space:nowrap;flex-shrink:0}
.ws{display:grid;grid-template-columns:var(--left) 1fr var(--right);flex:1;overflow:hidden;min-height:0}
.left{background:var(--ink2);border-right:1px solid var(--seam);display:flex;flex-direction:column;overflow:hidden}
.panel-hd{padding:11px 14px 8px;border-bottom:1px solid var(--seam);flex-shrink:0}
.panel-hd-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:5px}
.panel-title{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--chalk3)}
.panel-meta{font-size:10px;color:var(--chalk3)}
.legend{display:flex;gap:10px;font-size:9px;color:var(--chalk3)}
.legend span{display:flex;align-items:center;gap:3px}
.dot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.area-list{overflow-y:auto;flex:1;scrollbar-width:thin;scrollbar-color:var(--seam) transparent}
.a-row{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--seam);cursor:pointer;transition:background .12s;position:relative}
.a-row:hover{background:var(--ink3)}
.a-row.active{background:var(--ink4);border-left:2px solid var(--spike)}
.a-row.active .a-rank{color:var(--spike)}
.a-rank{font-family:'Syne',sans-serif;font-size:10px;font-weight:800;color:var(--chalk3);width:16px;flex-shrink:0}
.arc{position:relative;width:34px;height:34px;flex-shrink:0}
.arc svg{width:34px;height:34px}
.arc-n{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-family:'DM Mono',monospace;font-size:8.5px;font-weight:500;color:var(--chalk);line-height:1}
.a-body{flex:1;min-width:0}
.a-name{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:var(--chalk);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:1px}
.a-sub{font-size:10px;color:var(--chalk3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.a-wx{font-size:10px;color:var(--chalk2);margin-top:1px}
.a-tag{font-size:8px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 5px;border-radius:3px;flex-shrink:0;align-self:flex-start;margin-top:2px}
.tag-go{background:var(--go-d);color:var(--go)}
.tag-mix{background:var(--amb-d);color:var(--amb)}
.tag-wet{background:var(--wet-d);color:var(--wet)}
.centre{display:flex;flex-direction:column;overflow:hidden;background:var(--ink)}
.hero{position:relative;height:220px;flex-shrink:0;overflow:hidden}
.hero img{width:100%;height:100%;object-fit:cover;filter:brightness(.55) saturate(.8);display:block}
.hero-fb{width:100%;height:100%;background:linear-gradient(160deg,#2A3B28,#0C0D10);display:flex;align-items:center;justify-content:center;font-size:56px;opacity:.25}
.hero-grad{position:absolute;inset:0;background:linear-gradient(to bottom,rgba(12,13,16,0) 10%,rgba(12,13,16,.9) 80%,var(--ink) 100%)}
.hero-body{position:absolute;bottom:0;left:0;right:0;padding:14px 22px 18px;display:flex;align-items:flex-end;justify-content:space-between;gap:12px}
.hero-tag{display:flex;align-items:center;gap:7px;margin-bottom:6px;flex-wrap:wrap}
.hero-badge{background:var(--spike);color:var(--ink);font-size:9px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:3px}
.hero-region{font-size:11px;color:var(--chalk2)}
.hero-name{font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:var(--chalk);line-height:1.05;letter-spacing:-.4px;margin-bottom:5px}
.hero-info{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--chalk2);flex-wrap:wrap}
.hero-scores{display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex-shrink:0}
.score-box{background:rgba(12,13,16,.75);backdrop-filter:blur(10px);border:1px solid var(--seam);border-radius:var(--r-lg);padding:9px 13px;text-align:center}
.score-val{font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:var(--spike);line-height:1}
.score-lbl{font-size:8px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--chalk3);margin-top:2px}
.wx-pill{background:rgba(12,13,16,.75);backdrop-filter:blur(10px);border:1px solid var(--seam);border-radius:20px;padding:4px 10px;font-size:12px;font-weight:600;color:var(--chalk);display:flex;align-items:center;gap:5px;white-space:nowrap}
.c-body{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--seam) transparent}
.sec{padding:16px 22px;border-bottom:1px solid var(--seam)}
.sec:last-child{border-bottom:none}
.sec-lbl{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--chalk3);margin-bottom:10px}
.why-text{font-size:13px;line-height:1.7;color:var(--chalk2)}
.why-text strong{color:var(--chalk);font-weight:500}
.basis{font-size:10px;color:var(--chalk3);margin-top:9px;font-style:italic}
.facts{display:flex;gap:0;border:1px solid var(--seam);border-radius:var(--r-lg);overflow:hidden;margin-top:12px}
.fact{flex:1;padding:9px 11px;background:var(--ink3);border-right:1px solid var(--seam);min-width:0}
.fact:last-child{border-right:none}
.fact-lbl{font-size:8px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--chalk3);margin-bottom:3px}
.fact-val{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:var(--chalk);line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fact-sub{font-size:9px;color:var(--chalk3);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wx-chart{display:flex;gap:3px;align-items:flex-end;height:68px;margin-bottom:6px}
.wx-col{display:flex;flex-direction:column;align-items:center;flex:1}
.wx-bar-wrap{width:100%;display:flex;align-items:flex-end;height:44px;background:var(--ink4);border-radius:3px 3px 0 0;overflow:hidden;position:relative}
.wx-bar-rain{width:100%;background:rgba(90,140,200,.5);position:absolute;bottom:0}
.wx-bar-temp{width:4px;height:4px;border-radius:50%;background:var(--go);position:absolute;left:50%;transform:translateX(-50%)}
.wx-col-label{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--chalk3);margin-top:4px;text-align:center;width:100%}
.wx-col-temp{font-family:'DM Mono',monospace;font-size:9px;color:var(--chalk2);text-align:center}
.wx-col.trip .wx-bar-wrap{background:rgba(196,255,92,.08);border:1px solid rgba(196,255,92,.25)}
.wx-col.trip .wx-col-label{color:var(--spike)}
.wind-row{display:flex;gap:4px;margin-top:2px}
.wind-col{flex:1;text-align:center;font-size:9px;color:var(--chalk3);font-family:'DM Mono',monospace}
.wx-legend{display:flex;gap:14px;font-size:9px;color:var(--chalk3);margin-top:8px;flex-wrap:wrap}
.wx-legend span{display:flex;align-items:center;gap:4px}
.wx-swatch{width:10px;height:8px;border-radius:2px}
.outlook-line{font-size:11px;color:var(--chalk2);background:rgba(91,157,255,.08);border:1px solid rgba(91,157,255,.2);border-radius:6px;padding:5px 9px;margin:8px 0 2px}
.climb-card{display:flex;gap:11px;padding:10px 0;border-bottom:1px solid var(--seam);align-items:flex-start}
.climb-card:last-child{border-bottom:none}
.climb-thumb{width:64px;height:52px;border-radius:var(--r);overflow:hidden;flex-shrink:0;background:var(--ink3);border:1px solid var(--seam)}
.climb-thumb.ph{display:flex;align-items:center;justify-content:center;font-size:22px}
.climb-thumb img{width:100%;height:100%;object-fit:cover}
.climb-body{flex:1;min-width:0}
.climb-name{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:var(--chalk);margin-bottom:2px}
.climb-route{font-size:11px;color:var(--chalk2);margin-bottom:4px}
.climb-pills{display:flex;gap:5px;flex-wrap:wrap}
.cpill{font-size:9px;font-weight:600;padding:2px 6px;border-radius:3px;background:var(--ink4);color:var(--chalk3)}
.cpill-g{background:var(--go-d);color:var(--go)}
.climb-flags{display:flex;gap:4px;margin-top:4px;flex-wrap:wrap}
.flag-tag{font-size:9px;color:var(--amb);background:var(--amb-d);padding:1px 5px;border-radius:3px}
.climb-grade{font-family:'DM Mono',monospace;font-size:12px;font-weight:500;color:var(--go);flex-shrink:0;margin-top:2px}
.right{background:var(--ink2);border-left:1px solid var(--seam);display:flex;flex-direction:column;overflow:hidden}
.r-body{overflow-y:auto;flex:1;padding:12px;scrollbar-width:thin;scrollbar-color:var(--seam) transparent;display:flex;flex-direction:column;gap:14px}
.r-sec-lbl{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--chalk3);padding-bottom:6px;border-bottom:1px solid var(--seam);margin-bottom:8px;display:flex;align-items:center}
.mock-tag{font-size:8px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--chalk3);background:var(--ink4);padding:1px 5px;border-radius:3px;margin-left:6px}
.fc{background:var(--ink3);border:1px solid var(--seam);border-radius:var(--r-lg);overflow:hidden;margin-bottom:6px}
.fc:last-of-type{margin-bottom:0}
.fc-hd{padding:9px 12px 7px;border-bottom:1px solid var(--seam);display:flex;align-items:center;justify-content:space-between}
.fc-who{font-size:12px;font-weight:600;color:var(--chalk)}
.fc-from{font-size:10px;color:var(--chalk3);margin-top:1px}
.fc-best{font-size:8px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--spike);background:rgba(196,255,92,.1);padding:2px 6px;border-radius:3px}
.fc-bd{padding:9px 12px}
.fc-price{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:var(--chalk);display:flex;align-items:baseline;gap:4px;margin-bottom:7px}
.fc-price span{font-family:'Inter',sans-serif;font-size:10px;font-weight:400;color:var(--chalk3)}
.fc-opt{display:flex;justify-content:space-between;gap:8px;font-size:11px;padding:3px 0;border-bottom:1px solid var(--seam);color:var(--chalk2)}
.fc-opt:last-of-type{border-bottom:none}
.fc-opt span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag-d{color:var(--go);font-size:10px;font-weight:600;flex-shrink:0}
.tag-s{color:var(--chalk3);font-size:10px;flex-shrink:0}
.fc-btn{width:100%;margin-top:9px;background:var(--chalk);color:var(--ink);border:none;border-radius:var(--r);padding:7px;font-size:11px;font-weight:700;font-family:'Inter',sans-serif;cursor:pointer;transition:background .15s;text-decoration:none;display:block;text-align:center}
.fc-btn:hover{background:var(--go)}
.fc-btn.sec{background:transparent;border:1px solid var(--seam);color:var(--chalk2);font-weight:500;margin-top:4px}
.fc-btn.sec:hover{background:var(--ink4);color:var(--chalk);border-color:var(--chalk3)}
.hc{background:var(--ink3);border:1px solid var(--seam);border-radius:var(--r-lg);padding:10px 12px;margin-bottom:6px}
.hc:last-child{margin-bottom:0}
.hc-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:1px}
.hc-name{font-size:12px;font-weight:600;color:var(--chalk)}
.hc-stars{font-size:10px;color:var(--amb);white-space:nowrap;flex-shrink:0}
.hc-type{font-size:10px;color:var(--chalk3);margin-bottom:5px}
.hc-price{font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:var(--chalk);margin-bottom:5px}
.hc-price span{font-family:'Inter',sans-serif;font-size:10px;font-weight:400;color:var(--chalk3)}
.hc-tags{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:7px}
.hc-tag{font-size:9px;font-weight:500;padding:2px 5px;border-radius:3px;background:var(--ink4);color:var(--chalk3)}
.hc-tag.g{background:var(--go-d);color:var(--go)}
.empty{font-size:12px;color:var(--chalk3);padding:6px 0}
.flink{color:var(--go);text-decoration:none;font-weight:600}
.flink:hover{text-decoration:underline}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--seam);border-radius:2px}
@media(max-width:900px){
  html,body{overflow:auto}
  .ws{display:block}
  .left,.right{border-right:none;border-left:none;border-bottom:1px solid var(--seam)}
  .area-list{max-height:420px}
  .centre{min-height:auto}
  .hero{height:200px}
}
</style></head>"""

PAGE_BODY = """<body>
<header class="top">
  <div class="logo">multi<b>·</b>pitch</div>
  <div class="divider-v"></div>
  <div class="ctx" id="ctx"></div>
  <div class="top-right">
    <a class="btn-g" id="mapBtn" target="_blank" rel="noopener">\U0001f5fa Map</a>
    <a class="btn-g" id="sheetBtn" target="_blank" rel="noopener">\U0001f4cb Spreadsheet</a>
    <a class="btn-p" id="mpBtn" target="_blank" rel="noopener">multi-pitch.com ↗</a>
  </div>
</header>
<div class="databar" id="databar"></div>
<div class="ws">
  <aside class="left">
    <div class="panel-hd">
      <div class="panel-hd-row"><span class="panel-title">Areas ranked for your trip</span><span class="panel-meta" id="areaCount"></span></div>
      <div class="legend">
        <span><div class="dot" style="background:var(--go)"></div>Dry</span>
        <span><div class="dot" style="background:var(--amb)"></div>Mixed</span>
        <span><div class="dot" style="background:var(--wet)"></div>Wet</span>
        <span style="margin-left:auto;font-size:9px;color:var(--chalk3)">Score = weather</span>
      </div>
    </div>
    <div class="area-list" id="areaList"></div>
  </aside>
  <main class="centre" id="centre"></main>
  <aside class="right" id="right"></aside>
</div>
"""

PAGE_JS = """
var D=window.DATA,V=D.venues;
function esc(s){return s==null?'':String(s);}
document.getElementById('ctx').innerHTML=D.trip.pills.map(function(p){return '<div class="pill">'+p+'</div>';}).join('<span class="sep">·</span>');
document.getElementById('mapBtn').href=D.trip.mapUrl;
document.getElementById('sheetBtn').href=D.trip.sheetUrl;
document.getElementById('mpBtn').href=D.trip.mpUrl;
document.getElementById('areaCount').textContent=V.length+' areas';
var db=document.getElementById('databar');db.className='databar '+(D.banner.cls==='ok'?'ok':'');
db.innerHTML='<span class="msg">'+D.banner.html+'</span><span class="upd">updated '+D.trip.updated+'</span>';

function heroFail(img){img.style.display='none';var fb=img.nextElementSibling;if(fb)fb.style.display='flex';}
function thumbFail(img){var p=img.parentElement;p.classList.add('ph');p.textContent='\U0001f3d4';}

function arcSvg(score,color){
  var C=81.7,off=(C*(1-Math.max(0,score)/100)).toFixed(1);
  return '<svg viewBox="0 0 34 34" fill="none"><circle cx="17" cy="17" r="13" stroke="#252840" stroke-width="2.5"/>'
    +'<circle cx="17" cy="17" r="13" stroke="'+color+'" stroke-width="2.5" stroke-dasharray="'+C+'" stroke-dashoffset="'+off+'" stroke-linecap="round" transform="rotate(-90 17 17)"/></svg>'
    +'<div class="arc-n">'+(score>=0?score:'–')+'</div>';
}
function areaRow(v,i){
  var wx=v.wx.tmax!=null?(v.wx.tmax+'°C · '+v.wx.rain+'% wet · \U0001f4a8'+v.wx.wind+'km/h'):'no weather data';
  return '<div class="a-row" data-i="'+i+'" onclick="sel('+i+')">'
    +'<div class="a-rank">'+v.rank+'</div>'
    +'<div class="arc">'+arcSvg(v.score,v.arcColor)+'</div>'
    +'<div class="a-body"><div class="a-name">'+v.flag+' '+esc(v.shortName)+'</div>'
    +'<div class="a-sub">'+esc(v.country)+(v.rock?' · '+v.rock:'')+'</div>'
    +'<div class="a-wx">'+wx+'</div></div>'
    +'<div class="a-tag tag-'+v.tagCls+'">'+v.tag+'</div></div>';
}
document.getElementById('areaList').innerHTML=V.map(areaRow).join('');

function climbCard(c){
  var inner=c.img?'<img src="'+c.img+'" alt="" onerror="thumbFail(this)">':'\U0001f3d4';
  var pills=[];
  if(c.grade)pills.push('<span class="cpill cpill-g">'+esc(c.grade)+'</span>');
  if(c.approach!=null)pills.push('<span class="cpill">'+c.approach+' min approach</span>');
  if(c.dist!=null)pills.push('<span class="cpill">'+c.dist+' km away</span>');
  var flags=(c.flags||[]).map(function(f){return '<span class="flag-tag">⚠ '+f+'</span>';}).join('');
  var meta=[c.pitches?c.pitches+' pitches':null,c.length?c.length+'m':null].filter(Boolean).join(' · ');
  return '<div class="climb-card"><div class="climb-thumb'+(c.img?'':' ph')+'">'+inner+'</div>'
    +'<div class="climb-body"><div class="climb-name">'+esc(c.cliff)+'</div>'
    +'<div class="climb-route">'+esc(c.route)+(meta?' — '+meta:'')+'</div>'
    +'<div class="climb-pills">'+pills.join('')+'</div>'+(flags?'<div class="climb-flags">'+flags+'</div>':'')+'</div>'
    +'<div class="climb-grade">'+esc(c.tradGrade)+'</div></div>';
}

function buildChart(series){
  var chart=document.getElementById('wxChart'),windRow=document.getElementById('windRow');
  if(!chart)return;chart.innerHTML='';windRow.innerHTML='';
  if(!series||!series.length){chart.innerHTML='<div class="empty">No daily series available.</div>';return;}
  var maxRain=Math.max.apply(null,series.map(function(d){return d.precip;}).concat([1]));
  var maxT=Math.max.apply(null,series.map(function(d){return d.tmax;}));
  var minT=Math.min.apply(null,series.map(function(d){return d.tmax;}));
  series.forEach(function(d){
    var rainH=Math.round((d.precip/maxRain)*36)+2;
    var pct=maxT===minT?0.5:(d.tmax-minT)/(maxT-minT);
    var tempTop=Math.round((1-pct)*32)+4;
    var col=document.createElement('div');col.className='wx-col'+(d.trip?' trip':'');
    col.innerHTML='<div class="wx-bar-wrap"><div class="wx-bar-rain" style="height:'+rainH+'px"></div><div class="wx-bar-temp" style="bottom:'+tempTop+'px"></div></div><div class="wx-col-label">'+d.lbl+'</div><div class="wx-col-temp">'+d.tmax+'°</div>';
    chart.appendChild(col);
    var wc=document.createElement('div');wc.className='wind-col';wc.style.color=d.trip?'rgba(196,255,92,.6)':'var(--chalk3)';wc.textContent='\U0001f4a8'+d.wind;windRow.appendChild(wc);
  });
}

function renderCentre(v){
  var hero=v.hero
    ?'<img src="'+v.hero+'" alt="" onerror="heroFail(this)"><div class="hero-fb" style="display:none">\U0001f3d4</div>'
    :'<div class="hero-fb" style="display:flex">\U0001f3d4</div>';
  var info=[v.style,v.climbs.length?(v.climbs.length+' routes on multi-pitch.com'):null,v.grades?('Grades '+v.grades):null].filter(Boolean).join(' · ');
  var facts=v.facts.map(function(f){return '<div class="fact"><div class="fact-lbl">'+f.lbl+'</div><div class="fact-val">'+f.val+'</div><div class="fact-sub">'+esc(f.sub)+'</div></div>';}).join('');
  var climbs=v.climbs.length?v.climbs.map(climbCard).join(''):'<div class="empty">No multi-pitch.com routes indexed near here yet — <a class="flink" href="'+v.mpMap+'" target="_blank" rel="noopener">browse the map ↗</a></div>';
  var wxpill='<div class="wx-pill">'+(v.wx.sky||'☁')+' '+(v.wx.tmax!=null?v.wx.tmax+'°C':'—')+' · '+v.tag.toLowerCase()+'</div>';
  var legend='<div class="wx-legend"><span><div class="wx-swatch" style="background:rgba(90,140,200,.5)"></div>Rain (mm)</span><span><div class="wx-swatch" style="background:var(--go);border-radius:50%;width:8px;height:8px"></div>Temp °C</span><span><div class="wx-swatch" style="background:rgba(196,255,92,.25);border:1px solid rgba(196,255,92,.4)"></div>Trip days</span></div>';
  var outlook=v.seasonal?'<div class="outlook-line">\U0001f52d <b>45-day outlook:</b> '+v.seasonal.tmax+'°C · '+v.seasonal.rain+'% wet days <span style="color:var(--chalk3)">(experimental '+v.seasonal.members+'-member ensemble)</span></div>':'';
  document.getElementById('centre').innerHTML=
    '<div class="hero">'+hero+'<div class="hero-grad"></div><div class="hero-body"><div class="hero-left">'
    +'<div class="hero-tag"><span class="hero-badge">#'+v.rank+' this trip</span><span class="hero-region">'+esc(v.country)+'</span></div>'
    +'<div class="hero-name">'+esc(v.shortName)+'</div><div class="hero-info">'+info+'</div></div>'
    +'<div class="hero-scores"><div class="score-box"><div class="score-val">'+(v.score>=0?v.score:'–')+'</div><div class="score-lbl">Trip score</div></div>'+wxpill+'</div></div></div>'
    +'<div class="c-body">'
    +'<div class="sec"><div class="sec-lbl">Why go here</div><div class="why-text">'+esc(v.why)+'</div>'+(facts?'<div class="facts">'+facts+'</div>':'')+(v.basis?'<div class="basis">Ranking basis: '+esc(v.basis)+'</div>':'')+'</div>'
    +'<div class="sec"><div class="sec-lbl">'+esc(v.chartLabel)+'</div><div class="wx-chart" id="wxChart"></div><div class="wind-row" id="windRow"></div>'+outlook+legend+'</div>'
    +'<div class="sec"><div class="sec-lbl">Climbs in this area — from multi-pitch.com</div>'+climbs+'</div>'
    +'</div>';
  buildChart(v.series);
}

function flightCard(who,f,from){
  var head='<div class="fc-hd"><div><div class="fc-who">'+who+'</div><div class="fc-from">'+from+'</div></div>';
  if(!f||f.mode==='local')return '<div class="fc">'+head+'</div><div class="fc-bd" style="padding:10px 12px"><div style="font-size:13px;font-weight:600;color:var(--go);margin-bottom:4px">\U0001f697 Local — no flight needed</div><div style="font-size:11px;color:var(--chalk3)">Lives near the crags.</div></div></div>';
  if(f.mode==='drive')return '<div class="fc">'+head+'</div><div class="fc-bd" style="padding:10px 12px"><div style="font-size:13px;font-weight:600;color:var(--go);margin-bottom:4px">\U0001f697 Drive / train</div><div style="font-size:11px;color:var(--chalk3)">Drivable — no flight priced.</div></div></div>';
  var opts=f.options||[];var view=f.view_url||f.book_url;var book=f.book_url||f.view_url;
  var best=opts.length?'<div class="fc-best">Best value</div>':'';
  var body;
  if(!opts.length){
    body='<div class="fc-bd"><div style="font-size:11px;color:var(--chalk3);margin-bottom:7px">to '+esc(f.to)+' — no live price</div>'+(view?'<a class="fc-btn" href="'+view+'" target="_blank" rel="noopener">Search flights ↗</a>':'')+'</div>';
  }else{
    var rows=opts.map(function(o,i){var st=o.stops===0?'Direct':o.stops+'-stop';var lead=i===0?'':'£'+o.price+' ';return '<div class="fc-opt"><span>'+lead+o.dep+'→'+o.arr+' · '+o.from+' · '+esc(o.airline).slice(0,10)+'</span><span class="'+(o.stops===0?'tag-d':'tag-s')+'">'+st+'</span></div>';}).join('');
    body='<div class="fc-bd"><div class="fc-price">£'+opts[0].price+' <span>return pp</span></div>'+rows+'<a class="fc-btn" href="'+book+'" target="_blank" rel="noopener">Book flight ↗</a>'+(f.view_url?'<a class="fc-btn sec" href="'+f.view_url+'" target="_blank" rel="noopener">See all options</a>':'')+'</div>';
  }
  return '<div class="fc">'+head+best+'</div>'+body+'</div>';
}

function hotelCard(h){
  return '<div class="hc"><div class="hc-hd"><div class="hc-name">'+esc(h.name)+'</div><div class="hc-stars">'+Array(h.stars+1).join('★')+'</div></div>'
    +'<div class="hc-type">'+esc(h.type)+'</div><div class="hc-price">'+h.price+' <span>/ room / night</span></div>'
    +'<div class="hc-tags">'+h.tags.map(function(t,i){return '<div class="hc-tag'+(i===0?' g':'')+'">'+t+'</div>';}).join('')+'</div>'
    +'<a class="fc-btn" href="'+h.book+'" target="_blank" rel="noopener">Search on Booking.com ↗</a></div>';
}

function guideCard(g){
  return '<div class="hc" style="display:flex;gap:11px;align-items:center"><div style="font-size:22px">\U0001f4d7</div><div>'
    +'<div style="font-size:12px;font-weight:600;color:var(--chalk)">'+esc(g.title)+'</div>'
    +'<div style="font-size:10px;color:var(--chalk3)">'+esc(g.pub)+'</div>'
    +'<div style="font-size:10px;margin-top:2px"><a href="'+g.url+'" target="_blank" rel="noopener" class="flink">'+g.price+' → Amazon ↗</a></div></div></div>';
}

function renderRight(v){
  var hotels=v.hotels&&v.hotels.length?v.hotels.map(hotelCard).join(''):'<div class="empty">No sample stays for this area.</div>';
  var guide=v.guide?'<div><div class="r-sec-lbl">Guidebook <span class="mock-tag">sample</span></div>'+guideCard(v.guide)+'</div>':'';
  document.getElementById('right').innerHTML=
    '<div class="panel-hd"><div class="panel-hd-row"><span class="panel-title">Plan this trip</span><span class="panel-meta">'+esc(v.shortName)+'</span></div></div>'
    +'<div class="r-body">'
    +'<div><div class="r-sec-lbl">Flights · '+D.trip.dates+'</div>'+flightCard('Michel',v.flights.michel,'from London')+flightCard('Dan',v.flights.dan,'from Belfast / Dublin')+'</div>'
    +'<div><div class="r-sec-lbl">Accommodation near crags <span class="mock-tag">sample</span></div>'+hotels+'</div>'
    +guide
    +'</div>';
}

function sel(i){
  var rows=document.querySelectorAll('.a-row');
  for(var k=0;k<rows.length;k++)rows[k].classList.toggle('active',+rows[k].dataset.i===i);
  renderCentre(V[i]);renderRight(V[i]);
}
sel(0);
"""


def build_html(ranked, now, banner):
    """Dark 3-panel 'Live Hub' dashboard: left = venues ranked, centre = area detail
    (hero + weather + multi-pitch.com climbs), right = flights (live) + stays (sample).
    All per-venue data is embedded as JSON and rendered client-side so one static
    file (GitHub Pages) supports switching between areas."""
    payload = [venue_payload(n, r) for n, r in enumerate(ranked, 1)]
    trip = {
        "pills": ["✈ Michel · London", "✈ Dan · Belfast / Dublin",
                  f"📅 {REP_OUT_LBL} – {REP_BACK_LBL}",
                  f"🧗 {len(payload)} areas ranked"],
        "dates": f"{REP_OUT_LBL} → {REP_BACK_LBL}",
        "mapUrl": MP_MAP_URL, "sheetUrl": SHEET_URL, "mpUrl": SITE_URL,
        "updated": now.strftime("%a %d %b %Y, %H:%M UTC"),
    }
    data = {"venues": payload, "trip": trip,
            "banner": {"cls": (banner[0] or "info"), "html": banner[1]}}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (PAGE_HEAD
            + "\n<script>window.DATA=" + blob + ";</script>\n"
            + PAGE_BODY
            + "<script>" + PAGE_JS + "</script>\n</body></html>\n")


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

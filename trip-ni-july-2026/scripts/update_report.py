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
import sys
import time
import unicodedata
import urllib.error
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


def _md_range(start, end):
    """Set of (month, day) tuples covered by [start, end] inclusive — so the trip/graph
    window logic keeps working when the window straddles a month boundary (e.g. 30 Jul–3 Aug)."""
    out, d = set(), start
    while d <= end:
        out.add((d.month, d.day))
        d += timedelta(days=1)
    return out


GRAPH_MD = _md_range(GRAPH_START, GRAPH_END)   # graph window as (month, day) keys
TRIP_MD = _md_range(TARGET_START, TARGET_END)  # trip window as (month, day) keys
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
    except Exception as e:
        print(f"[warn] could not read {CLIMBING_CSV.name}: {e}", file=sys.stderr)
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

# multi-pitch.com's own weather icon set (Climacons) — used on the dashboard.
MP_ICONS = SITE_URL + "img/icons/weather/"


def wmo_icon(code):
    """WMO weather code -> multi-pitch.com icon URL (day variants)."""
    if code is None:
        return None
    name = ("clear-day" if code == 0 else
            "partly-cloudy-day" if code in (1, 2) else
            "cloudy" if code == 3 else
            "fog" if code in (45, 48) else
            "Cloud-Drizzle" if code in (51, 53, 55) else
            "rain" if code in (61, 63, 65) else
            "snow" if code in (71, 73, 75) else
            "Cloud-Rain-Sun" if code in (80, 81) else
            "Cloud-Lightning" if code in (82, 95, 96, 99) else "cloudy")
    return MP_ICONS + name + ".svg"

FLAGS = {
    "Northern Ireland": "🇬🇧", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Italy": "🇮🇹", "Austria": "🇦🇹", "Spain": "🇪🇸", "Croatia": "🇭🇷", "France": "🇫🇷", "Ireland": "🇮🇪",
    "Norway": "🇳🇴",
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


def _redact(s):
    """Strip the SerpApi key out of any string before it reaches a log or exception —
    the key rides in the query string, so raw urllib error text would otherwise leak it."""
    s = str(s)
    return s.replace(SERPAPI_KEY, "***") if SERPAPI_KEY else s


def _get(url, retries=4):
    """GET JSON with retries — APIs rate-limit bursts; never silently lose a sample.
    Client errors (4xx: bad key/params) are NOT retried — retrying can't fix them and
    just burns ~15s × venues. Errors are re-raised with the key redacted."""
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if 400 <= e.code < 500:
                break
        except Exception as e:
            last = e
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {_redact(url)} failed: {_redact(last)}")


# ---- Weather --------------------------------------------------------------
def forecast(lat, lon):
    return _get(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,windspeed_10m_max,"
        "winddirection_10m_dominant"
        "&timezone=auto&forecast_days=16"
    )["daily"]


def climatology(lat, lon):
    """Typical trip-window conditions over recent years — ONE ranged request, filtered.
    Days are matched by real (month, day) against the graph/trip windows, so this stays
    correct even when the trip straddles a month boundary (e.g. 30 Jul–3 Aug)."""
    d = _get(
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={CLIMO_YEARS[0]}-{GRAPH_START:%m-%d}&end_date={CLIMO_YEARS[-1]}-{GRAPH_END:%m-%d}"
        "&daily=temperature_2m_max,precipitation_sum,windspeed_10m_max&timezone=auto"
    )["daily"]
    tmaxs, winds, rain_days, total = [], [], 0, 0
    per_day = {}   # (month, day) -> {"t","p","w"} lists for the graph window
    for t, tx, pr, wd in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"],
                             d.get("windspeed_10m_max", [None] * len(d["time"]))):
        dd = date.fromisoformat(t)
        md = (dd.month, dd.day)
        if tx is None:
            continue
        if md in GRAPH_MD:                       # graph window (trip ±2)
            e = per_day.setdefault(md, {"t": [], "p": [], "w": []})
            e["t"].append(tx)
            e["p"].append(pr or 0)
            e["w"].append(wd or 0)
        if md in TRIP_MD:                        # trip window aggregate
            total += 1
            tmaxs.append(tx)
            winds.append(wd or 0)
            if (pr or 0) >= 3:
                rain_days += 1
    if not total:
        return None
    series, day = [], GRAPH_START
    while day <= GRAPH_END:
        md = (day.month, day.day)
        pd = per_day.get(md)
        if pd:
            series.append({"day": day.day, "month": day.month,
                           "tmax": round(sum(pd["t"]) / len(pd["t"])),
                           "precip": round(sum(pd["p"]) / len(pd["p"]), 1),
                           "wind": round(sum(pd["w"]) / len(pd["w"])),
                           "trip": md in TRIP_MD})
        day += timedelta(days=1)
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
    daily = {}   # (month, day) -> ensemble-mean {tmax, precip} for the graph window
    for i, day in enumerate(times):
        dd = date.fromisoformat(day)
        gvals = [d[k][i] for k in tkeys if i < len(d[k]) and d[k][i] is not None]
        gp = [d[k][i] for k in pkeys if i < len(d[k]) and d[k][i] is not None]
        if gvals and (dd.month, dd.day) in GRAPH_MD:
            daily[(dd.month, dd.day)] = {
                "tmax": round(sum(gvals) / len(gvals)),
                "precip": round(sum(gp) / len(gp) if gp else 0, 1)}
        if not (TARGET_START <= dd <= TARGET_END):
            continue
        tvals = gvals
        pvals = gp
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
            "precip": round(sum(precs) / len(precs), 1), "members": max(1, len(tkeys)),
            "daily": daily}


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
    except Exception as e:
        print(f"[warn] climatology failed for {v['name']}: {_redact(e)}", file=sys.stderr)
        res["climo"] = None
    try:
        res["seasonal"] = seasonal(v["lat"], v["lon"])
    except Exception as e:
        print(f"[warn] seasonal failed for {v['name']}: {_redact(e)}", file=sys.stderr)
        res["seasonal"] = None
    try:
        d = forecast(v["lat"], v["lon"])
        days = d["time"]
        valid = [i for i in range(len(days)) if d["temperature_2m_max"][i] is not None]
        in_win = [i for i in valid if TARGET_START <= date.fromisoformat(days[i]) <= TARGET_END]
        winds = d.get("windspeed_10m_max") or [None] * len(days)
        dirs = d.get("winddirection_10m_dominant") or [None] * len(days)
        # per-day live forecast for graph-window days (overlaid on the typical chart)
        res["fc_days"] = {}
        for i in valid:
            dd = date.fromisoformat(days[i])
            if (dd.month, dd.day) in GRAPH_MD:
                res["fc_days"][(dd.month, dd.day)] = {
                    "tmax": round(d["temperature_2m_max"][i]),
                    "precip": round(d["precipitation_sum"][i] or 0, 1),
                    "icon": wmo_icon(d["weathercode"][i]),
                    "wind": round(winds[i]) if winds[i] is not None else None,
                    "dir": round(dirs[i]) if dirs[i] is not None else None,
                }
        if in_win:
            scores = [day_score(d["weathercode"][i], d["precipitation_sum"][i],
                                d["precipitation_probability_max"][i]) for i in in_win]
            codes = [d["weathercode"][i] for i in in_win]
            dom = max(set(codes), key=codes.count)
            res["fc"] = {
                "score": round(sum(scores) / len(scores)),
                "tmax": round(sum(d["temperature_2m_max"][i] for i in in_win) / len(in_win)),
                "rain_prob": max((d["precipitation_probability_max"][i] or 0) for i in in_win),
                "sky": WMO.get(dom, "?"), "sky_icon": wmo_icon(dom),
                "in_window": True, "horizon": days[-1],
            }
        else:
            res["fc"] = {"in_window": False, "horizon": days[-1] if days else "?"}
    except Exception as e:
        print(f"[warn] forecast failed for {v['name']}: {_redact(e)}", file=sys.stderr)
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
    ok_ids = {id(r) for r in ok}   # identity, not dict equality
    return ok + [r for r in results if id(r) not in ok_ids]


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
        except Exception as e:
            print(f"[warn] flight lookup failed ({who} -> {t.get('to')}): {_redact(e)}", file=sys.stderr)
    # no key / no result / error: still offer a search link so it's actionable
    if mode == "fly":
        return {"mode": "fly", "options": [], "to": t.get("to"),
                "book_url": skyscanner_url(ORIGIN[who].split(",")[0], t["to"], REP["out"], REP["back"])}
    return {"mode": "unknown"}


def attach_flights(ranked):
    """Price flights for the top-N venues (both travellers); cache to flights-latest.json.
    A run with no live price (no SerpApi key, or a failed/empty lookup) reuses the last
    good prices from the previous run's cache instead of falling back to bare links."""
    prev = FLIGHTS_DATA.get("venues") or {}   # last run's prices (loaded from disk at import)
    cache = {}
    for r in ranked[:TOP_N_FLIGHTS]:
        if not r.get("ok") or r["score"] < 0:
            continue
        v = r["venue"]
        flights = {}
        for w in ("michel", "dan"):
            f = traveller_flight(v, w)
            if not f.get("options"):
                cached = (prev.get(v["name"]) or {}).get(w)
                if cached and cached.get("options"):
                    f = dict(cached, cached=True)   # reuse last-known prices
            flights[w] = f
        r["flights"] = flights
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

    # quick-facts strip (travel lives in "Getting there" — not duplicated here)
    facts = []
    if v.get("rock"):
        facts.append({"lbl": "Rock", "val": v["rock"].split("/")[0].capitalize(), "sub": v.get("rock", "")})
    if cards:
        tallest = max(cards, key=lambda x: x.get("length") or 0)
        if tallest.get("length"):
            facts.append({"lbl": "Max height", "val": f"{tallest['length']}m", "sub": tallest["cliff"]})
        facts.append({"lbl": "Routes", "val": str(len(cards)), "sub": "on multi-pitch.com"})
    if grades:
        facts.append({"lbl": "Grades", "val": grades, "sub": "trad"})
    if rain is not None:
        facts.append({"lbl": "Wet days", "val": f"{rain}%", "sub": "typical late July"})
    facts = facts[:5]

    # weather chart series: typical (climatology) days enriched with weekday labels,
    # plus per-day overlays — live forecast ("fc") when it reaches the window,
    # otherwise the 45-day ensemble outlook ("out").
    fcd = r.get("fc_days") or {}
    sead = (sea or {}).get("daily") or {}
    series = []
    for s in (c.get("series") or []):
        m = s.get("month", TARGET_START.month)
        try:
            wd = date(TARGET_START.year, m, s["day"]).strftime("%a")
        except Exception:
            wd = str(s["day"])
        entry = {"day": s["day"], "lbl": wd, "tmax": s["tmax"],
                 "precip": s["precip"], "wind": s.get("wind", 0), "trip": s["trip"]}
        md_key = (m, s["day"])
        if md_key in fcd:
            entry["fc"] = fcd[md_key]
        elif md_key in sead:
            entry["out"] = sead[md_key]
        series.append(entry)

    hotels, guide = mock_stays(v)
    return {
        "rank": n, "name": v["name"], "shortName": _short_name(v["name"]),
        "country": v["country"], "flag": flag(v["country"]), "rock": v.get("rock", ""),
        "style": v.get("style", ""), "why": v.get("why", ""), "basis": r.get("basis", ""),
        "score": r["score"] if ok else -1, "tag": tag, "tagCls": tcls, "arcColor": arc_color(tcls),
        "wx": {"tmax": c.get("tmax"), "rain": rain, "wind": c.get("wind"),
               "sky": (fc.get("sky") if live else ""), "live": live,
               "skyIcon": (fc.get("sky_icon") if live else None),
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
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src https: data:">
<title>multi·pitch — Trip planner · Michel &amp; Dan · ~24 Jul 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#14161A; --panel:#191C21; --card:#20242B; --ink:#E9E7E1; --muted:#A0A19A; --faint:#6E7069;
  --line:#2A2E36; --line2:#353A44;
  --dry:#57A664; --dry-bg:rgba(87,166,100,.10); --mixed:#B98A2E; --mixed-bg:rgba(185,138,46,.10); --wet:#D06A57; --wet-bg:rgba(208,106,87,.10);
  --rain:#3987e5; --temp:#d95926;
  --disp:'Bricolage Grotesque',sans-serif; --body:'IBM Plex Sans',sans-serif; --mono:'IBM Plex Mono',monospace;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.55}
.top{display:flex;align-items:center;flex-wrap:wrap;gap:10px 18px;padding:13px 22px;border-bottom:1px solid var(--line2);background:var(--panel)}
.mplogo{width:22px;height:22px;object-fit:contain;margin-right:8px;vertical-align:-5px}
.wordmark{font-family:var(--disp);font-weight:800;font-size:19px;letter-spacing:-.02em;white-space:nowrap;display:flex;align-items:center}
.wordmark em{font-style:normal;font-weight:500;font-size:10px;font-family:var(--mono);color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-left:8px}
.trip-line{font-size:12.5px;color:var(--muted)}
.top-links{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.tl{font-size:12px;font-weight:500;text-decoration:none;color:var(--ink);border:1px solid var(--line2);border-radius:7px;padding:5px 11px;background:var(--card);white-space:nowrap}
.tl:hover{border-color:var(--muted)}
.tl.strong{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.tl.strong:hover{opacity:.88}
.basis{padding:9px 22px;font-size:12.5px;color:var(--muted);background:var(--panel);border-bottom:1px solid var(--line)}
.basis b{color:var(--ink)}
.layout{display:grid;grid-template-columns:minmax(300px,370px) minmax(0,1fr);align-items:start}
.board{border-right:1px solid var(--line2);position:sticky;top:0;max-height:100vh;overflow-y:auto;background:var(--panel);scrollbar-width:thin;scrollbar-color:var(--line2) transparent}
.board-hd{padding:16px 18px 10px}
.eyebrow{font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.board-sub{font-size:11.5px;color:var(--faint);margin-top:3px}
.row{display:grid;grid-template-columns:30px minmax(0,1fr);column-gap:12px;width:100%;text-align:left;border:0;border-top:1px solid var(--line);background:none;padding:13px 18px;cursor:pointer;font:inherit;color:inherit}
.row:hover{background:#1F232B}
.row.active{background:var(--card);box-shadow:inset 3px 0 0 var(--ink)}
.rnum{grid-row:1/4;font-family:var(--disp);font-weight:800;font-size:21px;line-height:1.1;color:var(--ink);opacity:.3}
.row.active .rnum{opacity:1}
.rname{font-family:var(--disp);font-weight:700;font-size:15.5px;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rsub{font-size:11.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rbar-line{display:flex;align-items:center;gap:8px;margin-top:6px}
.rbar-track{flex:1;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.rbar{height:100%;border-radius:3px}
.rsc{font-family:var(--mono);font-size:12px;font-weight:600;min-width:20px;text-align:right}
.rsc.dim{color:var(--faint);font-weight:400}
.board-ft{padding:12px 18px;font-size:10.5px;color:var(--faint);border-top:1px solid var(--line);line-height:1.5}
.detail{background:var(--bg);min-height:100vh}
.band{position:relative;overflow:hidden;padding:30px 30px 26px;border-bottom:1px solid var(--line2);min-height:214px;display:flex;align-items:flex-end}
.band svg.topo{position:absolute;top:50%;right:-30px;transform:translateY(-50%);height:135%;pointer-events:none}
.band-body{position:relative;max-width:60%}
.vname{font-family:var(--disp);font-weight:800;font-size:clamp(26px,4.5vw,40px);letter-spacing:-.02em;line-height:1.05;margin:6px 0 5px}
.vmeta{font-size:13px;color:var(--muted)}
.vpills{display:flex;gap:7px;margin-top:13px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:6px;background:var(--card);border:1px solid var(--line2);border-radius:16px;padding:4px 11px;font-size:11.5px;font-weight:600}
.pill .dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.pill .wxi{width:16px;height:16px}
.sec{padding:22px 30px;border-bottom:1px solid var(--line)}
.sec:last-child{border-bottom:0}
.sec>.eyebrow{margin-bottom:14px}
.sec-hd{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.sec-hd .eyebrow{margin-bottom:0}
.lk{color:var(--ink);font-weight:600}
.lk.sm{font-size:11.5px;font-weight:500;color:var(--muted);text-decoration:underline;text-underline-offset:3px}
.lk.sm:hover{color:var(--ink)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:9px 13px;min-width:96px}
.chip-l{font-family:var(--mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.chip-v{font-family:var(--disp);font-weight:700;font-size:16px;margin-top:2px;white-space:nowrap}
.chip-s{font-size:10.5px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px}
.spot{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);max-width:860px}
.spot img{width:100%;height:330px;object-fit:cover;display:block}
.spot figcaption{padding:12px 16px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:baseline}
.spot-name{font-family:var(--disp);font-weight:700;font-size:16px}
.spot-meta{font-family:var(--mono);font-size:11px;color:var(--muted)}
.why{max-width:760px;font-size:14px;line-height:1.75;color:#CDCCC4}
.score-note{font-size:12.5px;color:var(--muted);margin-top:10px;max-width:760px;line-height:1.6}
.score-note b{color:var(--ink)}
.wx-take{font-size:14px;margin-bottom:16px;max-width:760px}
.wx-take b{font-weight:600}
.wxgrid{display:grid;grid-template-columns:70px minmax(0,1fr);row-gap:2px;max-width:880px}
.wxlbl{font-family:var(--mono);font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);display:flex;align-items:flex-end;padding:0 8px 6px 0}
.wxlbl .sw{width:8px;height:8px;border-radius:2px;margin-right:5px;flex-shrink:0}
.wxrow{display:flex}
.wcol{flex:1;min-width:0;text-align:center;position:relative;padding:0 1px}
.wcol.trip::before{content:'';position:absolute;inset:0;background:rgba(87,166,100,.07)}
.bktrow{height:16px;font-family:var(--mono);font-size:9px;color:var(--dry);letter-spacing:.08em;text-transform:uppercase}
.bktrow .wcol.trip{border-top:2px solid var(--dry)}
.bktrow .wcol span{position:relative;top:3px;white-space:nowrap}
.iconrow{height:26px}
.wxi{width:22px;height:22px;filter:invert(1) brightness(.92);opacity:.92;vertical-align:middle}
.wxi.sm{width:15px;height:15px;margin-right:4px;flex-shrink:0}
.temparea{position:relative;height:76px}
.temparea svg{position:absolute;inset:0;width:100%;height:100%}
.temparea .wxrow{height:100%}
.tdot{position:absolute;left:50%;transform:translate(-50%,50%);width:7px;height:7px;border-radius:50%;background:var(--temp);border:2px solid var(--bg)}
.tdot.ty{width:5px;height:5px;background:var(--faint);border-width:1px}
.tval{position:absolute;left:50%;transform:translateX(-50%);font-family:var(--mono);font-size:9.5px;color:var(--ink)}
.wcol:not(.trip) .tdot{opacity:.5}
.wcol:not(.trip) .tval{color:var(--faint)}
.rainarea .wcol{display:flex;flex-direction:column;justify-content:flex-end;height:66px}
.mm{font-family:var(--mono);font-size:9px;color:var(--muted);height:13px;white-space:nowrap}
.rb-pair{display:flex;align-items:flex-end;justify-content:center;gap:2px;width:100%}
.rbarv{width:38%;max-width:15px;background:var(--rain);border-radius:3px 3px 0 0}
.rbarv.ty{opacity:.32}
.wcol:not(.trip) .rbarv{opacity:.18}
.wcol:not(.trip) .rbarv.ov{opacity:.45}
.daysrow .wcol{font-family:var(--mono);font-size:9.5px;color:var(--faint);padding-top:5px;white-space:nowrap;overflow:hidden}
.daysrow .wcol.trip{color:var(--ink);font-weight:600}
.windrow .wcol{font-family:var(--mono);font-size:9.5px;color:var(--faint);padding-top:2px}
.windrow .hi{color:var(--mixed);font-weight:600}
.warr{display:inline-block;font-size:10px;color:var(--muted);margin-left:1px}
.wx-legend{display:flex;gap:16px;font-size:10.5px;color:var(--muted);margin-top:12px;flex-wrap:wrap}
.wx-legend .sw{display:inline-block;width:10px;height:8px;border-radius:2px;margin-right:5px;vertical-align:baseline}
.wx-legend .swl{display:inline-block;width:14px;height:2px;margin:0 5px 3px 0}
.outlook{margin-top:14px;font-size:12px;color:var(--muted);border:1px dashed var(--line2);border-radius:8px;padding:8px 12px;max-width:760px}
.outlook b{color:var(--ink)}
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;max-width:880px}
.fcard{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:15px 16px}
.fwho{font-family:var(--disp);font-weight:700;font-size:15px}
.ffrom{font-size:11px;color:var(--muted);margin-bottom:10px}
.fprice{font-family:var(--mono);font-weight:600;font-size:24px;letter-spacing:-.02em;margin-bottom:4px}
.fprice span{font-family:var(--body);font-size:11px;font-weight:400;color:var(--muted)}
.fopt{display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:5px 0;border-bottom:1px solid var(--line);color:var(--muted)}
.fopt:last-of-type{border-bottom:0}
.fopt>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fopt b{color:var(--ink);font-weight:500}
.fstop{font-family:var(--mono);font-size:10.5px;flex-shrink:0}
.fstop.direct{color:var(--dry);font-weight:600}
.fmode{font-size:13px;font-weight:600;color:var(--dry)}
.fmode-sub{font-size:11.5px;color:var(--muted);margin-top:2px}
.btn{display:block;text-align:center;text-decoration:none;font-size:12px;font-weight:600;border-radius:8px;padding:8px 10px;margin-top:10px;background:var(--ink);color:var(--bg)}
.btn:hover{opacity:.88}
.btn.ghost{background:none;border:1px solid var(--line2);color:var(--ink);font-weight:500;margin-top:6px}
.btn.ghost:hover{border-color:var(--muted)}
.climbgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:2px 26px;max-width:1100px}
.climb{display:flex;gap:13px;padding:12px 0;border-bottom:1px solid var(--line);align-items:flex-start}
.cthumb{width:78px;height:60px;border-radius:8px;overflow:hidden;background:var(--card);border:1px solid var(--line);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:22px}
.cthumb img{width:100%;height:100%;object-fit:cover}
.cname{font-family:var(--disp);font-weight:700;font-size:14px}
.croute{font-size:12px;color:var(--muted);margin:1px 0 6px}
.cpills{display:flex;gap:5px;flex-wrap:wrap}
.cp{font-family:var(--mono);font-size:9.5px;padding:2px 7px;border-radius:4px;background:var(--card);border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.cp.warn{color:var(--mixed);border-color:rgba(185,138,46,.4);background:var(--mixed-bg)}
.cgrade{margin-left:auto;font-family:var(--mono);font-weight:600;font-size:13px;flex-shrink:0;padding-top:2px}
.empty{font-size:13px;color:var(--muted)}
.hgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;max-width:880px}
.hcard{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:14px 15px}
.hname{font-weight:600;font-size:13.5px}
.hstars{color:var(--mixed);font-size:11px;white-space:nowrap}
.htype{font-size:11px;color:var(--muted);margin:2px 0 7px}
.hprice{font-family:var(--mono);font-weight:600;font-size:18px}
.hprice span{font-family:var(--body);font-size:10.5px;font-weight:400;color:var(--muted)}
.htags{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}
.htag{font-size:10px;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:2px 6px;color:var(--muted)}
.sample{font-family:var(--mono);font-size:8.5px;letter-spacing:.08em;background:var(--card);border:1px solid var(--line2);border-radius:4px;padding:2px 6px;color:var(--muted);margin-left:6px}
.guide{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:11px;padding:12px 15px;max-width:460px;margin-top:12px}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line2);border-radius:4px}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
@media(prefers-reduced-motion:no-preference){.row,.tl,.btn{transition:background .12s,border-color .12s,opacity .12s}}
@media(max-width:900px){
  .layout{display:block}
  .board{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line2)}
  .top{padding:12px 16px;gap:8px 14px}
  .basis{padding:8px 16px}
  .band{padding:22px 16px 20px;min-height:172px}
  .band-body{max-width:100%}
  .band svg.topo{right:-70px}
  .band svg.topo .rings{opacity:.5}
  .sec{padding:18px 16px}
  .row{padding:11px 16px}
  .wxgrid{grid-template-columns:50px minmax(0,1fr)}
  .daysrow .wcol{font-size:8.5px}
  .wxi{width:17px;height:17px}
  .chip{min-width:84px;padding:8px 10px}
  .spot img{height:210px}
}
</style></head>"""

PAGE_BODY = """<body>
<header class="top">
  <div class="wordmark"><img class="mplogo" src="https://multi-pitch.com/img/logo/mp-logo-white.png" alt="" onerror="this.style.display='none'">multi<b>·</b>pitch<em>trip planner</em></div>
  <div class="trip-line" id="tripline"></div>
  <nav class="top-links">
    <a class="tl" href="knowledge/index.html">Knowledge</a>
    <a class="tl" id="mapBtn" target="_blank" rel="noopener">Map</a>
    <a class="tl" id="sheetBtn" target="_blank" rel="noopener">Spreadsheet</a>
    <a class="tl strong" id="mpBtn" target="_blank" rel="noopener">multi-pitch.com ↗</a>
  </nav>
</header>
<div class="basis" id="basis"></div>
<div class="layout">
  <aside class="board" aria-label="Climbing areas ranked by trip weather">
    <div class="board-hd">
      <div class="eyebrow">Ranked · best weather first</div>
      <div class="board-sub">Score = expected trip-window weather, 0–100. Select an area for details.</div>
    </div>
    <div id="rows"></div>
    <div class="board-ft" id="updated"></div>
  </aside>
  <main class="detail" id="detail"></main>
</div>"""

PAGE_JS = r"""
var D=window.DATA,V=D.venues;
var EM={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
function esc(s){return s==null?'':String(s).replace(/[&<>"']/g,function(c){return EM[c];});}
function num(x){x=Number(x);return isFinite(x)?x:0;}
function safeUrl(u){u=String(u==null?'':u);return /^https:\/\//i.test(u)?esc(u):'';}
var COND={go:['Dry','var(--dry)','var(--dry-bg)'],mix:['Mixed','var(--mixed)','var(--mixed-bg)'],wet:['Wet','var(--wet)','var(--wet-bg)']};
function cond(v){return COND[v.tagCls]||COND.mix;}
var WIND_ICON='https://multi-pitch.com/img/icons/weather/wind.svg';
var THERMO_ICON='https://multi-pitch.com/img/icons/weather/Thermometer-50.svg';
var RAIN_ICON='https://multi-pitch.com/img/icons/weather/Umbrella.svg';

document.getElementById('tripline').innerHTML=D.trip.pills.map(esc).join(' · ');
document.getElementById('mapBtn').href=safeUrl(D.trip.mapUrl);
document.getElementById('sheetBtn').href=safeUrl(D.trip.sheetUrl);
document.getElementById('mpBtn').href=safeUrl(D.trip.mpUrl);
document.getElementById('basis').innerHTML=D.banner.html;
document.getElementById('updated').textContent='Updated '+D.trip.updated+' · weather: Open-Meteo · flights: Google Flights';

function rowHtml(v,i){
  var c=cond(v),sc=num(v.score);
  var bar=v.score>=0
    ?'<div class="rbar-line"><div class="rbar-track"><div class="rbar" style="width:'+Math.max(4,sc)+'%;background:'+c[1]+'"></div></div><span class="rsc">'+sc+'</span></div>'
    :'<div class="rbar-line"><span class="rsc dim">no data yet</span></div>';
  return '<button class="row" data-i="'+i+'" onclick="sel('+i+')">'
    +'<span class="rnum">'+num(v.rank)+'</span>'
    +'<span class="rname">'+esc(v.flag)+' '+esc(v.shortName)+'</span>'
    +'<span class="rsub">'+esc(v.country)+(v.rock?' · '+esc(v.rock):'')+' · <b style="color:'+c[1]+';font-weight:600">'+c[0].toLowerCase()+'</b></span>'
    +bar+'</button>';
}
document.getElementById('rows').innerHTML=V.map(rowHtml).join('');

function hashSeed(s){s=String(s);var h=2166136261;for(var i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
function ringPath(p){
  var n=p.length;
  var d='M'+((p[n-1][0]+p[0][0])/2).toFixed(1)+' '+((p[n-1][1]+p[0][1])/2).toFixed(1);
  for(var i=0;i<n;i++){
    var nx=p[(i+1)%n];
    d+='Q'+p[i][0].toFixed(1)+' '+p[i][1].toFixed(1)+' '+((p[i][0]+nx[0])/2).toFixed(1)+' '+((p[i][1]+nx[1])/2).toFixed(1);
  }
  return d+'Z';
}
function topoSvg(v){
  var c=cond(v),rnd=mulberry(hashSeed(v.name));
  var W=520,H=300,cx=W*0.52+rnd()*W*0.1,cy=H*0.48+rnd()*H*0.08;
  var P=40,noise=[],ph1=rnd()*6.28,ph2=rnd()*6.28,ph3=rnd()*6.28;
  for(var q=0;q<P;q++){
    var a=q/P*6.2832;
    noise.push(0.5*Math.sin(a*2+ph1)+0.3*Math.sin(a*3+ph2)+0.2*Math.sin(a*5+ph3)+(rnd()-0.5)*0.18);
  }
  var rings='';
  for(var i=6;i>=1;i--){
    var r=38+(i-1)*20,pts=[];
    for(q=0;q<P;q++){
      var a2=q/P*6.2832,rr=r*(1+0.2*noise[q]);
      pts.push([cx+Math.cos(a2)*rr*1.28,cy+Math.sin(a2)*rr]);
    }
    rings+='<path d="'+ringPath(pts)+'" fill="'+(i===1?'var(--card)':'none')+'" stroke="'+c[1]+'" stroke-opacity="'+(i===1?0.9:(0.58-i*0.06).toFixed(2))+'" stroke-width="'+(i===1?1.8:1.1)+'"/>';
  }
  var sc=v.score>=0?num(v.score):'–';
  var summit='<text x="'+cx.toFixed(1)+'" y="'+(cy-1).toFixed(1)+'" text-anchor="middle" dominant-baseline="middle" style="font:600 26px var(--mono);fill:var(--ink)">'+sc+'</text>'
    +'<text x="'+cx.toFixed(1)+'" y="'+(cy+17).toFixed(1)+'" text-anchor="middle" style="font:600 7px var(--mono);letter-spacing:.18em;fill:var(--muted)">WEATHER /100</text>';
  return '<svg class="topo" viewBox="0 0 '+W+' '+H+'" aria-hidden="true"><g class="rings">'+rings+'</g>'+summit+'</svg>';
}

function bandHtml(v){
  var c=cond(v);
  var sky=v.wx.skyIcon?'<img class="wxi" src="'+safeUrl(v.wx.skyIcon)+'" alt="">':'';
  var pills='<span class="pill"><span class="dot" style="background:'+c[1]+'"></span>'+c[0]
    +(v.wx.rain!=null?' · '+num(v.wx.rain)+'% wet days':'')+'</span>';
  if(v.wx.live)pills+='<span class="pill">'+sky+' live forecast for your dates</span>';
  if(v.grades)pills+='<span class="pill">Trad '+esc(v.grades)+'</span>';
  return '<header class="band" style="background:'+c[2]+'">'+topoSvg(v)
    +'<div class="band-body">'
    +'<div class="eyebrow">No.'+num(v.rank)+' of '+V.length+' · '+esc(v.flag)+' '+esc(v.country)+'</div>'
    +'<h1 class="vname">'+esc(v.shortName)+'</h1>'
    +'<div class="vmeta">'+esc(v.style||'')+'</div>'
    +'<div class="vpills">'+pills+'</div></div></header>';
}

function highlightHtml(v){
  var c=(v.climbs||[])[0];
  if(!c)return '';
  var img=safeUrl(c.img);
  if(!img)return '';
  var meta=[esc(c.tradGrade||c.grade||''),c.pitches?num(c.pitches)+' pitches':'',c.length?num(c.length)+'m':'',c.approach!=null?num(c.approach)+' min walk-in':'']
    .filter(function(x){return x;}).join(' · ');
  return '<div class="sec"><div class="eyebrow">Highlight climb in this area</div>'
    +'<figure class="spot"><img src="'+img+'" alt="'+esc(c.cliff)+'" loading="lazy" onerror="this.parentElement.style.display=\'none\'">'
    +'<figcaption><div class="spot-name">'+esc(c.cliff)+' · '+esc(c.route)+'</div><div class="spot-meta">'+meta+'</div></figcaption></figure></div>';
}

function verdictHtml(v){
  var why=v.why?'<p class="why">'+esc(v.why)+'</p>':'';
  var bits=[];
  if(v.wx.rain!=null)bits.push('late July here typically has <b>'+num(v.wx.rain)+'% wet days</b> with highs of <b>'+num(v.wx.tmax)+'°C</b> (2021–2024 average)');
  if(v.wx.live&&v.wx.liveRain!=null)bits.push('the live forecast for your dates shows <b>'+num(v.wx.liveRain)+'% max rain chance</b>');
  if(v.seasonal)bits.push('the 45-day outlook currently reads <b>'+num(v.seasonal.rain)+'% wet days</b> at <b>'+num(v.seasonal.tmax)+'°C</b>');
  var note=v.score>=0
    ?'<p class="score-note">Why score <b>'+num(v.score)+'/100</b>: ranked on '+esc(v.basis||'weather')+' — '+bits.join('; ')+'.</p>'
    :'<p class="score-note">No weather data yet for this area, so it is unranked.</p>';
  return '<div class="sec"><div class="eyebrow">Why go · why score '+(v.score>=0?num(v.score):'—')+'</div>'+why+note+'</div>';
}

function takeaway(v){
  var t=(v.series||[]).filter(function(s){return s.trip;});
  if(!t.length)return '';
  var ov=t.map(function(s){return s.fc||s.out||null;});
  var haveOv=ov.every(function(x){return x;});
  var src=t.some(function(s){return s.fc;})?'Live forecast for your dates':'45-day outlook for your dates';
  var rows=haveOv?ov:t;
  var wet=rows.filter(function(s){return num(s.precip)>=3;}).length;
  var avgT=Math.round(rows.reduce(function(a,s){return a+num(s.tmax);},0)/rows.length);
  var winds=t.map(function(s){return num((s.fc&&s.fc.wind!=null)?s.fc.wind:s.wind);});
  var maxW=Math.max.apply(null,winds);
  var head=haveOv?src+': ':'Typical late July here: ';
  var wetTxt=wet===0?'<b>rain unlikely</b>':'<b>'+wet+' of '+rows.length+' days wet</b>';
  return '<p class="wx-take">'+head+wetTxt+' · highs around <b>'+avgT+'°C</b> · wind up to <b>'+maxW+' km/h</b>.</p>';
}

function wxHtml(v){
  var s=v.series||[];
  if(!s.length)return '<div class="sec"><div class="eyebrow">Weather</div><div class="empty">No weather data for this area yet.</div></div>';
  var n=s.length;
  function ovOf(d){return d.fc||d.out||null;}
  var anyFc=s.some(function(d){return d.fc;}),anyOut=s.some(function(d){return d.out;});
  var ovLabel=anyFc?'live 16-day forecast':'45-day outlook (experimental)';
  var maxR=1,allT=[];
  s.forEach(function(d){
    maxR=Math.max(maxR,num(d.precip));allT.push(num(d.tmax));
    var o=ovOf(d);if(o){maxR=Math.max(maxR,num(o.precip));allT.push(num(o.tmax));}
  });
  var maxT=Math.max.apply(null,allT),minT=Math.min.apply(null,allT);
  function y(t){var pct=maxT===minT?0.5:(num(t)-minT)/(maxT-minT);return 88-pct*60;}
  function cols(fn,cls){
    return '<div class="wxrow '+(cls||'')+'">'+s.map(function(d,i){
      var o=ovOf(d);
      var tip=esc(d.lbl)+' '+num(d.day)+' — typical: '+num(d.tmax)+'°C, '+num(d.precip)+'mm'+(o?' · '+(d.fc?'forecast':'outlook')+': '+num(o.tmax)+'°C, '+num(o.precip)+'mm':'')+' · wind '+num(d.wind)+' km/h';
      return '<div class="wcol'+(d.trip?' trip':'')+'" title="'+tip+'">'+fn(d,i)+'</div>';
    }).join('')+'</div>';
  }
  var firstTrip=-1;
  s.forEach(function(d,i){if(d.trip&&firstTrip<0)firstTrip=i;});
  var bkt=cols(function(d,i){return d.trip&&i===firstTrip?'<span>your dates</span>':'';},'bktrow');
  var icons=anyFc?cols(function(d){return d.fc&&d.fc.icon?'<img class="wxi" src="'+safeUrl(d.fc.icon)+'" alt="" loading="lazy">':'';},'iconrow'):'';
  var tyPts=s.map(function(d,i){return [(i+0.5)/n*1000,y(d.tmax)];});
  var ovPts=[];
  s.forEach(function(d,i){var o=ovOf(d);if(o)ovPts.push([(i+0.5)/n*1000,y(o.tmax)]);});
  var lines='<svg viewBox="0 0 1000 100" preserveAspectRatio="none">'
    +'<polyline points="'+tyPts.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ')+'" fill="none" stroke="var(--faint)" stroke-width="1.5" stroke-opacity=".8" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>'
    +(ovPts.length>1?'<polyline points="'+ovPts.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ')+'" fill="none" stroke="var(--temp)" stroke-width="2" stroke-opacity=".85" vector-effect="non-scaling-stroke"/>':'')
    +'</svg>';
  var temp='<div class="temparea">'+lines+cols(function(d,i){
    var o=ovOf(d),h='';
    var bt=(100-y(d.tmax)).toFixed(1);
    h+='<span class="tdot ty" style="bottom:'+bt+'%"></span>';
    if(o){
      var bo=(100-y(o.tmax)).toFixed(1);
      h+='<span class="tdot" style="bottom:'+bo+'%"></span><span class="tval" style="bottom:calc('+bo+'% + 7px)">'+num(o.tmax)+'°</span>';
    }else{
      h+='<span class="tval" style="bottom:calc('+bt+'% + 6px)">'+num(d.tmax)+'°</span>';
    }
    return h;
  })+'</div>';
  var rain='<div class="rainarea">'+cols(function(d){
    var o=ovOf(d);
    var tmm=Math.round(num(d.precip)*10)/10;
    var ty='<span class="rbarv ty" style="height:'+(Math.round(num(d.precip)/maxR*44)+2)+'px"></span>';
    var ov=o?'<span class="rbarv ov" style="height:'+(Math.round(num(o.precip)/maxR*44)+2)+'px"></span>':'';
    var lbl=o?Math.round(num(o.precip)*10)/10:tmm;
    return '<span class="mm">'+(lbl>0?lbl:'')+'</span><span class="rb-pair">'+ty+ov+'</span>';
  })+'</div>';
  var days=cols(function(d){return esc(d.lbl)+' '+num(d.day);},'daysrow');
  var wind=cols(function(d){
    var o=d.fc||null;
    var wv=(o&&o.wind!=null)?o.wind:d.wind;
    var arr=(o&&o.dir!=null)?'<span class="warr" style="transform:rotate('+((num(o.dir)+180)%360)+'deg)">↑</span>':'';
    return '<span class="'+(num(wv)>=25?'hi':'')+'">'+num(wv)+arr+'</span>';
  },'windrow');
  var legend='<div class="wx-legend">'
    +'<span><span class="swl" style="background:var(--faint)"></span>typical late July (avg 2021–24, dashed)</span>'
    +((ovPts.length)?'<span><span class="swl" style="background:var(--temp)"></span>'+ovLabel+' — temp</span>':'')
    +'<span><span class="sw" style="background:var(--rain);opacity:.35"></span>typical rain</span>'
    +((ovPts.length)?'<span><span class="sw" style="background:var(--rain)"></span>'+ovLabel+' — rain</span>':'')
    +'</div>';
  return '<div class="sec"><div class="sec-hd"><div class="eyebrow">Weather · '+esc(D.trip.dates)+'</div>'
    +(safeUrl(v.weather)?'<a class="lk sm" target="_blank" rel="noopener" href="'+safeUrl(v.weather)+'">Full forecast on Windy ↗</a>':'')+'</div>'
    +takeaway(v)
    +'<div class="wxgrid">'
    +'<div class="wxlbl"></div>'+bkt
    +(icons?'<div class="wxlbl"></div>'+icons:'')
    +'<div class="wxlbl"><img class="wxi sm" src="'+THERMO_ICON+'" alt="">High °C</div>'+temp
    +'<div class="wxlbl"><img class="wxi sm" src="'+RAIN_ICON+'" alt="">Rain mm</div>'+rain
    +'<div class="wxlbl"></div>'+days
    +'<div class="wxlbl"><img class="wxi sm" src="'+WIND_ICON+'" alt="">Wind</div>'+wind
    +'</div>'+legend+'</div>';
}

function flightCard(who,from,f){
  var inner;
  if(!f||f.mode==='unknown'){
    inner='<div class="empty">No travel info for this area.</div>';
  }else if(f.mode==='local'){
    inner='<div class="fmode">Local — no flight needed</div><div class="fmode-sub">Lives near the crags. £0 transport.</div>';
  }else if(f.mode==='drive'){
    inner='<div class="fmode">Drive / train</div><div class="fmode-sub">Reachable without flying — nothing to book.</div>';
  }else{
    var opts=f.options||[],book=safeUrl(f.book_url||f.view_url),view=safeUrl(f.view_url||f.book_url);
    if(!opts.length){
      inner='<div class="fmode-sub">To '+esc(f.to||'?')+' — no live price today.</div>'
        +(view?'<a class="btn" target="_blank" rel="noopener" href="'+view+'">Search flights ↗</a>':'');
    }else{
      var rows=opts.map(function(o,i){
        var st=num(o.stops)===0?'Direct':num(o.stops)+'-stop';
        return '<div class="fopt"><span>'+(i?'£'+num(o.price)+' · ':'')+'<b>'+esc(o.dep)+'→'+esc(o.arr)+'</b> '+esc(o.from)+' · '+esc(String(o.airline||'').slice(0,12))+'</span><span class="fstop'+(num(o.stops)===0?' direct':'')+'">'+st+'</span></div>';
      }).join('');
      inner='<div class="fprice">£'+num(opts[0].price)+' <span>return · per person'+(f.cached?' · last checked price':'')+'</span></div>'+rows
        +(book?'<a class="btn" target="_blank" rel="noopener" href="'+book+'">Book ↗</a>':'')
        +(view&&view!==book?'<a class="btn ghost" target="_blank" rel="noopener" href="'+view+'">All options</a>':'');
    }
  }
  return '<div class="fcard"><div class="fwho">'+esc(who)+'</div><div class="ffrom">from '+esc(from)+'</div>'+inner+'</div>';
}

function climbHtml(c){
  var img=safeUrl(c.img),pills=[];
  if(c.pitches)pills.push(num(c.pitches)+' pitches');
  if(c.length)pills.push(num(c.length)+'m');
  if(c.approach!=null)pills.push(num(c.approach)+' min walk-in');
  if(c.dist!=null)pills.push(num(c.dist)+' km away');
  var ph='<div class="cpills">'+pills.map(function(p){return '<span class="cp">'+p+'</span>';}).join('')
    +(c.flags||[]).map(function(f){return '<span class="cp warn">⚠ '+esc(f)+'</span>';}).join('')+'</div>';
  return '<div class="climb"><div class="cthumb">'+(img?'<img src="'+img+'" alt="" loading="lazy" onerror="this.parentElement.textContent=\'🏔\'">':'🏔')+'</div>'
    +'<div style="min-width:0;flex:1"><div class="cname">'+esc(c.cliff)+'</div><div class="croute">'+esc(c.route)+'</div>'+ph+'</div>'
    +'<div class="cgrade">'+esc(c.tradGrade||c.grade||'')+'</div></div>';
}

function hotelHtml(h){
  var stars='';for(var i=0;i<num(h.stars);i++)stars+='★';
  return '<div class="hcard"><div style="display:flex;justify-content:space-between;gap:8px"><span class="hname">'+esc(h.name)+'</span><span class="hstars">'+stars+'</span></div>'
    +'<div class="htype">'+esc(h.type)+'</div><div class="hprice">'+esc(h.price)+' <span>/ room / night</span></div>'
    +'<div class="htags">'+(h.tags||[]).map(function(t){return '<span class="htag">'+esc(t)+'</span>';}).join('')+'</div>'
    +(safeUrl(h.book)?'<a class="btn ghost" target="_blank" rel="noopener" href="'+safeUrl(h.book)+'">Search Booking.com ↗</a>':'')+'</div>';
}

function detailHtml(v){
  var chips=(v.facts||[]).map(function(f){
    return '<div class="chip"><div class="chip-l">'+esc(f.lbl)+'</div><div class="chip-v">'+esc(f.val)+'</div><div class="chip-s">'+esc(f.sub)+'</div></div>';
  }).join('');
  var hl=highlightHtml(v);
  var rest=(v.climbs||[]).slice(hl?1:0);
  var climbs=rest.length
    ?'<div class="climbgrid">'+rest.map(climbHtml).join('')+'</div>'
    :(hl?'':'<div class="empty">multi-pitch.com has not indexed routes here yet — <a class="lk" target="_blank" rel="noopener" href="'+safeUrl(v.mpMap)+'">browse the map ↗</a></div>');
  var hotels=(v.hotels&&v.hotels.length)
    ?'<div class="hgrid">'+v.hotels.map(hotelHtml).join('')+'</div>'
    :'<div class="empty">No stay ideas for this area yet.</div>';
  var guide=v.guide?'<div class="guide"><div style="font-size:22px">📗</div><div style="flex:1"><div class="hname">'+esc(v.guide.title)+'</div><div class="htype" style="margin-bottom:0">'+esc(v.guide.pub)+' · '+esc(v.guide.price)+'</div></div>'
    +(safeUrl(v.guide.url)?'<a class="lk" style="font-size:12px;flex-shrink:0" target="_blank" rel="noopener" href="'+safeUrl(v.guide.url)+'">Amazon ↗</a>':'')+'</div>':'';
  return bandHtml(v)
    +(chips?'<div class="sec"><div class="chips">'+chips+'</div></div>':'')
    +wxHtml(v)
    +hl
    +verdictHtml(v)
    +'<div class="sec"><div class="eyebrow">Getting there · '+esc(D.trip.dates)+'</div><div class="fgrid">'
      +flightCard('Michel','London',v.flights&&v.flights.michel)
      +flightCard('Dan','Belfast / Dublin',v.flights&&v.flights.dan)+'</div></div>'
    +((climbs)?'<div class="sec"><div class="sec-hd"><div class="eyebrow">'+(hl?'More climbs':'Climbs')+' nearby · from multi-pitch.com</div>'
      +(safeUrl(v.mpMap)?'<a class="lk sm" target="_blank" rel="noopener" href="'+safeUrl(v.mpMap)+'">Browse the map ↗</a>':'')+'</div>'+climbs+'</div>':'')
    +'<div class="sec"><div class="eyebrow">Stay near the crag<span class="sample">sample data</span></div>'+hotels+guide+'</div>'
    +'<div class="sec" style="display:flex;gap:8px;flex-wrap:wrap">'
      +(safeUrl(v.maps)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(v.maps)+'">📍 Google Maps</a>':'')
      +(safeUrl(v.weather)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(v.weather)+'">Detailed forecast — Windy ↗</a>':'')
      +(safeUrl(v.mpMap)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(v.mpMap)+'">multi-pitch.com map ↗</a>':'')
    +'</div>';
}

var _booted=false;
function sel(i){
  var rows=document.querySelectorAll('.row');
  for(var k=0;k<rows.length;k++)rows[k].classList.toggle('active',+rows[k].getAttribute('data-i')===i);
  document.getElementById('detail').innerHTML=detailHtml(V[i]);
  if(_booted&&window.innerWidth<900)document.getElementById('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
sel(0);
_booted=true;
"""


def render_page(data):
    """Assemble the final page from the embedded-data dict. Kept separate from
    build_html so the page can be re-rendered from an existing index.html's
    window.DATA without re-hitting any API."""
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (PAGE_HEAD
            + "\n<script>window.DATA=" + blob + ";</script>\n"
            + PAGE_BODY
            + "<script>" + PAGE_JS + "</script>\n</body></html>\n")


def build_html(ranked, now, banner):
    """Light 'guidebook' dashboard: left = ranked leaderboard (score bars), right =
    area detail (contour-map header with the weather score at the summit, weather
    rows, flights, climbs, sample stays). All per-venue data is embedded as JSON
    and rendered client-side so one static file (GitHub Pages) supports switching
    between areas."""
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
    return render_page(data)


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

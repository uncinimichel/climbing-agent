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
        "&daily=temperature_2m_max,precipitation_sum&timezone=auto"
    )["daily"]
    tmaxs, rain_days, total = [], 0, 0
    per_day = {}   # day-of-month -> {"t": [...], "p": [...]} for the graph window
    for t, tx, pr in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"]):
        dd = date.fromisoformat(t)
        if dd.month != TARGET_START.month or tx is None:
            continue
        if GRAPH_START.day <= dd.day <= GRAPH_END.day:          # graph window (trip ±2)
            per_day.setdefault(dd.day, {"t": [], "p": []})
            per_day[dd.day]["t"].append(tx)
            per_day[dd.day]["p"].append(pr or 0)
        if TARGET_START.day <= dd.day <= TARGET_END.day:        # trip window aggregate
            total += 1
            tmaxs.append(tx)
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
                       "trip": TARGET_START.day <= day <= TARGET_END.day})
    return {"tmax": round(sum(tmaxs) / len(tmaxs)), "rain_pct": round(100 * rain_days / total),
            "days": total, "series": series}


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
    res = {"venue": v, "ok": True, "climo": None, "fc": None}
    try:
        res["climo"] = climatology(v["lat"], v["lon"])
    except Exception:
        res["climo"] = None
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

    fc = res["fc"]
    if fc and fc.get("in_window"):
        res["score"], res["basis"] = fc["score"], "live forecast (trip window)"
    elif res["climo"]:
        res["score"], res["basis"] = climo_score(res["climo"]), "typical July (climatology)"
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


def weather_html(r):
    c, fc = r.get("climo"), r.get("fc")
    main = f"{c['tmax']}°C · <b>{c['rain_pct']}%</b> wet" if c else "<span class='dim'>—</span>"
    if fc and fc.get("in_window"):
        main += f"<div class='vsub'>{fc['sky']} now {fc['tmax']}°C/{fc['rain_prob']}%</div>"
    return (f"{main}<div><a class='flink' href='{weather_url(r['venue'])}' "
            f"target='_blank' rel='noopener'>forecast ↗</a></div>")


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
    out.append(f"<div class='vsub'>times = outbound; return {REP_BACK_LBL.split()[0]} via link</div>")
    out.append(f"<a class='flink' href='{url}' target='_blank' rel='noopener'>book ↗</a>")
    return "".join(out)


def weather_graph_svg(series):
    """Inline SVG: rain bars + high-temp line across the trip window ±2 days."""
    if not series:
        return ""
    W, H, padL, padT, padB = 360, 120, 10, 10, 24
    n = len(series)
    bw = (W - 2 * padL) / n
    plotH = H - padT - padB
    pmax = max([s["precip"] for s in series] + [6.0])
    tmn = min(s["tmax"] for s in series)
    tmx = max(s["tmax"] for s in series)
    trng = max(1, tmx - tmn)
    parts = []
    trip = [i for i, s in enumerate(series) if s["trip"]]
    if trip:
        x0 = padL + trip[0] * bw
        x1 = padL + (trip[-1] + 1) * bw
        parts.append(f"<rect x='{x0:.0f}' y='{padT}' width='{x1-x0:.0f}' height='{plotH}' "
                     f"fill='rgba(37,99,235,.12)' rx='4'/>")
    pts = []
    for i, s in enumerate(series):
        x = padL + i * bw
        bh = plotH * (s["precip"] / pmax)
        col = "#16a34a" if s["precip"] < 3 else "#d97706" if s["precip"] < 8 else "#dc2626"
        parts.append(f"<rect x='{x+bw*0.22:.1f}' y='{padT+plotH-bh:.1f}' width='{bw*0.56:.1f}' "
                     f"height='{bh:.1f}' fill='{col}' rx='1.5'><title>{s['day']} Jul: {s['precip']}mm rain, {s['tmax']}°C</title></rect>")
        ty = padT + plotH * (1 - (s["tmax"] - tmn) / trng)
        pts.append(f"{x+bw/2:.1f},{ty:.1f}")
        parts.append(f"<text x='{x+bw/2:.1f}' y='{H-9}' text-anchor='middle' font-size='9' "
                     f"fill='#7b8694'>{s['day']}</text>")
    parts.append(f"<polyline points='{' '.join(pts)}' fill='none' stroke='#e6792b' stroke-width='1.6'/>")
    for p in pts:
        cx, cy = p.split(",")
        parts.append(f"<circle cx='{cx}' cy='{cy}' r='2' fill='#e6792b'/>")
    return f"<svg viewBox='0 0 {W} {H}' width='100%' style='max-width:{W}px;height:auto'>{''.join(parts)}</svg>"


def build_html(ranked, now, banner):
    rows = []
    for n, r in enumerate(ranked, 1):
        v = r["venue"]
        if not r.get("ok") or r["score"] < 0:
            rows.append(f"<tr><td>{n}</td><td><b>{v['name']}</b></td><td colspan='4' class='dim'>no data</td></tr>")
            continue
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, f"{n}")
        fl = r.get("flights") or {}
        rows.append(
            f"<tr><td class='rank'>{medal}</td>"
            f"<td><div class='vname'><a class='vlink' href='{maps_url(v)}' target='_blank' rel='noopener'>{v['name']} 🗺️</a></div>"
            f"<div class='vsub'>{v['country']} · {v.get('style','')}</div>"
            f"<div class='srcs'>{source_links(v)}</div></td>"
            f"<td><span class='pill' style='background:{score_color(r['score'])}'>{r['score']}</span></td>"
            f"<td class='wx'>{weather_html(r)}</td>"
            f"<td class='fl'>{flight_html(fl.get('michel'))}</td>"
            f"<td class='fl'>{flight_html(fl.get('dan'))}</td></tr>"
        )
    table = "\n".join(rows)

    top = ranked[0] if ranked and ranked[0].get("ok") and ranked[0]["score"] >= 0 else None
    if top:
        tv = top["venue"]
        fl = top.get("flights") or {}
        def fsum(w):
            f = fl.get(w)
            if not f: return "—"
            if f["mode"] == "local": return "local"
            if f["mode"] == "drive": return "drive"
            opts = f.get("options") or []
            return f"£{opts[0]['price']}" if opts else "see link"
        top_html = (
            f"<div class='hero'><div class='hero-tag'>📍 Best option right now</div>"
            f"<div class='hero-name'>{tv['name']} <span class='hero-flag'>{tv['country']}</span></div>"
            f"<div class='hero-why'>{tv.get('why','')}</div>"
            f"<div class='hero-stats'>"
            f"<span class='stat'><span class='snum'>{top['score']}</span><span class='slab'>score /100</span></span>"
            f"<span class='stat'><span class='snum'>{(top.get('climo') or {}).get('tmax','–')}°</span><span class='slab'>typical July</span></span>"
            f"<span class='stat'><span class='snum'>{(top.get('climo') or {}).get('rain_pct','–')}%</span><span class='slab'>wet days</span></span>"
            f"<span class='stat'><span class='snum'>{fsum('michel')}</span><span class='slab'>✈️ Michel</span></span>"
            f"<span class='stat'><span class='snum'>{fsum('dan')}</span><span class='slab'>✈️ Dan</span></span>"
            f"</div></div>"
        )
    else:
        top_html = "<div class='hero'><div class='hero-why'>No weather data available.</div></div>"

    graph_card = ""
    if top and (top.get("climo") or {}).get("series"):
        graph_card = (
            f"<div class='card'><h2>🌦️ Outlook — {top['venue']['name']}, "
            f"{GRAPH_START:%-d}–{GRAPH_END:%-d %b} (typical)</h2>"
            f"{weather_graph_svg(top['climo']['series'])}"
            f"<p class='legend'>Bars = typical daily rain (🟢 dry &lt;3mm · 🟠 · 🔴 wet &gt;8mm); "
            f"orange line = typical high °C. Shaded = trip days ({TARGET_START:%-d}–{TARGET_END:%-d} Jul). "
            f"Averages {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]}; switches to live forecast from ~8 Jul.</p></div>"
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Climbing Trip Planner — Michel &amp; Dan · ~24 Jul 2026</title>
<style>
:root{{--bg:#eef1f6;--card:#fff;--ink:#1f2733;--dim:#7b8694;--line:#e6eaf0;--accent:#2563eb;
--shadow:0 1px 3px rgba(16,24,40,.08),0 1px 2px rgba(16,24,40,.04);}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0b0f17;--card:#141a24;--ink:#e7edf5;--dim:#8b97a7;
--line:#222c3a;--accent:#5b9dff;--shadow:0 1px 3px rgba(0,0,0,.5);}}}}
*{{box-sizing:border-box}}html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;padding:24px 16px}}
.wrap{{max-width:860px;margin:0 auto}}
h1{{font-size:22px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}}
.lead{{color:var(--dim);font-size:14px;margin:0}}.lead b{{color:var(--ink)}}
.links{{margin:8px 0 0;font-size:13.5px}}
.links a{{color:var(--accent);text-decoration:none;font-weight:600}}.links a:hover{{text-decoration:underline}}
.banner{{margin:16px 0;padding:12px 15px;border-radius:12px;font-size:13.5px;line-height:1.45;
background:#fff7e6;border:1px solid #f3d18a;color:#7a5a12}}
@media(prefers-color-scheme:dark){{.banner{{background:#241d0e;border-color:#5c4a1e;color:#e7cf94}}}}
.banner.ok{{background:#e9f9ef;border-color:#a6e3bd;color:#176436}}
@media(prefers-color-scheme:dark){{.banner.ok{{background:#0f2418;border-color:#235c39;color:#86e0a6}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);
padding:18px 18px;margin:0 0 18px}}
.card h2{{font-size:15px;text-transform:uppercase;letter-spacing:.05em;color:var(--dim);margin:0 0 12px;font-weight:700}}
.hero{{background:linear-gradient(135deg,#2563eb,#1e40af);color:#fff;border:none}}
@media(prefers-color-scheme:dark){{.hero{{background:linear-gradient(135deg,#1e3a8a,#0f2456)}}}}
.hero-tag{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;opacity:.85}}
.hero-name{{font-size:25px;font-weight:800;margin:4px 0 6px}}
.hero-flag{{font-size:14px;font-weight:600;opacity:.85;background:rgba(255,255,255,.16);padding:2px 9px;border-radius:20px;margin-left:6px}}
.hero-why{{font-size:14px;line-height:1.5;opacity:.95;margin-bottom:16px}}
.hero-stats{{display:flex;gap:22px;flex-wrap:wrap}}
.stat{{display:flex;flex-direction:column}}
.snum{{font-size:22px;font-weight:800;line-height:1;color:#fff}}
.slab{{font-size:11px;opacity:.85;margin-top:3px;text-transform:uppercase;letter-spacing:.03em}}
table{{width:100%;border-collapse:separate;border-spacing:0}}
th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--dim);
font-weight:700;padding:0 8px 10px;border-bottom:2px solid var(--line)}}
td{{padding:12px 8px;border-bottom:1px solid var(--line);vertical-align:top;font-size:14px}}
tr:last-child td{{border-bottom:none}}tbody tr:hover{{background:rgba(37,99,235,.04)}}
.rank{{font-size:17px;font-weight:800;width:34px;text-align:center}}
.vname{{font-weight:700;font-size:14.5px}}
.vlink{{color:inherit;text-decoration:none}}.vlink:hover{{color:var(--accent);text-decoration:underline}}
.vsub{{color:var(--dim);font-size:12px;margin-top:2px}}
.srcs{{margin-top:4px;font-size:11.5px}}
.src{{color:var(--accent);text-decoration:none;font-weight:600}}
.src:hover{{text-decoration:underline}}
.src.dim{{color:var(--dim);font-weight:400}}
.wx{{white-space:nowrap}}
.fl{{font-size:13px}}
.fdates{{font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px;white-space:nowrap}}
.opt{{margin-bottom:3px;white-space:nowrap}}
.opt .t{{font-variant-numeric:tabular-nums;color:var(--ink)}}
.flink{{color:var(--accent);text-decoration:none;font-weight:600;font-size:12.5px}}
.flink:hover{{text-decoration:underline}}
.pill{{display:inline-block;min-width:38px;text-align:center;color:#fff;font-weight:800;font-size:14px;padding:4px 9px;border-radius:8px}}
.dim{{color:var(--dim)}}
.legend{{color:var(--dim);font-size:12.5px;margin:12px 2px 0;line-height:1.5}}
footer{{color:var(--dim);font-size:12px;text-align:center;margin-top:6px;line-height:1.7}}
footer a{{color:var(--accent);text-decoration:none}}
@media(max-width:600px){{td .vsub{{display:none}} th,td{{padding-left:5px;padding-right:5px}} .hero-stats{{gap:14px}}}}
</style></head><body><div class="wrap">
<header>
<h1>🧗 Climbing Trip Planner — where should Michel &amp; Dan go?</h1>
<p class="lead">Multi-pitch trip <b>Fri 24 – Tue 28 Jul 2026</b> · ranked best-first · updated {now:%a %d %b %Y, %H:%M UTC}</p>
<div class="links"><a href="{SITE_URL}" target="_blank" rel="noopener">🧗 multi-pitch.com</a> ·
<a href="{SHEET_URL}" target="_blank" rel="noopener">📋 venue spreadsheet</a> ·
<span class="dim">🗺️ tap a venue for Maps</span></div>
</header>
<div class="banner {banner[0]}">{banner[1]}</div>
{top_html}
{graph_card}
<div class="card">
<h2>🏔️ Venues + flights — best first</h2>
<table><thead>
<tr><th>#</th><th>Venue</th><th>Score</th><th>Weather</th><th>✈️ Michel<br><span class='dim'>London</span></th><th>✈️ Dan<br><span class='dim'>Belfast</span></th></tr>
</thead><tbody>
{table}
</tbody></table>
<p class="legend"><b>Score</b> 0–100 (higher = drier). <b>Weather</b> = typical late-July (avg {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]}); live forecast appears within 16 days.
<b>Flights</b> top {TOP_N_FLIGHTS} venues, return <b>🛫 {REP_OUT_LBL} → 🛬 {REP_BACK_LBL}</b> ({REP['nights']} nights): up to <b>3 options each</b>, ranked by best value (price + stop penalty); times shown are <b>outbound</b> (return on {REP_BACK_LBL}). Use <i>book ↗</i> to see return times / change dates. Other date options: {COMBO_LABELS}. Dan is local in NI. <b>forecast ↗</b> opens the venue's detailed weather.</p>
</div>
<footer>Weather: Open-Meteo (free). Flights: Google Flights via SerpApi, updated daily.<br>
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
        lines.append(f"| {n} | {v['name']}<br><sub>{src}</sub> | {r['score']} | {cstr} | {fcell(fl.get('michel'))} | {fcell(fl.get('dan'))} |")
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
        banner = ("", f"📅 Trip is {days_out} days out — beyond the 16-day live forecast (reaches {horizon}). "
                      f"Ranked on <b>typical late-July weather</b> (historical {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]}). "
                      f"Live forecast fills in from ~8 July.")

    INDEX.write_text(build_html(ranked, now, banner))
    md = build_md(ranked, now, banner)
    DAILY.write_text(md)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(md)
    print(f"Wrote index.html, daily-report.md, history/{today}.md")
    print("Ranking:", " > ".join(r["venue"]["name"] for r in ranked if r.get("ok") and r["score"] >= 0))


if __name__ == "__main__":
    main()

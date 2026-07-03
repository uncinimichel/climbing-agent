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

Stays (OpenStreetMap Overpass — free, no key):
  Named accommodation near each venue in three shapes — houses/apartments
  (Airbnb-style), campsites (bring your own kit), hotels/hostels/huts (one room,
  2 adults) — with date-filled Airbnb/Booking search links. Typical per-type
  nightly estimates feed the travel component of the composite score.

Outputs: index.html (Pages), daily-report.md, history/<date>.md. Stdlib only.
"""
import csv
import difflib
import json
import math
import os
import re
import socket
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


def _period_label(a, b):
    """Human name for the trip window, derived from the dates — never hardcoded
    ("late July", "early August", or "late July–early August" across months) so
    future trips on other dates label themselves correctly."""
    def part(d):
        seg = "early" if d.day <= 10 else "mid" if d.day <= 20 else "late"
        return f"{seg} {d:%B}"
    pa, pb = part(a), part(b)
    return pa if pa == pb else f"{pa}–{pb}"


PERIOD_LBL = _period_label(TARGET_START, TARGET_END)
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


# ---- Master venue list: the Google Sheet drives the ranking ---------------
# Michel curates areas in the spreadsheet (downloaded as climbing-trips.csv each
# CI run). Every sheet row becomes a ranked venue: curated venues.json entries
# are enriched with their sheet columns; unmatched rows are generated from the
# GAZETTEER below (coords + airports), falling back to free geocoding.
def _key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def _load_sheet_full():
    """All venue rows with the judgment columns (volume/difficulty/travel/min-trip)."""
    rows = []
    try:
        rdr = list(csv.reader(CLIMBING_CSV.open()))
    except Exception as e:
        print(f"[warn] could not read {CLIMBING_CSV.name}: {e}", file=sys.stderr)
        return rows

    def g(r, j):
        return r[j].strip() if j < len(r) else ""
    for i, r in enumerate(rdr, 1):
        if i < 3 or not r or not r[0].strip():    # rows 1-2 are banner/header
            continue
        rows.append({"row": i, "area": g(r, 0), "country": g(r, 1), "volume": g(r, 2),
                     "max_height": g(r, 4), "difficulty": g(r, 5), "travel_time": g(r, 6),
                     "hub": g(r, 7), "min_trip": g(r, 8), "cost": g(r, 9), "link": g(r, 22)})
    return rows


def _fly(m_to, d_to=None):
    return {"michel": {"mode": "fly", "to": m_to}, "dan": {"mode": "fly", "to": d_to or m_to}}


# Coords + airports for sheet areas (keys = accent-stripped lowercase sheet names,
# in the sheet's own spellings). New sheet rows missing here are geocoded.
GAZETTEER = {
    "tenerife": dict(lat=28.27, lon=-16.64, rock="volcanic", style="Cañadas del Teide multi-pitch", travel=_fly("TFS")),
    "mallorca": dict(lat=39.72, lon=2.77, rock="limestone", style="Sa Gubia + sea cliffs", travel=_fly("PMI")),
    "riglos": dict(lat=42.35, lon=-0.73, rock="conglomerate", style="huge overhanging towers", aspect="S", travel=_fly("BCN")),
    "vratsa": dict(lat=43.20, lon=23.55, rock="limestone", style="big limestone walls", travel=_fly("SOF")),
    "elbsandstein": dict(lat=50.91, lon=14.06, rock="sandstone", style="historic sandstone towers", travel=_fly("PRG")),
    "montserrat": dict(lat=41.60, lon=1.81, rock="conglomerate", style="pocketed conglomerate spires", travel=_fly("BCN")),
    "freyr": dict(lat=50.22, lon=4.89, rock="limestone", style="Meuse valley slab classics", travel=_fly("BRU")),
    "meteora": dict(lat=39.72, lon=21.63, rock="conglomerate", style="monastery towers, bold conglomerate", travel=_fly("SKG")),
    "anti atlas": dict(lat=29.72, lon=-8.98, rock="quartzite", style="vast desert trad (Tafraout)", travel=_fly("AGA")),
    "bruggler": dict(lat=47.12, lon=8.99, rock="limestone", style="plated limestone slabs", aspect="S", travel=_fly("ZRH")),
    "setesdal": dict(lat=58.9, lon=7.4, rock="granite", style="granite walls & slabs", travel=_fly("KRS")),
    "loften": dict(lat=68.12, lon=13.6, rock="granite", style="arctic granite (Presten, Svolvær)", travel=_fly("BOO")),
    "wadi rum": dict(lat=29.57, lon=35.42, rock="sandstone", style="desert big walls, Bedouin routes", travel=_fly("AQJ")),
    "triglav": dict(lat=46.38, lon=13.84, rock="limestone", style="north-face alpine limestone", travel=_fly("LJU")),
    "lundy": dict(lat=51.18, lon=-4.67, rock="granite", style="island sea-cliff granite",
                  travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "BRS"}}),
    "costa blanca": dict(lat=38.63, lon=0.07, rock="limestone", style="Peñón d'Ifach + big ridges", aspect="S", travel=_fly("ALC")),
    "zadiel": dict(lat=48.62, lon=20.83, rock="limestone", style="karst gorge towers", travel=_fly("KSC")),
    "calanques": dict(lat=43.21, lon=5.45, rock="limestone", style="sea cliffs above turquoise coves", aspect="S", travel=_fly("MRS")),
    "gredos": dict(lat=40.27, lon=-5.17, rock="granite", style="Galayos granite spires", aspect="W", travel=_fly("MAD")),
    "sicilly": dict(lat=38.17, lon=12.74, rock="limestone", style="San Vito lo Capo sea cliffs", travel=_fly("PMO")),
    "campanile basso": dict(lat=46.16, lon=10.87, rock="dolomite", style="Brenta's free-standing tower", travel=_fly("VRN")),
    "mont blonc": dict(lat=45.88, lon=6.89, rock="granite", style="high alpine granite (Chamonix)", travel=_fly("GVA")),
    "spitzkoppe": dict(lat=-21.83, lon=15.19, rock="granite", style="desert granite dome", travel=_fly("WDH")),
    "hoy": dict(lat=58.88, lon=-3.43, rock="sandstone", style="Old Man of Hoy sea stack", aspect="W", travel=_fly("KOI")),
    "isle of white": dict(lat=50.66, lon=-1.30, rock="chalk", style="south-coast sea cliffs",
                          travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "SOU"}}),
    "devon": dict(lat=50.92, lon=-4.56, rock="culm sandstone", style="Culm coast slabs (Wreckers Slab)",
                  travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "EXT"}}),
    "carcassonne": dict(lat=43.21, lon=2.35, rock="limestone", style="southern France crags", travel=_fly("CCF")),
    "medina": dict(lat=24.47, lon=39.61, rock="granite", style="desert granite", travel=_fly("MED")),
    "aladaglar": dict(lat=37.80, lon=35.15, rock="limestone", style="Turkish alpine limestone", travel=_fly("ASR")),
}

# sheet spelling -> curated venues.json name
SHEET_ALIAS = {
    "east tyrol": "East Tyrol (Lienz)", "picos europa": "Picos de Europa",
    "dolomites": "Dolomites (Cortina)", "aaran": "Isle of Arran",
    "mournes": "Mournes, NI", "lake district": "Lake District (Borrowdale)",
    "llanberis": "Snowdonia (Llanberis Pass)", "cornwall": "West Cornwall (Bosigran)",
}


def _geocode(name):
    """Open-Meteo's free geocoder — fallback for sheet rows not in the GAZETTEER."""
    try:
        d = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&name="
                 + urllib.parse.quote(name))
        res = (d.get("results") or [None])[0]
        if res:
            return dict(lat=res["latitude"], lon=res["longitude"],
                        country=res.get("country", ""), rock="", style="",
                        travel={"michel": {"mode": "fly", "to": ""}, "dan": {"mode": "fly", "to": ""}})
    except Exception as e:
        print(f"[warn] geocode failed for {name}: {_redact(e)}", file=sys.stderr)
    return None


def build_venues():
    """Sheet rows (deduped, in sheet order) merged with curated venues.json entries;
    curated venues without a sheet row (e.g. Paklenica) are appended after."""
    curated = {v["name"]: v for v in _cfg["venues"]}
    out, used, seen = [], set(), set()
    for sh in _load_sheet_full():
        k = _key(sh["area"])
        if not k or k in seen:
            continue
        seen.add(k)
        cname = SHEET_ALIAS.get(k)
        if cname and cname in curated:
            v = dict(curated[cname])
            used.add(cname)
        else:
            g = GAZETTEER.get(k) or _geocode(sh["area"])
            if not g:
                print(f"[warn] sheet area '{sh['area']}' has no coords — skipped", file=sys.stderr)
                continue
            v = {"name": sh["area"], "country": sh["country"] or g.get("country", ""),
                 "priority": "7 (from sheet)", "lat": g["lat"], "lon": g["lon"],
                 "rock": g.get("rock", ""), "style": g.get("style", ""), "why": "",
                 "travel": g["travel"], "auto": True}
        v["sheet"] = sh
        out.append(v)
    for name, v in curated.items():
        if name not in used:
            v = dict(v)
            v["sheet"] = None
            out.append(v)
    return out


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
    "Northern Ireland": "☘️", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Italy": "🇮🇹", "Austria": "🇦🇹", "Spain": "🇪🇸", "Croatia": "🇭🇷", "France": "🇫🇷", "Ireland": "🇮🇪",
    "Norway": "🇳🇴", "Germany": "🇩🇪", "Belgium": "🇧🇪", "Bulgaria": "🇧🇬", "Greece": "🇬🇷",
    "Turkey": "🇹🇷", "Slovakia": "🇸🇰", "Slovenia": "🇸🇮", "Portugal": "🇵🇹", "Switzerland": "🇨🇭",
    "Morocco": "🇲🇦", "Jordan": "🇯🇴", "Jodan": "🇯🇴", "Namibia": "🇳🇦", "Saudi Arabia": "🇸🇦",
    # the sheet's own spellings
    "Slovinia": "🇸🇮", "Swizzerland": "🇨🇭",
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


USER_AGENT = "climbing-agent/1.0 (github.com/uncinimichel/climbing-agent)"


def _get(url, retries=4):
    """GET JSON with retries — APIs rate-limit bursts; never silently lose a sample.
    Client errors (4xx: bad key/params) are NOT retried — retrying can't fix them and
    just burns ~15s × venues. Errors are re-raised with the key redacted. A real
    User-Agent is required by some providers (Overpass 406s on Python's default)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=45) as r:
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


# The ranked venue list: every sheet row + curated extras. Built after _get is
# defined because the geocoder fallback for unknown sheet rows uses it.
VENUES = build_venues()


# ---- Weather --------------------------------------------------------------
def forecast(lat, lon):
    """16-day live forecast (Open-Meteo's max). Beyond the sky/temp/wind basics we pull
    climbing-quality signals — gusts (exposed multi-pitch), sunshine + precip_hours (rock
    drying), and hourly dewpoint/humidity (friction / 'grease'). All free, one request."""
    return _get(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,precipitation_hours,"
        "windspeed_10m_max,wind_gusts_10m_max,winddirection_10m_dominant,"
        "sunshine_duration,daylight_duration"
        "&hourly=dewpoint_2m,relative_humidity_2m,precipitation"
        "&timezone=auto&forecast_days=16"
    )


# Climatology never changes (fixed 2021–24 archive), so it's cached to disk and
# committed — repeated runs then skip the weight-heavy archive API entirely
# (which rate-limits after a few full 42-venue runs in an hour).
CLIMO_CACHE_F = ROOT / "climo-cache.json"
try:
    _CLIMO_CACHE = json.loads(CLIMO_CACHE_F.read_text())
except Exception:
    _CLIMO_CACHE = {}


def climatology(lat, lon):
    """Typical trip-window conditions over recent years — ONE ranged request, filtered.
    Days are matched by real (month, day) against the graph/trip windows, so this stays
    correct even when the trip straddles a month boundary (e.g. 30 Jul–3 Aug)."""
    ck = f"{lat},{lon}|{CLIMO_YEARS[0]}-{CLIMO_YEARS[-1]}|{GRAPH_START:%m%d}-{GRAPH_END:%m%d}|v2"
    if ck in _CLIMO_CACHE:
        return _CLIMO_CACHE[ck]
    d = _get(
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={CLIMO_YEARS[0]}-{GRAPH_START:%m-%d}&end_date={CLIMO_YEARS[-1]}-{GRAPH_END:%m-%d}"
        "&daily=temperature_2m_max,precipitation_sum,windspeed_10m_max,winddirection_10m_dominant&timezone=auto"
    )["daily"]
    tmaxs, winds, rain_days, total = [], [], 0, 0
    per_day = {}   # (month, day) -> {"t","p","w"} lists for the graph window
    dirs = d.get("winddirection_10m_dominant") or [None] * len(d["time"])
    for t, tx, pr, wd, wdir in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"],
                                   d.get("windspeed_10m_max", [None] * len(d["time"])), dirs):
        dd = date.fromisoformat(t)
        md = (dd.month, dd.day)
        if tx is None:
            continue
        if md in GRAPH_MD:                       # graph window (trip ±2)
            e = per_day.setdefault(md, {"t": [], "p": [], "w": []})
            e["t"].append(tx)
            e["p"].append(pr or 0)
            e["w"].append(wd or 0)
            if wdir is not None:
                e.setdefault("dx", []).append(math.cos(math.radians(wdir)))
                e.setdefault("dy", []).append(math.sin(math.radians(wdir)))
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
                           "dir": (round(math.degrees(math.atan2(sum(pd["dy"]), sum(pd["dx"]))) % 360)
                                   if pd.get("dx") else None),
                           "trip": md in TRIP_MD})
        day += timedelta(days=1)
    out = {"tmax": round(sum(tmaxs) / len(tmaxs)), "rain_pct": round(100 * rain_days / total),
           "wind": round(sum(winds) / len(winds)), "days": total, "series": series}
    _CLIMO_CACHE[ck] = out
    try:
        CLIMO_CACHE_F.write_text(json.dumps(_CLIMO_CACHE))   # persist as we go
    except Exception:
        pass
    return out


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


def friction_label(dew):
    """Rock friction from daytime dewpoint (°C). Low dewpoint = crisp, grippy rock;
    high dewpoint = humid, greasy. The single best rock-quality signal we have."""
    if dew is None:
        return None
    if dew < 8:
        return "crisp"
    if dew < 13:
        return "good"
    if dew < 17:
        return "humid"
    return "greasy"


def day_score(code, mm, prob, m=None):
    """0–100 for a single forecast day. Base = rain probability + amount + storm caps.
    `m` (optional) carries the richer signals — gusts, wet-hours, sunshine (drying) and
    dewpoint (friction) — each a gentle, bounded nudge so ranking never swings wildly."""
    s = 100.0 - (prob or 0) * 0.8 - (mm or 0) * 6
    if code is not None and code >= 61:
        s = min(s, 25)
    if code in (95, 96, 99):
        s = min(s, 15)
    if m:
        if m.get("gust") is not None:            # gusts bite on exposed routes / sea-cliffs
            s -= max(0, m["gust"] - 30) * 0.6     # 50 km/h ≈ −12
        if m.get("precip_hours") is not None:     # hours of rain, not just total mm
            s -= min(m["precip_hours"], 12) * 0.8  # up to ≈ −10
        if m.get("sun_frac") is not None:         # sun dries rock → reward, dull → penalise
            s += (m["sun_frac"] - 0.5) * 10        # ±5
        if m.get("dew") is not None:              # friction / grease
            s -= max(0, m["dew"] - 12) * 1.2       # dew 20 ≈ −10
        if m.get("tmax") is not None:             # same climbing heat curve as climatology
            s -= heat_penalty(m["tmax"])
    return max(0.0, min(100.0, s))


def heat_penalty(tmax):
    """Climbing-specific heat curve. Friction research puts ideal sending temps at
    ~7–18°C (climbing.com 'Science of Friction'; UKC conditions threads agree);
    rubber and skin grease out past ~20–25°C, and multi-pitch means HOURS exposed
    on the wall with no shade retreat. Cumulative slopes: gentle from 20°C, steep
    from 25°C, brutal from 30°C — a 31°C coastal venue loses ~36 points."""
    return (max(0, tmax - 20) * 1.2
            + max(0, tmax - 25) * 3
            + max(0, tmax - 30) * 5)


def climo_score(c):
    s = 100 - c["rain_pct"] * 0.9
    s -= max(0, 8 - c["tmax"]) * 2      # too cold: numb fingers below ~8°C
    s -= heat_penalty(c["tmax"])
    return max(0, min(100, round(s)))


# Felt temperature ON THE ROCK: direct sun on a wall reads far hotter than air
# temp, and a shaded N face climbs cooler — crag aspect × actual sunniness.
ASPECT_ADJ = {"N": -4, "NE": -3, "NW": -2, "E": -1, "W": 2, "SE": 3, "SW": 3, "S": 4}


def sun_adjusted_tmax(v, tmax, sun_frac=None):
    """Aspect comes from venues.json / GAZETTEER ('aspect'; unknown → mild +1 sun
    bump). Sunniness = forecast sunshine fraction when live, dryness as a proxy
    for the climatology/outlook horizons."""
    if tmax is None:
        return tmax
    adj = ASPECT_ADJ.get((v.get("aspect") or "").upper(), 1)
    s = 0.7 if sun_frac is None else max(0.0, min(1.0, sun_frac))
    return tmax + adj * s


def _asp_m(v, m):
    """Apply the aspect/sun adjustment to a live-forecast day's metrics dict."""
    if m and m.get("tmax") is not None:
        m = dict(m, tmax=sun_adjusted_tmax(v, m["tmax"], m.get("sun_frac")))
    return m


def forecast_metrics(d):
    """Per-day derived climbing signals from a forecast response, keyed by ISO date.
    Daily gives gusts / sunshine / precip-hours; hourly dewpoint+humidity are averaged
    over daytime (09–18 local) for friction, and 07–12 dryness flags an AM window.
    Everything is best-effort — any missing field just yields None for that signal."""
    daily = d.get("daily", {})
    times = daily.get("time", [])
    gusts = daily.get("wind_gusts_10m_max") or [None] * len(times)
    sun = daily.get("sunshine_duration") or [None] * len(times)
    daylt = daily.get("daylight_duration") or [None] * len(times)
    phours = daily.get("precipitation_hours") or [None] * len(times)

    # aggregate hourly dewpoint/humidity/precip into per-date daytime means
    h = d.get("hourly", {})
    htime = h.get("time", [])
    hdew, hhum, hpre = (h.get("dewpoint_2m") or [], h.get("relative_humidity_2m") or [],
                        h.get("precipitation") or [])
    day_dew, day_hum, am_wet = {}, {}, {}
    for j, ts in enumerate(htime):
        date_s, hr = ts[:10], int(ts[11:13]) if len(ts) >= 13 else 0
        if 9 <= hr <= 18:
            if j < len(hdew) and hdew[j] is not None:
                day_dew.setdefault(date_s, []).append(hdew[j])
            if j < len(hhum) and hhum[j] is not None:
                day_hum.setdefault(date_s, []).append(hhum[j])
        if 7 <= hr <= 12 and j < len(hpre) and (hpre[j] or 0) >= 0.2:
            am_wet[date_s] = True

    tmaxs = daily.get("temperature_2m_max") or [None] * len(times)
    out = {}
    for i, ds in enumerate(times):
        dew = round(sum(day_dew[ds]) / len(day_dew[ds]), 1) if day_dew.get(ds) else None
        hum = round(sum(day_hum[ds]) / len(day_hum[ds])) if day_hum.get(ds) else None
        sf = (sun[i] / daylt[i]) if (sun[i] is not None and daylt[i]) else None
        out[ds] = {
            "tmax": tmaxs[i],
            "gust": round(gusts[i]) if gusts[i] is not None else None,
            "sun_frac": round(sf, 2) if sf is not None else None,
            "precip_hours": round(phours[i], 1) if phours[i] is not None else None,
            "dew": dew, "humid": hum,
            "am_dry": (ds in am_wet) is False if htime else None,
            "friction": friction_label(dew),
        }
    return out


def evaluate(v):
    res = {"venue": v, "ok": True, "climo": None, "fc": None, "seasonal": None}
    res["stays"] = stay_options(v)   # places to stay (OSM Overpass, disk-cached)
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
        daily = d["daily"]
        days = daily["time"]
        met = forecast_metrics(d)                     # per-ISO-date derived signals
        valid = [i for i in range(len(days)) if daily["temperature_2m_max"][i] is not None]
        in_win = [i for i in valid if TARGET_START <= date.fromisoformat(days[i]) <= TARGET_END]
        winds = daily.get("windspeed_10m_max") or [None] * len(days)
        dirs = daily.get("winddirection_10m_dominant") or [None] * len(days)
        # per-day live forecast for graph-window days (overlaid on the typical chart)
        res["fc_days"] = {}
        for i in valid:
            dd = date.fromisoformat(days[i])
            if (dd.month, dd.day) in GRAPH_MD:
                mi = met.get(days[i], {})
                res["fc_days"][(dd.month, dd.day)] = {
                    "tmax": round(daily["temperature_2m_max"][i]),
                    "precip": round(daily["precipitation_sum"][i] or 0, 1),
                    "icon": wmo_icon(daily["weathercode"][i]),
                    "wind": round(winds[i]) if winds[i] is not None else None,
                    "dir": round(dirs[i]) if dirs[i] is not None else None,
                    "gust": mi.get("gust"), "dew": mi.get("dew"),
                    "friction": mi.get("friction"), "sunFrac": mi.get("sun_frac"),
                }
        if in_win:
            scores = [day_score(daily["weathercode"][i], daily["precipitation_sum"][i],
                                daily["precipitation_probability_max"][i],
                                _asp_m(v, met.get(days[i])))
                      for i in in_win]
            codes = [daily["weathercode"][i] for i in in_win]
            dom = max(set(codes), key=codes.count)
            wm = [met.get(days[i], {}) for i in in_win]
            gusts_w = [x["gust"] for x in wm if x.get("gust") is not None]
            dews_w = [x["dew"] for x in wm if x.get("dew") is not None]
            am_flags = [x["am_dry"] for x in wm if x.get("am_dry") is not None]
            mean_dew = round(sum(dews_w) / len(dews_w), 1) if dews_w else None
            res["fc"] = {
                "score": round(sum(scores) / len(scores)),
                "tmax": round(sum(daily["temperature_2m_max"][i] for i in in_win) / len(in_win)),
                "rain_prob": max((daily["precipitation_probability_max"][i] or 0) for i in in_win),
                "sky": WMO.get(dom, "?"), "sky_icon": wmo_icon(dom),
                "gust_max": max(gusts_w) if gusts_w else None,
                "friction": friction_label(mean_dew), "dew": mean_dew,
                "am_dry_days": (sum(1 for a in am_flags if a), len(am_flags)) if am_flags else None,
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
        c = res["climo"]
        sunny = max(0.35, 1 - c["rain_pct"] / 100)   # dry climate ≈ sunny climate
        cs = climo_score({**c, "tmax": sun_adjusted_tmax(v, c["tmax"], sunny)})
        if sea:
            # gentle blend: climatology dominant, 45-day outlook nudges it
            ssun = max(0.35, 1 - sea["rain_pct"] / 100)
            ss = climo_score({"tmax": sun_adjusted_tmax(v, sea["tmax"], ssun),
                              "rain_pct": sea["rain_pct"]})
            res["score"] = round(0.7 * cs + 0.3 * ss)
            res["basis"] = f"typical {PERIOD_LBL} + long-range outlook"
        else:
            res["score"], res["basis"] = cs, f"typical {PERIOD_LBL} (climatology)"
    else:
        res["score"], res["basis"] = -1, "no data"
    res["wscore"] = res["score"]   # weather-only score; composite overwrites score
    return res


def prio_num(v):
    for ch in v.get("priority", "9"):
        if ch.isdigit():
            return int(ch)
    return 9


# ---- Composite score: weather + travel + venue fit -------------------------
# Weather stays dominant; travel uses live/cached flight prices when known plus
# the sheet's travel-time band; venue fit comes from the sheet's judgment
# columns (volume of multi-pitch, difficulty spread, minimum-trip length).
W_WEATHER, W_TRAVEL, W_FIT = 55, 25, 20
TRIP_DAYS = (TARGET_END - TARGET_START).days + 1
TIME_BAND = {"< 4": 95, "2-4": 95, "4-6": 85, "6-8": 70, "8-10": 55, "10-12": 45, "12-24": 30}
VOL_BAND = {"vast": 100, "large": 85, "moderate": 65, "smaller": 45}
DIFF_BAND = {"full range": 100, "moderate": 90, "medium to hard": 75, "hard": 50}


def _band(txt, table, default):
    t = (txt or "").lower()
    for k, s in table.items():
        if k in t:
            return s
    return default


def _sig(x):
    return max(0, min(100, round(x)))


def weather_signals(r, v):
    """Per-signal 'health checks' for the header ring's outer tier: how little
    each weather signal is costing (100 = costing nothing). Uses the same
    numbers/penalty curves as the score itself. Wind + friction only exist on
    the live-forecast horizon — before that they ship as None ('pending')."""
    fc = r.get("fc") or {}
    if fc.get("in_window"):
        t = sun_adjusted_tmax(v, fc["tmax"]) if fc.get("tmax") is not None else None
        g, dw = fc.get("gust_max"), fc.get("dew")
        return [
            {"n": "Rain", "v": _sig(100 - (fc.get("rain_prob") or 0) * 0.8),
             "d": f"max rain prob {fc.get('rain_prob') or 0}% over the trip"},
            {"n": "Heat", "v": _sig(100 - heat_penalty(t) - max(0, 8 - t) * 2) if t is not None else None,
             "d": f"{round(t)}°C felt on the rock" if t is not None else "no temperature signal"},
            {"n": "Wind", "v": _sig(100 - max(0, (g or 0) - 30) * 0.6) if g is not None else None,
             "d": f"gusts to {g} km/h" if g is not None else "no gust signal"},
            {"n": "Friction", "v": _sig(100 - max(0, (dw or 0) - 12) * 1.2) if dw is not None else None,
             "d": f"daytime dewpoint {dw}°C" if dw is not None else "no dewpoint signal"},
        ]
    c, sea = r.get("climo"), r.get("seasonal")
    if not c:
        return None
    rp = round(0.7 * c["rain_pct"] + 0.3 * sea["rain_pct"]) if sea else c["rain_pct"]
    sunny = max(0.35, 1 - rp / 100)
    tm = 0.7 * c["tmax"] + 0.3 * sea["tmax"] if sea else c["tmax"]
    t = sun_adjusted_tmax(v, tm, sunny)
    pend = "activates when the live forecast reaches your dates"
    return [
        {"n": "Rain", "v": _sig(100 - rp * 0.9), "d": f"{rp}% typical wet days"},
        {"n": "Heat", "v": _sig(100 - heat_penalty(t) - max(0, 8 - t) * 2),
         "d": f"{round(t)}°C felt on the rock"},
        {"n": "Wind", "v": None, "d": pend},
        {"n": "Friction", "v": None, "d": pend},
    ]


def apply_composite(r):
    """Attach r['score'] (composite 0-100) + r['breakdown'] for the UI."""
    v = r["venue"]
    sh = v.get("sheet") or {}
    w = r.get("wscore", -1)
    if w < 0:
        r["score"], r["breakdown"] = -1, None
        return
    # travel: known flight prices (live or cached) per traveller; drive/local are cheap
    fl = r.get("flights") or {}
    costs, cost_bits = [], []
    for who, label in (("michel", "Michel"), ("dan", "Dan")):
        mode = (v.get("travel", {}).get(who) or {}).get("mode")
        opts = ((fl.get(who) or {}).get("options")) or []
        if mode == "local":
            costs.append(0)
            cost_bits.append(f"{label} local £0")
        elif mode == "drive":
            costs.append(90)
            cost_bits.append(f"{label} drives ~£90")
        elif opts:
            costs.append(opts[0]["price"])
            cost_bits.append(f"{label} £{opts[0]['price']} return")
        else:
            costs.append(None)
    known = [c for c in costs if c is not None]
    cost_s = round(max(0, min(100, 100 - (sum(known) / len(known)) / 4))) if known else None
    fl_d = "; ".join(cost_bits) if cost_bits else "no priced flights yet"
    time_s = _band(sh.get("travel_time"), TIME_BAND, 65)
    # stay: the cheapest realistic bed near the crag for the trip's nights —
    # a campsite keeps a venue cheap, a hotel-only area costs points. Typical
    # per-type nightly estimates (OSM has no prices), per person, same £/4
    # slope as flights.
    st = (r.get("stays") or {}).get("cheapest")
    stay_s = None
    if st:
        pp_total = st["est"] / STAY_ADULTS * REP["nights"]
        stay_s = round(max(0, min(100, 100 - pp_total / 4)))
        cost_bits.append(f"stay from ~£{st['est']}/night for 2 ({st['type'].lower()}, est.)")
    tparts = [s for s in (cost_s, time_s, stay_s) if s is not None]
    travel = round(sum(tparts) / len(tparts))
    travel_note = ("; ".join(cost_bits) if cost_bits else "no priced flights yet") \
        + (f" · {sh['travel_time']} from UK (sheet)" if sh.get("travel_time") else "")
    # venue fit from the sheet's judgment columns
    vol_s = _band(sh.get("volume"), VOL_BAND, 60)
    diff_s = _band(sh.get("difficulty"), DIFF_BAND, 70)
    mt = re.search(r"\d+", sh.get("min_trip") or "")
    trip_s = 100 if not mt else max(0, 100 - max(0, int(mt.group()) - TRIP_DAYS) * 25)
    n_routes = len(nearby_climbs(v, km=60))
    routes_s = 50 + min(50, n_routes * 10)   # multi-pitch.com coverage: neutral at 0, +10/route
    fit = round((vol_s + diff_s + trip_s + routes_s) / 4)
    fit_bits = []
    if sh.get("volume"):
        fit_bits.append(f"{sh['volume'].lower()} multi-pitch volume")
    if sh.get("difficulty"):
        fit_bits.append(f"difficulty: {sh['difficulty'].lower()}")
    if sh.get("min_trip"):
        fit_bits.append(f"min trip {sh['min_trip'].lower()} vs your {TRIP_DAYS} days")
    fit_bits.append(f"{n_routes} multi-pitch.com route{'s' if n_routes != 1 else ''} nearby"
                    if n_routes else "no multi-pitch.com routes indexed yet")
    fit_note = "; ".join(fit_bits)
    r["score"] = round((W_WEATHER * w + W_TRAVEL * travel + W_FIT * fit) / 100)
    r["breakdown"] = {
        "weather": w, "travel": travel, "fit": fit,
        "weights": {"weather": W_WEATHER, "travel": W_TRAVEL, "fit": W_FIT},
        "weather_note": r.get("basis", "") + (
            f" · {v['aspect'].upper()}-facing rock ({ASPECT_ADJ.get(v['aspect'].upper(), 0):+d}°C felt in full sun)"
            if v.get("aspect") else ""),
        "travel_note": travel_note, "fit_note": fit_note,
        # each factor's own function, for the header ring's outer tier +
        # hover panels (v = 0-100 sub-score, None = pending/no data)
        "sub": {
            "weather": weather_signals(r, v),
            "travel": [
                {"n": "Flights", "v": cost_s, "d": fl_d},
                {"n": "Time", "v": time_s,
                 "d": f"{sh['travel_time']} from UK (sheet)" if sh.get("travel_time")
                      else "no travel-time band on the sheet — neutral"},
                {"n": "Stay", "v": stay_s,
                 "d": f"{st['type'].lower()} ~£{st['est']}/night for 2 (est.)" if st
                      else "no stay data yet"},
            ],
            "fit": [
                {"n": "Volume", "v": vol_s,
                 "d": f"{sh['volume'].lower()} multi-pitch volume (sheet)" if sh.get("volume")
                      else "no volume note on the sheet — default"},
                {"n": "Difficulty", "v": diff_s,
                 "d": f"difficulty: {sh['difficulty'].lower()} (sheet)" if sh.get("difficulty")
                      else "no difficulty note on the sheet — default"},
                {"n": "Trip fit", "v": trip_s,
                 "d": f"min trip {sh['min_trip'].lower()} vs your {TRIP_DAYS} days" if sh.get("min_trip")
                      else f"no minimum-trip constraint vs your {TRIP_DAYS} days"},
                {"n": "Coverage", "v": routes_s,
                 "d": f"{n_routes} multi-pitch.com route{'s' if n_routes != 1 else ''} within 60 km"
                      if n_routes else "no multi-pitch.com routes indexed — neutral"},
            ],
        },
    }


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
        if r.get("flights"):          # already priced in an earlier pass this run
            cache[v["name"]] = r["flights"]
            continue
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
                "appDiff": c.get("approachDifficulty"),
                "dist": round(d),
                "img": (SITE_URL.rstrip("/") + "/" + img) if img else None,
                "url": climb_url(c),
                "flags": _climb_flags(c),
            }))
    out.sort(key=lambda x: x[0])
    return [c for _, c in out[:limit]]


def climb_url(c):
    """Route page on multi-pitch.com. Must match multi-pitch.com's own
    slugifier EXACTLY (website/js/modules/convertNameToURL.js): lowercase,
    drop apostrophes and slashes, spaces -> hyphens — nothing else. An
    earlier version also stripped accents to plain ASCII, which is wrong:
    the real site keeps diacritics literally in the URL (Peñón de Ifach,
    Brüggler, Freÿr do NOT become Penon/Bruggler/Freyr), so that version
    404'd on every accented cliff or route name. Draft routes (not yet
    published on multi-pitch.com) have no live page at all."""
    route, cliff = c.get("routeName") or "", c.get("cliff") or ""
    if not route or not cliff or (c.get("status") or "publish") != "publish":
        return None
    slug = (f"{route.strip()}-on-{cliff.strip()}".lower()
            .replace("'", "").replace("/", "").replace(" ", "-"))
    return SITE_URL + "climbs/" + slug + "/"


def venue_tags(v, cards, grades, cond_txt=None):
    """Colored tag chips: the sheet's judgment columns + flagship-climbing traits
    derived from nearby multi-pitch.com routes, named after the knowledge-base
    taxonomy (route character & hazard flags, approach)."""
    sh = v.get("sheet") or {}
    tags = []

    def add(kind, text):
        if text:
            tags.append({"k": kind, "t": text})
    if cond_txt:
        add("cond", cond_txt)
    add("vol", sh.get("volume") and f"{sh['volume']} volume")
    add("diff", sh.get("difficulty"))
    add("time", sh.get("travel_time") and f"{sh['travel_time']} from UK")
    add("trip", sh.get("min_trip") and f"min trip {sh['min_trip']}")
    add("height", sh.get("max_height") and f"walls to {sh['max_height']}m")
    add("rock", v.get("rock"))
    asp = (v.get("aspect") or "").upper()
    if asp:
        adj = ASPECT_ADJ.get(asp, 0)
        add("aspect", f"{asp}-facing" + (" · shade" if adj < 0 else " · sun-baked" if adj >= 3 else ""))
    if grades:
        add("grade", f"Trad {grades}")
    if cards:
        add("routes", f"{len(cards)} route{'s' if len(cards) != 1 else ''} on multi-pitch.com")
        _tall = max(cards, key=lambda x: x.get("length") or 0)
        if _tall.get("length"):
            add("height", f"tallest {_tall['length']}m · {_tall['cliff']}")
    if v.get("auto"):
        add("auto", "from your sheet")
    if cards:
        pitches = [x.get("pitches") or 0 for x in cards]
        if max(pitches) >= 6:
            add("grade", f"up to {max(pitches)} pitches")
        # taxonomy hazard/character flags aggregated over the area's routes
        seen_flags = {f for x in cards for f in (x.get("flags") or [])}
        for f in sorted(seen_flags):
            add("hazard", f)
        walks = [x.get("approach") for x in cards if x.get("approach") is not None]
        if walks:
            med = sorted(walks)[len(walks) // 2]
            add("appr", "long walk-ins" if med >= 60 else ("roadside cragging" if med <= 20 else f"~{med} min walk-ins"))
        if any((x.get("appDiff") or 0) >= 3 for x in cards):
            add("hazard", "serious approach")
    return tags[:18]


def _short_name(name):
    return name.split("(")[0].split(",")[0].strip()


# ---- Accommodation: OpenStreetMap Overpass (free, no key) ------------------
# Real named places to stay near each venue, in the three shapes that matter
# for this trip: self-catered houses/apartments (Airbnb-style), campsites
# (bring your own tent + kit) and hotels/hostels/huts (one room, 2 adults).
# OSM carries no prices, so each lodging type gets a typical nightly estimate
# (clearly labelled est., for 2 people) which also feeds the travel component
# of the composite score. Results are disk-cached and committed like the
# climatology — lodging stock changes slowly and Overpass rate-limits bursts.
STAYS_CACHE_F = ROOT / "stays-cache.json"
try:
    _STAYS_CACHE = json.loads(STAYS_CACHE_F.read_text())
except Exception:
    _STAYS_CACHE = {}

# Per-stay "Website" buttons point at whatever OSM's website tag says, and that
# drifts — small operators' sites die, move, or get replaced. A dead direct
# link is worse than no link (a "Booking.com" button that's just a search
# never looks broken; a "Website" button to a 404 does). So every such URL is
# health-checked and the result cached, re-checked every LINK_RECHECK_DAYS so a
# site that comes back isn't hidden forever.
#
# Getting the failure classification right matters a lot here: a first pass
# that also trusted 5xx as "dead" wrongly flagged Premier Inn and other clearly
# live sites, because Cloudflare/Akamai bot-challenges routinely answer non-
# browser requests with 503 (not just 401/403/429) — the exact same "can't
# verify, not actually dead" case, just a different status code. A real
# visitor's browser clears all of these challenges fine; a single automated
# GET can't tell a challenge from a real outage on a status code alone.
# So: only 404/410 (this exact page is confirmed gone) and a DNS resolution
# failure (the domain itself doesn't exist) count as dead on the first check —
# both are unambiguous regardless of bot protection. Everything else that
# fails (timeouts, connection errors, 5xx) only counts after it fails again on
# a LATER day, so one bad network moment can't nuke a fine link.
LINK_HEALTH_F = ROOT / "link-health-cache.json"
try:
    _LINK_HEALTH = json.loads(LINK_HEALTH_F.read_text())
except Exception:
    _LINK_HEALTH = {}
LINK_RECHECK_DAYS = 14
LINK_DEAD_NOW = {404, 410}          # confirmed dead on a single check
LINK_DEAD_DAY = 86400


def link_is_dead(url):
    now = time.time()
    cached = _LINK_HEALTH.get(url, {})
    if now - cached.get("t", 0) < LINK_RECHECK_DAYS * 86400:
        return cached.get("dead", False)
    dns_fail = False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        with urllib.request.urlopen(req, timeout=10):
            dead, ambiguous_fail = False, False
    except urllib.error.HTTPError as e:
        dead, ambiguous_fail = e.code in LINK_DEAD_NOW, e.code not in LINK_DEAD_NOW
    except urllib.error.URLError as e:
        dns_fail = isinstance(e.reason, socket.gaierror)
        dead, ambiguous_fail = dns_fail, not dns_fail
    except Exception:
        dead, ambiguous_fail = False, True   # timeout, connection reset, bad SSL, ...
    if ambiguous_fail:
        last_fail_day = cached.get("fail_day")
        today = int(now // LINK_DEAD_DAY)
        # only escalate to dead once the SAME url has failed on two DIFFERENT
        # days — a single flaky run (ours or the site's) never removes a link
        dead = bool(last_fail_day is not None and last_fail_day != today)
        _LINK_HEALTH[url] = {"dead": dead, "t": now,
                              "fail_day": last_fail_day if dead else today}
    else:
        _LINK_HEALTH[url] = {"dead": dead, "t": now}
    try:
        LINK_HEALTH_F.write_text(json.dumps(_LINK_HEALTH))   # persist as we go
    except Exception:
        pass
    return dead

STAY_RADIUS_KM = 15
STAY_ADULTS = 2
STAY_PER_CAT = 3                     # options shown per category
OSM_STAY_CAT = {                     # OSM tourism=* -> dashboard category
    "apartment": "house", "chalet": "house", "guest_house": "house",
    "camp_site": "camp",
    "hotel": "hotel", "hostel": "hotel", "alpine_hut": "hotel", "motel": "hotel",
}
STAY_TYPE_LBL = {
    "apartment": "Apartment", "chalet": "Chalet", "guest_house": "Guest house",
    "camp_site": "Campsite", "hotel": "Hotel", "hostel": "Hostel",
    "alpine_hut": "Mountain hut", "motel": "Motel",
}
# Mainstream OTAs (Booking.com, Hotels.com, Airbnb) essentially never list
# alpine huts/refuges — they're booked direct or through mountain federations
# (FEDME, FFCAM, CAI...) — so an OTA search for one just returns junk or
# nothing, which reads as "broken" even though the URL loads fine. Same
# reasoning as excluding campsites: don't offer a search an OTA can't answer.
NO_OTA_KINDS = {"camp_site", "alpine_hut"}
# typical £/night for TWO people — rough planning estimates, not live quotes
STAY_EST_NIGHT = {
    "apartment": 95, "chalet": 100, "guest_house": 85, "camp_site": 20,
    "hotel": 115, "hostel": 55, "alpine_hut": 70, "motel": 75,
}
CAMP_NOTE = "unserviced pitch — bring your own tent, mats and cooking kit"


def _amazon(q):
    return "https://www.amazon.co.uk/s?k=" + urllib.parse.quote(q)


def _booking_url(q):
    """Booking.com search pre-filled with the trip dates + 2 adults, 1 room."""
    return "https://www.booking.com/searchresults.html?" + urllib.parse.urlencode({
        "ss": q, "checkin": REP["out"], "checkout": REP["back"],
        "group_adults": STAY_ADULTS, "no_rooms": 1, "group_children": 0})


def _airbnb_url(q):
    """Airbnb area search pre-filled with the trip dates + 2 adults."""
    return (f"https://www.airbnb.co.uk/s/{urllib.parse.quote(q)}/homes?"
            + urllib.parse.urlencode({"adults": STAY_ADULTS,
                                      "checkin": REP["out"], "checkout": REP["back"]}))


def _hotels_url(q):
    """Hotels.com search pre-filled with the trip dates + 2 adults, 1 room."""
    return "https://www.hotels.com/Hotel-Search?" + urllib.parse.urlencode({
        "destination": q, "startDate": REP["out"], "endDate": REP["back"],
        "rooms": 1, "adults": STAY_ADULTS})


def _turbo_url(lat, lon):
    """overpass-turbo deep-link that auto-runs the venue's lodging query (&R):
    every place to stay pin-pointed on a real map, centred on the crag."""
    kinds = "|".join(sorted(OSM_STAY_CAT))
    q = ("[out:json][timeout:30];"
         f'nwr["tourism"~"^({kinds})$"]["name"](around:{STAY_RADIUS_KM * 1000},{lat},{lon});'
         "out center;")
    return f"https://overpass-turbo.eu/?Q={urllib.parse.quote(q)}&C={lat};{lon};11&R"


OVERPASS_HOSTS = ["https://overpass-api.de/api/interpreter",
                  "https://overpass.kumi.systems/api/interpreter",
                  "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]


def overpass_stays(lat, lon):
    """Named lodging within STAY_RADIUS_KM of the venue from Overpass, nearest
    first. One request per venue, then served from the committed disk cache.
    The public endpoints load-shed under bursts, so: gentle pacing between
    uncached fetches + a mirror fallback."""
    ck = f"{lat},{lon}|r{STAY_RADIUS_KM}|v1"
    if ck in _STAYS_CACHE:
        return _STAYS_CACHE[ck]
    kinds = "|".join(sorted(OSM_STAY_CAT))
    q = ("[out:json][timeout:30];"
         f'nwr["tourism"~"^({kinds})$"]["name"](around:{STAY_RADIUS_KM * 1000},{lat},{lon});'
         "out center 80;")
    d, last = None, None
    for host in OVERPASS_HOSTS:
        try:
            d = _get(host + "?data=" + urllib.parse.quote(q), retries=2)
            break
        except Exception as e:
            last = e
    if d is None:
        raise RuntimeError(f"all Overpass mirrors failed: {_redact(last)}")
    time.sleep(1)   # politeness between uncached venue queries
    out = []
    for el in d.get("elements", []):
        t = el.get("tags", {})
        kind, name = t.get("tourism"), (t.get("name") or "").strip()
        la = el.get("lat") or (el.get("center") or {}).get("lat")
        lo = el.get("lon") or (el.get("center") or {}).get("lon")
        if kind not in OSM_STAY_CAT or not name or la is None or lo is None:
            continue
        out.append({"name": name, "kind": kind,
                    "dist": round(_haversine(lat, lon, la, lo), 1),
                    "web": t.get("website") or t.get("contact:website") or ""})
    out.sort(key=lambda s: s["dist"])
    _STAYS_CACHE[ck] = out
    try:
        STAYS_CACHE_F.write_text(json.dumps(_STAYS_CACHE))   # persist as we go
    except Exception:
        pass
    return out


def stay_options(v):
    """Grouped stays payload for one venue. Overpass failing degrades to the
    date-filled search links only (empty list) — it never fails the build."""
    area = f"{_short_name(v['name'])}, {v['country']}"
    try:
        raw = overpass_stays(v["lat"], v["lon"])
    except Exception as e:
        print(f"[warn] stays lookup failed for {v['name']}: {_redact(e)}", file=sys.stderr)
        raw = []
    picks, seen = [], set()
    for cat in ("house", "camp", "hotel"):     # houses first: Michel's preference order
        n = 0
        for s in raw:
            if OSM_STAY_CAT[s["kind"]] != cat or s["name"].lower() in seen:
                continue                        # skip other cats + node/way duplicates
            if n >= STAY_PER_CAT:
                break
            seen.add(s["name"].lower())
            n += 1
            web = s["web"] if s["web"].startswith("https://") else ""
            if web and link_is_dead(web):
                web = ""
            # engines that actually list this category: houses on Airbnb,
            # hotels/hostels/huts on Booking.com + Hotels.com — a specific
            # campsite name rarely resolves on any of the three, so camp
            # keeps just its (verified) own website + map.
            q = f"{s['name']}, {area}"
            picks.append({
                "name": s["name"], "cat": cat, "type": STAY_TYPE_LBL[s["kind"]],
                "dist": s["dist"], "est": STAY_EST_NIGHT[s["kind"]],
                "note": CAMP_NOTE if cat == "camp" else "",
                "web": web,
                "airbnb": _airbnb_url(q) if cat == "house" and s["kind"] not in NO_OTA_KINDS else "",
                "book": _booking_url(q) if cat in ("house", "hotel") and s["kind"] not in NO_OTA_KINDS else "",
                "hotels": _hotels_url(q) if cat == "hotel" and s["kind"] not in NO_OTA_KINDS else "",
                "maps": ("https://www.google.com/maps/search/?api=1&query="
                         + urllib.parse.quote(f"{s['name']} {area}")),
            })
    cheapest = min(picks, key=lambda p: p["est"]) if picks else None
    return {
        "list": picks, "radius": STAY_RADIUS_KM, "adults": STAY_ADULTS,
        "cheapest": ({"est": cheapest["est"], "type": cheapest["type"]} if cheapest else None),
        "search": {"airbnb": _airbnb_url(area), "booking": _booking_url(area),
                   "hotels": _hotels_url(area),
                   "camps": ("https://www.google.com/maps/search/?api=1&query="
                             + urllib.parse.quote(f"campsite near {area}")),
                   "map": _turbo_url(v["lat"], v["lon"])},
    }


# Guidebook per area (title, publisher, £) — curated, with an Amazon search link.
GUIDEBOOKS = {
    "Fair Head": ("Fair Head — A Rock Climbing Guide", "NIMC", 25),
    "Mournes": ("Mourne Mountains — Rock Climbs", "NIMC", 20),
    "Dolomites": ("Dolomites — Rockfax", "Rockfax", 30),
    "East Tyrol": ("Osttirol — Alpinkletterfuehrer", "Panico", 34),
    "Lake District": ("Lake District — Rockfax", "Rockfax", 28),
    "Snowdonia": ("Llanberis — Climbers Club Guide", "Climbers Club", 25),
    "Arran": ("Arran — SMC Climbers Guide", "SMC", 24),
    "Picos": ("Picos de Europa — Rockfax", "Rockfax", 30),
    "Paklenica": ("Paklenica — Climbing Guide", "Astroida", 28),
}


def guidebook(v):
    key = next((k for k in GUIDEBOOKS if k in v["name"]), None)
    if not key:
        return None
    title, pub, price = GUIDEBOOKS[key]
    return {"title": title, "pub": pub, "price": f"£{price}", "url": _amazon(title)}


def _list_info(v, r, cards):
    """Compact extra line for the leaderboard: expected trip temperature, total
    flight cost when priced, route count, and the sheet's difficulty band."""
    parts = []
    sea, c = r.get("seasonal"), r.get("climo")
    fc = r.get("fc") or {}
    t = (fc.get("tmax") if fc.get("in_window") else None)
    if t is None:
        t = (sea or {}).get("tmax") if sea else None
    if t is None:
        t = (c or {}).get("tmax") if c else None
    prices = []
    for who in ("michel", "dan"):
        mode = (v.get("travel", {}).get(who) or {}).get("mode")
        opts = (((r.get("flights") or {}).get(who)) or {}).get("options") or []
        if mode in ("local", "drive"):
            prices.append(0)
        elif opts:
            prices.append(opts[0]["price"])
        else:
            prices.append(None)
    if None not in prices and sum(prices) > 0:
        parts.append(f"✈ £{sum(prices)} flights total")
    if cards:
        parts.append(f"{len(cards)} route" + ("s" if len(cards) != 1 else ""))
    diff = (v.get("sheet") or {}).get("difficulty")
    if diff:
        parts.append(diff)
    return {"txt": " · ".join(parts), "temp": t}


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

    facts = []

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
        entry = {"day": s["day"], "lbl": wd, "tmax": s["tmax"], "dir": s.get("dir"),
                 "precip": s["precip"], "wind": s.get("wind", 0), "trip": s["trip"]}
        md_key = (m, s["day"])
        if md_key in fcd:
            entry["fc"] = fcd[md_key]
        elif md_key in sead:
            entry["out"] = sead[md_key]
        series.append(entry)

    return {
        "rank": n, "name": v["name"], "shortName": _short_name(v["name"]),
        "country": v["country"], "flag": flag(v["country"]), "rock": v.get("rock", ""),
        "style": v.get("style", ""),
        "why": v.get("why", "") or (
            f"{(v.get('sheet') or {}).get('volume') or 'Unknown'}-volume {v.get('rock') or 'rock'}"
            f", {((v.get('sheet') or {}).get('difficulty') or 'range unknown').lower()}"
            f", {(v.get('sheet') or {}).get('travel_time') or '?'} from the UK — auto-summary "
            "from your spreadsheet row; add notes there or in venues.json."),
        "basis": r.get("basis", ""),
        "score": r["score"] if ok else -1, "tag": tag, "tagCls": tcls, "arcColor": arc_color(tcls),
        "wx": {"tmax": c.get("tmax"), "rain": rain, "wind": c.get("wind"),
               "sky": (fc.get("sky") if live else ""), "live": live,
               "skyIcon": (fc.get("sky_icon") if live else None),
               "liveTemp": (fc.get("tmax") if live else None),
               "liveRain": (fc.get("rain_prob") if live else None),
               "friction": (fc.get("friction") if live else None),
               "gustMax": (fc.get("gust_max") if live else None),
               "amDry": (fc.get("am_dry_days") if live else None)},
        "seasonal": ({"tmax": sea["tmax"], "rain": sea["rain_pct"], "members": sea["members"]}
                     if sea and not live else None),
        "series": series,
        "chartLabel": ("Live forecast — trip window" if live
                       else f"Typical {PERIOD_LBL} daily pattern (avg {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]})"),
        "grades": grades, "hero": (cards[0]["img"] if cards else None), "climbs": cards,
        "facts": facts,
        "flights": {"michel": mf, "dan": md},
        "stays": r.get("stays"), "guide": guidebook(v),
        "maps": maps_url(v), "weather": weather_url(v), "mpMap": MP_MAP_URL,
        "tags": venue_tags(v, cards, grades, (f"{tag} · {rain}% wet days" if rain is not None else tag)),
        "listInfo": _list_info(v, r, cards)["txt"],
        "listTemp": _list_info(v, r, cards)["temp"],
        "breakdown": r.get("breakdown"),
        "auto": bool(v.get("auto")),
    }


PAGE_HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src https: data:">
<title>multi·pitch — Trip planner · Michel &amp; Dan · ~24 Jul 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
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
.rnum{grid-row:1/5;font-family:var(--disp);font-weight:800;font-size:21px;line-height:1.1;color:var(--ink);opacity:.3}
.rinfo{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;font-family:var(--mono)}
.bd-leg{display:flex;gap:13px;margin-top:11px;font-family:var(--mono);font-size:10.5px;color:var(--muted);flex-wrap:wrap}
.bd-leg i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.bd-leg span{cursor:pointer}
.bd-leg span:hover{color:var(--ink)}
.bd-cap{margin-top:8px;font-size:11.5px;color:var(--faint);max-width:520px;line-height:1.5;min-height:17px}
.bd-cap b{color:var(--ink)}
.dseg{cursor:pointer;pointer-events:stroke}
svg.topo{pointer-events:none}
svg.topo .dseg{pointer-events:stroke}
.updstamp{color:var(--faint);font-size:11px;white-space:nowrap}
.brkchart{height:300px;max-width:780px;width:100%}
.brkchart svg{display:block;width:100%;height:100%;overflow:visible}
.fgrp{cursor:pointer;transition:opacity .15s}
.fgrp.dim{opacity:.3}
.brkpanel{display:none;position:absolute;top:50%;transform:translateY(-50%);right:calc(100% + 14px);width:236px;background:rgba(20,22,26,.93);border:1px solid var(--line2);border-radius:10px;padding:10px 14px;font-family:var(--mono);pointer-events:none;z-index:3}
.brkpanel.on{display:block;animation:bpfade .16s ease-out}
@keyframes bpfade{from{opacity:0;transform:translate(4px,-50%)}to{opacity:1;transform:translate(0,-50%)}}
@media(prefers-reduced-motion:reduce){.brkpanel.on{animation:none}}
.bp-hd{display:flex;align-items:baseline;gap:7px}
.bp-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0;align-self:center}
.bp-name{font-size:10px;font-weight:700;letter-spacing:.09em;color:var(--ink)}
.bp-wt{font-size:9px;color:var(--faint);font-weight:400}
.bp-score{font-family:var(--disp);font-size:16px;font-weight:800;margin-left:auto}
.bp-fn{font-size:9.5px;color:var(--faint);margin-top:4px;line-height:1.75}
.bp-fn b{font-weight:600}
.bp-pend{opacity:.7;font-style:italic}
.wxchart{height:340px;max-width:920px;width:100%}
.tag-aspect{color:#8FB8C8;border-color:rgba(120,170,195,.4);background:rgba(120,170,195,.08)}
.board-sub .lk{font-size:11px}
.hovl{display:none;position:fixed;inset:0;background:rgba(10,11,14,.72);z-index:60;align-items:center;justify-content:center;padding:18px}
.hbox{background:var(--panel);border:1px solid var(--line2);border-radius:14px;max-width:660px;max-height:86vh;overflow-y:auto;padding:18px 22px 20px;box-shadow:0 18px 60px rgba(0,0,0,.5)}
.hhd{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
.hbody{font-size:13px;line-height:1.7;color:var(--muted)}
.hbody p{margin-bottom:11px}
.hbody b{color:var(--ink)}
.wdir{font-size:9px;color:var(--muted);margin-left:2px}
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
.band{position:relative;overflow:hidden;padding:26px 30px 20px;border-bottom:1px solid var(--line2);min-height:214px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.brkchart.hdr{height:250px;width:min(290px,100%);flex-shrink:0;position:relative;z-index:1;margin-left:auto}
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
.wx-take{font-size:14px;margin-bottom:12px;max-width:760px}
.wx-take b{font-weight:600}
.wx-cond{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px;max-width:760px}
.wx-cond .cc{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);background:var(--card);border:1px solid var(--line2);border-radius:20px;padding:4px 11px}
.wx-cond .cc .ci{font-size:13px;line-height:1}
.wx-cond .cc b{color:var(--ink);font-weight:600}
.wx-cond .cc.good b{color:var(--dry)}
.wx-cond .cc.warn b{color:var(--mixed)}
.wx-cond .cc.bad b{color:var(--wet)}
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
.stale{font-size:10.5px;color:var(--mixed);margin:2px 0 4px}
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
.htype{font-size:11px;color:var(--muted);margin:2px 0 7px}
.hprice{font-family:var(--mono);font-weight:600;font-size:18px}
.hprice span{font-family:var(--body);font-size:10.5px;font-weight:400;color:var(--muted)}
.htags{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}
.htag{font-size:10px;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:2px 6px;color:var(--muted)}
.sample{font-family:var(--mono);font-size:8.5px;letter-spacing:.08em;background:var(--card);border:1px solid var(--line2);border-radius:4px;padding:2px 6px;color:var(--muted);margin-left:6px}
a.sample{text-decoration:none}
a.sample:hover{color:var(--ink);border-color:var(--muted)}
.stay-search{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.stay-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px 16px;max-width:1100px}
.stay-col-hd{font-family:var(--disp);font-weight:700;font-size:14.5px}
.stay-col-sub{font-size:10.5px;color:var(--faint);margin:1px 0 10px}
.stay-col .hcard{margin-bottom:10px}
.stay-none{font-size:12px;color:var(--muted);border:1px dashed var(--line2);border-radius:11px;padding:12px 14px}
.stay-links{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.stay-links .btn{flex:1;margin-top:0;padding:6px 8px;font-size:11px;min-width:90px}
.htag.warn{color:#D9B25E;border-color:rgba(185,138,46,.45);background:var(--mixed-bg)}
.guide{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:11px;padding:12px 15px;max-width:460px;margin-top:12px}
.brk{max-width:760px}
.brk-row{display:grid;grid-template-columns:92px 1fr 116px;gap:10px;align-items:center;margin-bottom:5px}
.brk-lbl{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.brk-track{height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.brk-fill{height:100%;border-radius:4px}
.brk-val{font-family:var(--mono);font-size:11px;color:var(--ink);text-align:right;white-space:nowrap}
.brk-note{font-size:11px;color:var(--faint);margin:-1px 0 11px 102px;line-height:1.5}
.brk-total{display:flex;justify-content:space-between;gap:10px;border-top:1px solid var(--line2);margin-top:8px;padding-top:9px;font-family:var(--mono);font-size:12px;color:var(--muted)}
.brk-total b{color:var(--ink)}
.tagleg{font-size:10.5px;color:var(--faint);margin-bottom:9px}
.tags{display:flex;gap:6px;flex-wrap:wrap;max-width:880px}
.tag{font-family:var(--mono);font-size:10.5px;padding:4px 9px;border-radius:5px;border:1px solid var(--line2);white-space:nowrap}
.tag-vol{color:#7FB2E8;border-color:rgba(57,135,229,.4);background:rgba(57,135,229,.10)}
.tag-height{color:#7FB2E8;border-color:rgba(57,135,229,.28);background:rgba(57,135,229,.06)}
.tag-diff{color:#D08770;border-color:rgba(217,89,38,.4);background:rgba(217,89,38,.10)}
.tag-time{color:#B9A0E8;border-color:rgba(144,110,220,.4);background:rgba(144,110,220,.10)}
.tag-trip{color:#B9A0E8;border-color:rgba(144,110,220,.3);background:rgba(144,110,220,.06)}
.tag-rock{color:var(--muted);background:var(--card)}
.tag-grade{color:#79C289;border-color:rgba(87,166,100,.4);background:var(--dry-bg)}
.tag-hazard{color:#D9B25E;border-color:rgba(185,138,46,.45);background:var(--mixed-bg)}
.tag-appr{color:var(--ink);background:var(--card)}
.tag-cond{color:var(--ink);border-color:var(--line2);background:var(--card);font-weight:600}
.tag-routes{color:#79C289;border-color:rgba(87,166,100,.3);background:rgba(87,166,100,.06)}
.tag-auto{color:var(--muted);border-style:dashed}
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
  /* wind per-day row is too dense to read on a phone — its signal lives in the
     takeaway line + the conditions chips, so drop it from the grid here. */
  .wxlbl-wind,.windrow{display:none}
  .wxi{width:17px;height:17px}
  .chip{min-width:84px;padding:8px 10px}
  .spot img{height:210px}
  .brk-row{grid-template-columns:72px 1fr 100px}
  .brk-note{margin-left:82px}
  .brkchart{height:250px}
  .brkchart.hdr{margin:0 auto}
  /* no room beside the ring on a phone — the maths card floats over it instead */
  .brkpanel{right:auto;left:50%;transform:translate(-50%,-50%);max-width:86vw}
  @keyframes bpfade{from{opacity:0;transform:translate(-50%,-50%)}to{opacity:1;transform:translate(-50%,-50%)}}
  .wxchart{height:300px}
}
</style></head>"""

PAGE_BODY = """<body>
<header class="top">
  <div class="wordmark"><img class="mplogo" src="https://multi-pitch.com/img/logo/mp-logo-white.png" alt="" onerror="this.style.display='none'">multi<b>·</b>pitch<em>trip planner</em></div>
  <div class="trip-line" id="tripline"></div>
  <nav class="top-links">
    <button class="tl" onclick="help(1)" title="How the ranking works" aria-label="How the ranking works">?</button>
    <a class="tl" href="knowledge/index.html">Knowledge</a>
    <a class="tl" id="mapBtn" target="_blank" rel="noopener">Map</a>
    <a class="tl" id="sheetBtn" target="_blank" rel="noopener">Spreadsheet</a>
    <a class="tl" id="ghBtn" target="_blank" rel="noopener" title="Project source on GitHub">GitHub</a>
    <a class="tl strong" id="mpBtn" target="_blank" rel="noopener">multi-pitch.com ↗</a>
  </nav>
</header>
<div class="basis" id="basis"></div>
<div class="layout">
  <aside class="board" aria-label="Climbing areas ranked by trip weather">
    <div class="board-hd">
      <div class="eyebrow">Ranked · best weather first</div>
      <div class="board-sub">Score /100 = weather (55%) + travel (25%) + venue fit (20%).
        <a href="#" class="lk" onclick="help(1);return false">How the ranking works ?</a></div>
    </div>
    <div id="rows"></div>
    <div class="board-ft" id="updated"></div>
  </aside>
  <main class="detail" id="detail"></main>
</div>
<div class="hovl" id="hovl" onclick="if(event.target===this)help(0)">
  <div class="hbox" role="dialog" aria-label="How the ranking works">
    <div class="hhd"><span class="eyebrow">How the ranking works</span><button class="tl" onclick="help(0)">✕ Close</button></div>
    <div class="hbody">
      <p>Every area gets a <b>trip score out of 100</b> — the donut in each header shows the split:</p>
      <p><b style="color:var(--rain)">Weather · 55%</b> — rain first: wet days and rain
      probability cost points, and a forecast rain day is hard-capped. Temperature is scored
      <b>through a climbing lens</b>: friction research puts ideal sending temps around
      <b>7–18°C</b>, so points fall away gently above 20°C, steeply above 25°C, and brutally
      above 30°C (numb-fingers penalty below 8°C too — this is multi-pitch, hours exposed on
      the wall). <b>Sun exposure matters as much as air temperature</b>: a south-facing wall
      in full sun feels far hotter than the thermometer says, while a shaded north face
      climbs cooler — each crag's <b>aspect</b> shifts its felt temperature, weighted by how
      sunny it actually is (cloud/sunshine from the live forecast once in range; dryness as
      a proxy before that). Once the trip is inside the 16-day forecast, friction terms
      (dew point, drying sun, gusts) join in.</p>
      <p><b style="color:var(--temp)">Travel · 25%</b> — real return-flight prices for both
      of you when priced (the top venues each day), otherwise the spreadsheet's travel-time
      band from the UK. Local/drivable venues score near-perfect. The <b>cheapest realistic
      bed near the crag</b> counts too (from OpenStreetMap): an area with a campsite stays
      cheap, a hotel-only area costs points — using typical nightly prices per type of
      stay, not live quotes.</p>
      <p><b style="color:var(--dry)">Venue fit · 20%</b> — from the spreadsheet's judgment
      columns: how much multi-pitch there is, its difficulty spread, and whether the
      minimum sensible trip fits your dates.</p>
      <p>Ranking basis by date: <b>typical weather for your trip dates</b> (recent-year averages) blended with the
      <b>long-range outlook</b> now (a forecast model that can see up to ~45 days ahead — the ‘45-day’ is the model’s reach, not your trip length); the <b>live 16-day forecast takes over ~8 July</b>. The page
      rebuilds daily at 06:00 UTC. Full maths:
      <a class="lk" href="knowledge/data/condition-algorithm.html">condition algorithm</a>.</p>
    </div>
  </div>
</div>"""

PAGE_JS = r"""
var D=window.DATA,V=D.venues;
var EM={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
function esc(s){return s==null?'':String(s).replace(/[&<>"']/g,function(c){return EM[c];});}
function num(x){x=Number(x);return isFinite(x)?x:0;}
function safeUrl(u){u=String(u==null?'':u);return /^https:\/\//i.test(u)?esc(u):'';}
var COND={go:['Dry','var(--dry)','var(--dry-bg)'],mix:['Mixed','var(--mixed)','var(--mixed-bg)'],wet:['Wet','var(--wet)','var(--wet-bg)']};
function cond(v){return COND[v.tagCls]||COND.mix;}
function compass(d){var n=['N','NE','E','SE','S','SW','W','NW'];return n[Math.round((((num(d)%360)+360)%360)/45)%8];}
var WIND_ICON='https://multi-pitch.com/img/icons/weather/wind.svg';
var THERMO_ICON='https://multi-pitch.com/img/icons/weather/Thermometer-50.svg';
var RAIN_ICON='https://multi-pitch.com/img/icons/weather/Umbrella.svg';

document.getElementById('tripline').innerHTML=D.trip.pills.map(esc).join(' · ');
document.getElementById('mapBtn').href=safeUrl(D.trip.mapUrl);
document.getElementById('sheetBtn').href=safeUrl(D.trip.sheetUrl);
document.getElementById('mpBtn').href=safeUrl(D.trip.mpUrl);
document.getElementById('ghBtn').href=safeUrl(D.trip.repoUrl);
document.getElementById('basis').innerHTML=D.banner.html+' <span class="updstamp">· page updated '+esc(D.trip.updated)+'</span>';
document.getElementById('updated').textContent='Updated '+D.trip.updated+' · weather: Open-Meteo · flights: Google Flights · stays: OpenStreetMap';

function rowHtml(v,i){
  var c=cond(v),sc=num(v.score);
  var bar=v.score>=0
    ?'<div class="rbar-line"><div class="rbar-track"><div class="rbar" style="width:'+Math.max(4,sc)+'%;background:'+(sc>=80?'var(--dry)':(sc>=60?'var(--mixed)':'var(--faint)'))+'"></div></div><span class="rsc">'+sc+'</span></div>'
    :'<div class="rbar-line"><span class="rsc dim">no data yet</span></div>';
  var tc=v.listTemp==null?null:(v.listTemp<=20?'var(--dry)':(v.listTemp<=27?'var(--mixed)':'var(--wet)'));
  var info='<span class="rinfo">'+(tc?'<b style="color:'+tc+'">'+num(v.listTemp)+'°C avg</b>'+(v.listInfo?' · ':''):'')+esc(v.listInfo||'')+'</span>';
  return '<button class="row" data-i="'+i+'" onclick="sel('+i+')">'
    +'<span class="rnum">'+num(v.rank)+'</span>'
    +'<span class="rname">'+esc(v.flag)+' '+esc(v.shortName)+'</span>'
    +'<span class="rsub">'+esc(v.country)+(v.rock?' · '+esc(v.rock):'')+' · <b style="color:'+c[1]+';font-weight:600">'+c[0].toLowerCase()+'</b></span>'
    +info+bar+'</button>';
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
  for(var i=6;i>=2;i--){
    var r=38+(i-1)*20,pts=[];
    for(q=0;q<P;q++){
      var a2=q/P*6.2832,rr=r*(1+0.2*noise[q]);
      pts.push([cx+Math.cos(a2)*rr*1.28,cy+Math.sin(a2)*rr]);
    }
    rings+='<path d="'+ringPath(pts)+'" fill="none" stroke="'+c[1]+'" stroke-opacity="'+(0.58-i*0.06).toFixed(2)+'" stroke-width="1.1"/>';
  }
  // summit disc: a donut whose segments are the score's weather/travel/fit
  // contributions (cake-chart breakdown lives here, not in a separate section)
  rings+='<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="46" fill="var(--card)" stroke="'+c[1]+'" stroke-opacity=".9" stroke-width="1.8"/>';
  return '<svg class="topo" viewBox="0 0 '+W+' '+H+'"><g class="rings">'+rings+'</g></svg>';
}


function bandHtml(v){
  var c=cond(v);
  var img=safeUrl(v.hero);
  var bg=img?'background:linear-gradient(90deg,rgba(20,22,26,.94) 22%,rgba(20,22,26,.55)),url('+img+') center/cover no-repeat':'background:'+c[2];
  return '<header class="band" style="'+bg+'">'
    +'<div class="band-body">'
    +'<div class="eyebrow">No.'+num(v.rank)+' of '+V.length+' · '+esc(v.flag)+' '+esc(v.country)+'</div>'
    +'<h1 class="vname">'+esc(v.shortName)+'</h1>'
    +'<div class="vmeta">'+esc(v.style||'')+'</div></div>'
    +(v.breakdown?'<div id="brkChart" class="brkchart hdr"></div>':'')
    +'</header>';
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
  if(v.wx.rain!=null)bits.push(esc(D.trip.periodLbl)+' here typically has <b>'+num(v.wx.rain)+'% wet days</b> with highs of <b>'+num(v.wx.tmax)+'°C</b> (2021–2024 average)');
  if(v.wx.live&&v.wx.liveRain!=null)bits.push('the live forecast for your dates shows <b>'+num(v.wx.liveRain)+'% max rain chance</b>');
  if(v.seasonal)bits.push('the long-range outlook (model reach ~45 days) currently reads <b>'+num(v.seasonal.rain)+'% wet days</b> at <b>'+num(v.seasonal.tmax)+'°C</b>');
  var note=v.score>=0
    ?'<p class="score-note">Why score <b>'+num(v.score)+'/100</b>: ranked on '+esc(v.basis||'weather')+' — '+bits.join('; ')+'.</p>'
    :'<p class="score-note">No weather data yet for this area, so it is unranked.</p>';
  return '<div class="sec"><div class="eyebrow">Why go</div>'+why+'</div>';
}

function takeaway(v){
  var t=(v.series||[]).filter(function(s){return s.trip;});
  if(!t.length)return '';
  var ov=t.map(function(s){return s.fc||s.out||null;});
  var haveOv=ov.every(function(x){return x;});
  var src=t.some(function(s){return s.fc;})?'Live forecast for your dates ('+esc(D.trip.dates)+')':'Long-range outlook for your dates ('+esc(D.trip.dates)+')';
  var rows=haveOv?ov:t;
  var wet=rows.filter(function(s){return num(s.precip)>=3;}).length;
  var avgT=Math.round(rows.reduce(function(a,s){return a+num(s.tmax);},0)/rows.length);
  var winds=t.map(function(s){return num((s.fc&&s.fc.wind!=null)?s.fc.wind:s.wind);});
  var maxW=Math.max.apply(null,winds);
  var head=haveOv?src+': ':'Typical '+esc(D.trip.periodLbl)+' here: ';
  var wetTxt=wet===0?'<b>rain unlikely</b>':'<b>'+wet+' of '+rows.length+' days wet</b>';
  var extra='';
  if(v.wx&&v.wx.live){
    if(v.wx.friction)extra+=' · rock <b>'+esc(v.wx.friction)+'</b>';
    if(v.wx.gustMax!=null)extra+=' · gusts to <b>'+num(v.wx.gustMax)+' km/h</b>';
    if(v.wx.amDry&&v.wx.amDry[1])extra+=' · <b>'+num(v.wx.amDry[0])+'/'+num(v.wx.amDry[1])+'</b> dry mornings';
  }
  return '<p class="wx-take">'+head+wetTxt+' · highs around <b>'+avgT+'°C</b> · wind up to <b>'+maxW+' km/h</b>'+extra+'.</p>';
}

function condStrip(v){
  // Icon chips for the live-forecast-only climbing signals — always visible (unlike the
  // chart's hover tooltips, which don't exist on touch screens).
  if(!v.wx||!v.wx.live)return '';
  var w=v.wx,chips=[];
  if(w.friction){
    var fc=w.friction==='greasy'?'bad':w.friction==='humid'?'warn':'good';
    chips.push('<span class="cc '+fc+'"><span class="ci">🪨</span>rock <b>'+esc(w.friction)+'</b></span>');
  }
  if(w.gustMax!=null){
    var gc=w.gustMax>=55?'bad':w.gustMax>=40?'warn':'good';
    chips.push('<span class="cc '+gc+'"><span class="ci">🌬️</span>gusts <b>'+num(w.gustMax)+' km/h</b></span>');
  }
  if(w.amDry&&w.amDry[1]){
    var dc=w.amDry[0]===w.amDry[1]?'good':(w.amDry[0]===0?'bad':'warn');
    chips.push('<span class="cc '+dc+'"><span class="ci">🌅</span><b>'+num(w.amDry[0])+'/'+num(w.amDry[1])+'</b> dry mornings</span>');
  }
  return chips.length?'<div class="wx-cond">'+chips.join('')+'</div>':'';
}

function wxHtml(v){
  var s=v.series||[];
  if(!s.length)return '<div class="sec"><div class="eyebrow">Weather</div><div class="empty">No weather data for this area yet.</div></div>';
  return '<div class="sec"><div class="sec-hd"><div class="eyebrow">Weather · '+esc(D.trip.dates)+'</div>'
    +(safeUrl(v.weather)?'<a class="lk sm" target="_blank" rel="noopener" href="'+safeUrl(v.weather)+'">Full forecast on Windy ↗</a>':'')+'</div>'
    +takeaway(v)
    +'<div id="wxChart" class="wxchart"></div>'
    +(v.seasonal?'<div class="outlook">Long-range outlook (model reach ~45 days, experimental '+num(v.seasonal.members)+'-member ensemble) supplies the bright series until the live forecast lands ~8 July.</div>':'')
    +'</div>';
}

var _charts=[];
function _clearCharts(){_charts.forEach(function(c){try{c.dispose();}catch(e){}});_charts=[];}
window.addEventListener('resize',function(){_charts.forEach(function(c){c.resize();});});

function renderWx(v){
  var el=document.getElementById('wxChart');
  if(!el)return;
  if(typeof echarts==='undefined'){el.innerHTML='<div class="empty">Charts need cdn.jsdelivr.net.</div>';return;}
  var s2=v.series||[];if(!s2.length)return;
  // phones: drop the long caption + per-day wind sub-labels, shrink everything —
  // the same info lives in the takeaway line, condition chips and tap-tooltips.
  var narrow=el.clientWidth<620;
  var ARR=['↓','↙','←','↖','↑','↗','→','↘'];
  function warr(d){return d==null?'':ARR[Math.round((((num(d)%360)+360)%360)/45)%8];}
  var days=s2.map(function(d){if(narrow)return d.lbl.slice(0,2)+' '+d.day;
    var w=(d.fc&&d.fc.wind!=null)?d.fc.wind:d.wind;
    var dd=(d.fc&&d.fc.dir!=null)?d.fc.dir:d.dir;return d.lbl+' '+d.day+'\n'+w+'km/h'+warr(dd);});
  var anyFc=s2.some(function(d){return d.fc;}),ov=anyFc?'Forecast':'Outlook';
  var f=-1,l=-1;s2.forEach(function(d,i2){if(d.trip){if(f<0)f=i2;l=i2;}});
  var mark={silent:true,itemStyle:{color:'rgba(87,166,100,0.09)'},data:[[{xAxis:f},{xAxis:l}]]};
  var c=echarts.init(el,null,{renderer:'svg'});
  c.setOption({backgroundColor:'transparent',textStyle:{fontFamily:'IBM Plex Mono, monospace'},
    title:{show:!narrow,text:'Lines = daily high °C (dashed grey = typical, orange = '+ov.toLowerCase()+') · bars = rain mm · under each day: wind km/h + direction',
      top:0,left:0,textStyle:{color:'#6E7069',fontSize:10.5,fontWeight:400}},
    legend:{top:narrow?0:18,textStyle:{color:'#A0A19A',fontSize:narrow?9.5:11},itemWidth:narrow?10:14,itemGap:narrow?7:10},
    tooltip:{trigger:'axis',backgroundColor:'#20242B',borderColor:'#353A44',textStyle:{color:'#E9E7E1',fontSize:12},confine:true,
      formatter:function(ps){if(!ps.length)return '';var i2=ps[0].dataIndex,d=s2[i2],o=d.fc||d.out;
        var h='<b>'+d.lbl+' '+d.day+(d.trip?' · TRIP DAY':'')+'</b><br>typical: '+d.tmax+'°C · '+d.precip+'mm · wind '+d.wind+' km/h';
        if(o)h+='<br><b>'+(d.fc?'forecast':'outlook')+': '+o.tmax+'°C · '+o.precip+'mm</b>';
        if(d.fc){if(d.fc.wind!=null)h+='<br>wind '+d.fc.wind+' km/h '+(d.fc.dir!=null?'from '+compass(d.fc.dir)+' '+warr(d.fc.dir):'')+(d.fc.gust!=null?' · gusts '+d.fc.gust:'');
          if(d.fc.friction)h+='<br>friction: '+esc(d.fc.friction)+(d.fc.dew!=null?' (dew '+d.fc.dew+'°C)':'');
          if(d.fc.sunFrac!=null)h+=' · sun '+Math.round(d.fc.sunFrac*100)+'%';}
        return h;}},
    grid:{left:narrow?34:46,right:narrow?34:46,top:narrow?28:46,bottom:narrow?30:44},
    xAxis:{type:'category',data:days,axisLabel:{fontSize:narrow?8.5:10.5,lineHeight:narrow?12:15,interval:narrow?1:0,color:function(v2,idx){var d=s2[idx];var w=(d.fc&&d.fc.wind!=null)?d.fc.wind:d.wind;return w>=25?'#B98A2E':'#A0A19A';}},axisLine:{lineStyle:{color:'#353A44'}},axisTick:{show:false}},
    yAxis:[{type:'value',name:narrow?'':'high °C',nameTextStyle:{color:'#6E7069'},axisLabel:{color:'#6E7069',fontSize:narrow?9:10},splitLine:{lineStyle:{color:'#2A2E36'}}},
           {type:'value',name:narrow?'':'rain mm',nameTextStyle:{color:'#6E7069'},axisLabel:{color:'#6E7069',fontSize:narrow?9:10},splitLine:{show:false}}],
    series:[
      {name:'Typical high °C',type:'line',yAxisIndex:0,data:s2.map(function(d){return d.tmax;}),symbolSize:narrow?4:5,
       lineStyle:{type:'dashed',color:'#6E7069',width:1.5},itemStyle:{color:'#6E7069'},markArea:mark},
      {name:ov+' high °C',type:'line',yAxisIndex:0,data:s2.map(function(d){var o=d.fc||d.out;return o?o.tmax:null;}),symbolSize:narrow?5:7,
       lineStyle:{color:'#d95926',width:narrow?2:2.5},itemStyle:{color:'#d95926'},
       label:{show:true,position:'top',color:'#E9E7E1',fontSize:narrow?9:10,fontWeight:600,
         formatter:function(p){return (narrow&&p.dataIndex%2===1)?'':num(p.value)+'°';}}},
      {name:'Typical rain mm',type:'bar',yAxisIndex:1,data:s2.map(function(d){return d.precip;}),barGap:'12%',
       itemStyle:{color:'rgba(57,135,229,0.32)',borderRadius:[3,3,0,0]}},
      {name:ov+' rain mm',type:'bar',yAxisIndex:1,data:s2.map(function(d){var o=d.fc||d.out;return o?o.precip:null;}),
       itemStyle:{color:'#3987e5',borderRadius:[3,3,0,0]}}
    ]});
  _charts.push(c);
}

// The weighted ring: the ranking function drawn honestly, two levels deep.
// Inner ring = the composite itself — one arc per factor, arc length = weight,
// lit length = score, so the lit fraction of the whole circle IS the trip
// score. Outer tier = each factor's own function: travel/fit really are
// equal-weight means in the scorer, so equal sub-arcs are honest geometry;
// weather's sub-arcs are signal checks (lit = how little that signal costs),
// dashed while a signal is pending (wind/friction before the live forecast).
// Hovering (or tapping) a factor's wedge shows its formula card and dims the
// other wedges; the card is pointer-events:none so it can never steal the
// hover and flicker. Pure SVG — ECharts stays only for the weather chart.
function renderBrk(v){
  var el=document.getElementById('brkChart');
  if(!el)return;
  var b=v.breakdown;
  if(!b){el.innerHTML='';return;}
  var W=b.weights||{weather:55,travel:25,fit:20};
  var FACT=[
    {key:'weather',name:'WEATHER',val:num(b.weather),wt:W.weather,color:'#3987e5',fn:'100 −rain −heat −wind −grease'},
    {key:'travel',name:'TRAVEL',val:num(b.travel),wt:W.travel,color:'#d95926',fn:'(flights + time + stay) / 3'},
    {key:'fit',name:'VENUE FIT',val:num(b.fit),wt:W.fit,color:'#57A664',fn:'(vol + diff + trip + routes) / 4'}
  ];
  var notes={weather:b.weather_note,travel:b.travel_note,fit:b.fit_note};
  var CX=145,CY=128,R=76,SW=15,RO=97,SWO=5,GAP=2.5,SUBGAP=1.8;
  function f1(n){return n.toFixed(1);}
  function pt(a,rr){var t=a*Math.PI/180;return [CX+rr*Math.sin(t),CY-rr*Math.cos(t)];}
  function arc(a0,a1,rr){
    var p0=pt(a0,rr),p1=pt(a1,rr),large=(a1-a0)>180?1:0;
    return 'M'+f1(p0[0])+' '+f1(p0[1])+' A'+rr+' '+rr+' 0 '+large+' 1 '+f1(p1[0])+' '+f1(p1[1]);
  }
  var s='',a=0;
  FACT.forEach(function(fc,fi){
    var span=360*fc.wt/100,fill=span*fc.val/100;
    var subs=(b.sub&&b.sub[fc.key])||null;
    s+='<g class="fgrp" data-f="'+fi+'">';
    // invisible fat arc = one continuous hover target for the whole wedge
    s+='<path d="'+arc(a+GAP/2,a+span-GAP/2,(R+RO)/2)+'" fill="none" stroke="rgba(0,0,0,0)" stroke-width="'+(RO-R+SW+SWO)+'"/>';
    s+='<path d="'+arc(a+GAP/2,a+span-GAP/2,R)+'" fill="none" stroke="'+fc.color+'" stroke-opacity=".16" stroke-width="'+SW+'"/>';
    s+='<path d="'+arc(a+GAP/2,Math.max(a+GAP/2+1,a+Math.min(fill,span-GAP/2)),R)+'" fill="none" stroke="'+fc.color+'" stroke-width="'+SW+'">'
      +'<title>'+fc.name+' '+fc.val+'/100 × '+fc.wt+'% = +'+f1(fc.val*fc.wt/100)+' pts</title></path>';
    if(subs){
      var n=subs.length,subspan=span/n;
      subs.forEach(function(sb,j){
        var s0=a+j*subspan+SUBGAP/2,s1=a+(j+1)*subspan-SUBGAP/2;
        if(sb.v==null){
          s+='<path d="'+arc(s0,s1,RO)+'" fill="none" stroke="#6E7069" stroke-opacity=".45" stroke-width="'+SWO+'" stroke-dasharray="2.5 3.5">'
            +'<title>'+esc(sb.n)+' — pending: '+esc(sb.d||'')+'</title></path>';
        }else{
          var sfill=s0+(s1-s0)*num(sb.v)/100;
          s+='<path d="'+arc(s0,s1,RO)+'" fill="none" stroke="'+fc.color+'" stroke-opacity=".15" stroke-width="'+SWO+'"/>';
          s+='<path d="'+arc(s0,Math.max(s0+.8,sfill),RO)+'" fill="none" stroke="'+fc.color+'" stroke-opacity=".85" stroke-width="'+SWO+'">'
            +'<title>'+esc(sb.n)+' '+num(sb.v)+'/100 — '+esc(sb.d||'')+'</title></path>';
        }
      });
    }
    var mid=a+span/2,lp=pt(mid,RO+13);
    var sn=Math.sin(mid*Math.PI/180),anchor=Math.abs(sn)<.35?'middle':(sn>0?'start':'end');
    s+='<text x="'+f1(lp[0])+'" y="'+f1(lp[1]+3)+'" text-anchor="'+anchor+'" font-family="IBM Plex Mono, monospace" font-size="8.5" font-weight="600" fill="#6E7069">'+fc.wt+'%</text>';
    s+='</g>';
    a+=span;
  });
  function trim1(x){var t=x.toFixed(1);return t.slice(-2)==='.0'?t.slice(0,-2):t;}
  s+='<text x="'+CX+'" y="'+(CY-8)+'" text-anchor="middle" font-family="Bricolage Grotesque, sans-serif" font-size="30" font-weight="800" fill="#E9E7E1">'+num(v.score)+'</text>'
    +'<text x="'+CX+'" y="'+(CY+8)+'" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="7" letter-spacing=".1em" fill="#A0A19A">TRIP SCORE /100</text>'
    +'<text x="'+CX+'" y="'+(CY+24)+'" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="8.5">'
    +FACT.map(function(fc,i){return (i?'<tspan fill="#6E7069">+</tspan>':'')+'<tspan fill="'+fc.color+'">'+trim1(fc.val*fc.wt/100)+'</tspan>';}).join('')+'</text>'
    +'<text x="'+CX+'" y="'+(CY+41)+'" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="6.5" letter-spacing=".08em" fill="#6E7069">'
    +FACT.map(function(fc){return '<tspan fill="'+fc.color+'">■</tspan>';}).join(' ')+' HOVER OR TAP FOR THE MATHS</text>';
  function subLine(subs){
    return subs.map(function(sb){
      if(sb.v==null)return '<span class="bp-pend">'+esc(sb.n.toLowerCase())+': '+esc(sb.d||'—')+'</span>';
      var c=sb.v>=80?'var(--dry)':(sb.v>=55?'var(--mixed)':'var(--wet)');
      return esc(sb.n.toLowerCase())+' <b style="color:'+c+'">'+num(sb.v)+'</b>';
    }).join(' · ');
  }
  var panels=FACT.map(function(fc,fi){
    var subs=(b.sub&&b.sub[fc.key])||null;
    var body=subs?fc.fn+'<br>'+subLine(subs):esc(notes[fc.key]||'');
    return '<div class="brkpanel" id="bp'+fi+'"><div class="bp-hd"><span class="bp-dot" style="background:'+fc.color+'"></span>'
      +'<span class="bp-name">'+fc.name+' <span class="bp-wt">×.'+fc.wt+'</span></span>'
      +'<span class="bp-score" style="color:'+fc.color+'">'+fc.val+'</span></div>'
      +'<div class="bp-fn">'+body+'</div></div>';
  }).join('');
  el.innerHTML='<svg viewBox="0 0 290 256" role="img" aria-label="Trip score '+num(v.score)+' of 100: weather '+num(b.weather)+', travel '+num(b.travel)+', venue fit '+num(b.fit)+'">'+s+'</svg>'+panels;
  var grps=Array.prototype.slice.call(el.querySelectorAll('.fgrp'));
  function showF(fi){
    grps.forEach(function(g){g.classList.toggle('dim',+g.getAttribute('data-f')!==fi);});
    FACT.forEach(function(_,i){
      var p=document.getElementById('bp'+i);
      if(p)p.classList.toggle('on',i===fi);
    });
  }
  function clearF(){
    grps.forEach(function(g){g.classList.remove('dim');});
    FACT.forEach(function(_,i){var p=document.getElementById('bp'+i);if(p)p.classList.remove('on');});
  }
  grps.forEach(function(g){
    var fi=+g.getAttribute('data-f');
    g.addEventListener('mouseenter',function(){showF(fi);});
    g.addEventListener('mouseleave',clearF);
    g.addEventListener('click',function(e){showF(fi);e.stopPropagation();});
  });
  // renderBrk reruns on every venue switch — keep ONE document listener that
  // always points at the current ring's clear function (tap-away on touch)
  window._bpClear=clearF;
}
document.addEventListener('click',function(){if(window._bpClear)window._bpClear();});

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
      inner='<div class="fprice">£'+num(opts[0].price)+' <span>return · per person'+'</span></div>'+(f.cached?'<div class="stale">⚠ last-checked price — verify before booking</div>':'')+rows
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
  var name=safeUrl(c.url)
    ?'<a class="lk" target="_blank" rel="noopener" href="'+safeUrl(c.url)+'">'+esc(c.cliff)+' ↗</a>'
    :esc(c.cliff);
  return '<div class="climb"><div class="cthumb">'+(img?'<img src="'+img+'" alt="" loading="lazy" onerror="this.parentElement.textContent=\'🏔\'">':'🏔')+'</div>'
    +'<div style="min-width:0;flex:1"><div class="cname">'+name+'</div><div class="croute">'+esc(c.route)+'</div>'+ph+'</div>'
    +'<div class="cgrade">'+esc(c.tradGrade||c.grade||'')+'</div></div>';
}

function breakdownHtml(v){
  var b=v.breakdown;
  if(!b)return '';
  var W=b.weights||{weather:55,travel:25,fit:20};
  function row(lbl,val,wt,color,note){
    return '<div class="brk-row"><span class="brk-lbl">'+lbl+'</span>'
      +'<div class="brk-track"><div class="brk-fill" style="width:'+Math.max(2,num(val))+'%;background:'+color+'"></div></div>'
      +'<span class="brk-val">'+num(val)+'/100 × '+wt+'%</span></div>'
      +(note?'<div class="brk-note">'+esc(note)+'</div>':'');
  }
  return '<div class="sec"><div class="eyebrow">Score breakdown · '+num(v.score)+'/100</div><div class="brk">'
    +row('Weather',b.weather,W.weather,'var(--rain)',b.weather_note)
    +row('Travel',b.travel,W.travel,'var(--temp)',b.travel_note)
    +row('Venue fit',b.fit,W.fit,'var(--dry)',b.fit_note)
    +'<div class="brk-total"><span>'+num(b.weather)+' × .'+W.weather+' &nbsp;+&nbsp; '+num(b.travel)+' × .'+W.travel+' &nbsp;+&nbsp; '+num(b.fit)+' × .'+W.fit+'</span><b>= '+num(v.score)+'/100</b></div>'
    +'</div></div>';
}

var TAGT={cond:'Typical share of wet days for your trip dates',vol:'Volume of multi-pitch climbing — from your sheet',diff:'Difficulty spread — from your sheet',time:'Rough travel time from the UK — from your sheet',trip:'Minimum sensible trip length — from your sheet',height:'Tallest route nearby on multi-pitch.com',rock:'Rock type',grade:'Trad grade range of nearby multi-pitch.com routes',routes:'Routes indexed on multi-pitch.com within 60 km',hazard:'Route character / hazard flag from multi-pitch.com route data',appr:'Approach character from route walk-in times',aspect:'Which way the crag faces — shifts felt temperature in sun',auto:'Venue generated from a row in your spreadsheet'};
function tagsHtml(v){
  if(!v.tags||!v.tags.length)return '';
  return '<div class="sec"><div class="eyebrow">Area character</div><div class="tagleg">colours: blue/violet = your sheet · green = multi-pitch.com · amber = hazards · grey = rock/approach — hover any tag for its meaning</div><div class="tags">'
    +v.tags.map(function(t){return '<span class="tag tag-'+esc(t.k)+'" title="'+esc(TAGT[t.k]||'')+'">'+esc(t.t)+'</span>';}).join('')+'</div></div>';
}

function stayHtml(s){
  var links=[];
  if(safeUrl(s.web))links.push('<a class="btn ghost" target="_blank" rel="noopener" href="'+safeUrl(s.web)+'">Website ↗</a>');
  if(safeUrl(s.airbnb))links.push('<a class="btn ghost" target="_blank" rel="noopener" href="'+safeUrl(s.airbnb)+'">Airbnb search ↗</a>');
  if(safeUrl(s.book))links.push('<a class="btn ghost" target="_blank" rel="noopener" href="'+safeUrl(s.book)+'">Booking.com search ↗</a>');
  if(safeUrl(s.hotels))links.push('<a class="btn ghost" target="_blank" rel="noopener" href="'+safeUrl(s.hotels)+'">Hotels.com search ↗</a>');
  if(safeUrl(s.maps))links.push('<a class="btn ghost" target="_blank" rel="noopener" href="'+safeUrl(s.maps)+'">Map ↗</a>');
  return '<div class="hcard"><div class="hname">'+esc(s.name)+'</div>'
    +'<div class="htype">'+esc(s.type)+' · '+num(s.dist)+' km from the crag</div>'
    +'<div class="hprice">~£'+num(s.est)+' <span>/ night · 2 people · est.</span></div>'
    +(s.note?'<div class="htags"><span class="htag warn">⛺ '+esc(s.note)+'</span></div>':'')
    +(links.length?'<div class="stay-links">'+links.join('')+'</div>':'')
    +'</div>';
}

// One column per kind of stay — house/apt first (Michel's preference), then
// camping, then hotels. Each column carries its own search fallback.
var STAY_COLS=[
  ['house','🏠','Houses & apartments','self-catered, Airbnb-style','airbnb','Airbnb search'],
  ['camp','⛺','Camping','bring your own tent, mats & cooking kit','camps','campsites map'],
  ['hotel','🏨','Hotels & hostels','one room, 2 adults','booking','Booking.com search']];
function staysHtml(v){
  var st=v.stays||{},q=st.search||{},radius=st.radius?num(st.radius):15;
  var list=st.list||[];
  var cols=STAY_COLS.map(function(cdef){
    var items=list.filter(function(s){return s.cat===cdef[0];});
    var inner=items.length?items.map(stayHtml).join('')
      :'<div class="stay-none">none mapped within '+radius+' km'
        +(safeUrl(q[cdef[4]])?' — try the <a class="lk" target="_blank" rel="noopener" href="'+safeUrl(q[cdef[4]])+'">'+esc(cdef[5])+' ↗</a>':'')+'</div>';
    return '<div class="stay-col"><div class="stay-col-hd">'+cdef[1]+' '+esc(cdef[2])+'</div>'
      +'<div class="stay-col-sub">'+esc(cdef[3])+'</div>'+inner+'</div>';
  }).join('');
  var search=[
    safeUrl(q.map)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(q.map)+'">🗺 All stays on one map ↗</a>':'',
    safeUrl(q.airbnb)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(q.airbnb)+'">🏠 Airbnb ↗</a>':'',
    safeUrl(q.booking)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(q.booking)+'">🏨 Booking.com ↗</a>':'',
    safeUrl(q.hotels)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(q.hotels)+'">🛏 Hotels.com ↗</a>':'',
    safeUrl(q.camps)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(q.camps)+'">⛺ Campsites ↗</a>':''
  ].join('');
  var src=safeUrl(q.map)
    ?'<a class="sample" target="_blank" rel="noopener" href="'+safeUrl(q.map)+'" title="Every stay pin-pointed on an OpenStreetMap map">OpenStreetMap ↗</a>'
    :'<span class="sample">OpenStreetMap</span>';
  var guide=v.guide?'<div class="guide"><div style="font-size:22px">📗</div><div style="flex:1"><div class="hname">'+esc(v.guide.title)+'</div><div class="htype" style="margin-bottom:0">'+esc(v.guide.pub)+' · '+esc(v.guide.price)+'</div></div>'
    +(safeUrl(v.guide.url)?'<a class="lk" style="font-size:12px;flex-shrink:0" target="_blank" rel="noopener" href="'+safeUrl(v.guide.url)+'">Amazon ↗</a>':'')+'</div>':'';
  return '<div class="sec"><div class="eyebrow">Stay near the crag · 2 adults · '+esc(D.trip.dates)+' '+src+'</div>'
    +'<div class="tagleg">named places within '+radius+' km · search links pre-filled with your dates + 2 adults · £ = typical price for that type of stay, not a live quote</div>'
    +(search?'<div class="stay-search">'+search+'</div>':'')
    +'<div class="stay-cols">'+cols+'</div>'+guide+'</div>';
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
  return bandHtml(v)
    +tagsHtml(v)
    +wxHtml(v)
    +hl
    +verdictHtml(v)
    +'<div class="sec"><div class="eyebrow">Getting there</div><div class="fgrid">'
      +flightCard('Michel','London',v.flights&&v.flights.michel)
      +flightCard('Dan','Belfast / Dublin',v.flights&&v.flights.dan)+'</div></div>'
    +((climbs)?'<div class="sec"><div class="sec-hd"><div class="eyebrow">'+(hl?'More climbs':'Climbs')+' nearby · from multi-pitch.com</div>'
      +(safeUrl(v.mpMap)?'<a class="lk sm" target="_blank" rel="noopener" href="'+safeUrl(v.mpMap)+'">Browse the map ↗</a>':'')+'</div>'+climbs+'</div>':'')
    +staysHtml(v)
    +'<div class="sec" style="display:flex;gap:8px;flex-wrap:wrap">'
      +(safeUrl(v.maps)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(v.maps)+'">📍 Google Maps</a>':'')
      +(safeUrl(v.weather)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(v.weather)+'">Detailed forecast — Windy ↗</a>':'')
      +(safeUrl(v.mpMap)?'<a class="tl" target="_blank" rel="noopener" href="'+safeUrl(v.mpMap)+'">multi-pitch.com map ↗</a>':'')
    +'</div>';
}

function help(on){document.getElementById('hovl').style.display=on?'flex':'none';}
document.addEventListener('keydown',function(e){if(e.key==='Escape')help(0);});
var _booted=false,_cur=0;
function slugify(n){return String(n).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');}
function sel(i){
  _cur=i;
  var rows=document.querySelectorAll('.row');
  for(var k=0;k<rows.length;k++)rows[k].classList.toggle('active',+rows[k].getAttribute('data-i')===i);
  document.getElementById('detail').innerHTML=detailHtml(V[i]);
  _clearCharts();renderBrk(V[i]);renderWx(V[i]);
  if(_booted)try{history.replaceState(null,'','#'+slugify(V[i].shortName));}catch(e){}
  if(_booted&&window.innerWidth<900)document.getElementById('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
var _h=location.hash.replace('#',''),_i0=0;
if(_h)V.forEach(function(v,i){if(slugify(v.shortName)===_h)_i0=i;});
sel(_i0);
_booted=true;
window.addEventListener('hashchange',function(){var h=location.hash.replace('#','');V.forEach(function(v,i){if(slugify(v.shortName)===h&&i!==_cur)sel(i);});});
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
        "periodLbl": PERIOD_LBL,
        "repoUrl": REPO_URL,
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
              f"date options: {COMBO_LABELS}. Use the book links to adjust. "
              f"Stays: OpenStreetMap lodging within {STAY_RADIUS_KM} km per venue (houses, camping, hotels "
              f"for {STAY_ADULTS} adults) on the dashboard's per-venue cards. Rendered dashboard: "
              "https://uncinimichel.github.io/climbing-agent/_"]
    return "\n".join(lines) + "\n"


def main():
    global MP_CLIMBS
    MP_CLIMBS = load_mp_climbs()
    print(f"multi-pitch climbs loaded: {len(MP_CLIMBS)}")
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    results = [evaluate(v) for v in VENUES]
    for r in results:                 # composite = weather + travel + venue fit
        apply_composite(r)
    ranked = rank(results)
    attach_flights(ranked)            # price the provisional top-N (quota-capped)
    for r in ranked[:TOP_N_FLIGHTS]:  # refine those with real flight prices…
        apply_composite(r)
    ranked = rank(results)            # …then price any NEWCOMERS to the top-N
    attach_flights(ranked)            # (already-priced venues are skipped)
    for r in ranked[:TOP_N_FLIGHTS]:
        apply_composite(r)
    ranked = rank(results)            # …and settle the final order

    in_window = any(r.get("fc") and r["fc"].get("in_window") for r in ranked)
    horizon = next((r["fc"]["horizon"] for r in ranked if r.get("fc")), "?")
    if in_window:
        banner = ("ok", "✅ Trip dates are within the 16-day forecast — venues ranked on the <b>actual trip-window forecast</b>.")
    else:
        days_out = (TARGET_START - now.date()).days
        has_sea = any(r.get("seasonal") for r in ranked)
        sea_txt = (" blended with a <b>long-range outlook</b> (model reach ~45 days; shown per venue)" if has_sea else "")
        banner = ("", f"📅 Trip is {days_out} days out — beyond the 16-day live forecast (reaches {horizon}). "
                      f"Ranked on <b>typical {PERIOD_LBL} weather</b> ({CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]}){sea_txt}. "
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

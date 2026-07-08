"""HTML/CSS/JS rendering — moved from update_report.py's build_data/build_html/
render_page/venue_payload/venue_page/write_venue_pages/write_seo_files/build_md
and the PAGE_HEAD/PAGE_BODY/PAGE_JS templates + tag-taxonomy rendering.

The PAGE_HEAD/PAGE_BODY/PAGE_JS strings are unchanged from update_report.py —
PAGE_JS in particular is pure client-side JS operating on the injected
`window.DATA` blob, with no server-side globals baked in, so it moved
verbatim. The Python-side functions are parameterized on TripContext plus a
few small reference-data objects (TagSpec, guidebooks, extra_climbing, the
multi-pitch.com climb list) instead of module-level globals.
"""
import json
import math
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import date

from .climbs import SITE_URL, grade_range, nearby_climb_cards, nearby_climbs, venue_is_tidal
from .flights import skyscanner_url
from .stays import STAY_ADULTS, STAY_RADIUS_KM
from .weather import ASPECT_ADJ

MP_MAP_URL = "https://multi-pitch.com/map/"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1N4Xs-aSGFc8-ibysqpdCvQIfMH4Rjx4n5WQnqITGPC8/edit"
REPO_URL = "https://github.com/uncinimichel/climbing-agent"
PAGES_BASE = "https://uncinimichel.github.io/climbing-agent/"   # canonical URL for SEO tags + sitemap
MP_ICONS = SITE_URL + "img/icons/weather/"

WMO = {
    0: "☀️ clear", 1: "🌤️ mostly clear", 2: "⛅ partly cloudy", 3: "☁️ overcast",
    45: "🌫️ fog", 48: "🌫️ rime fog", 51: "🌦️ drizzle", 53: "🌦️ drizzle",
    55: "🌧️ heavy drizzle", 61: "🌧️ light rain", 63: "🌧️ rain", 65: "🌧️ heavy rain",
    71: "🌨️ snow", 73: "🌨️ snow", 75: "❄️ heavy snow", 80: "🌦️ showers",
    81: "🌦️ showers", 82: "⛈️ violent showers", 95: "⛈️ storm", 96: "⛈️ storm", 99: "⛈️ storm",
}

FLAGS = {
    "Northern Ireland": "☘️", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Italy": "🇮🇹", "Austria": "🇦🇹", "Spain": "🇪🇸", "Croatia": "🇭🇷", "France": "🇫🇷", "Ireland": "🇮🇪",
    "Norway": "🇳🇴", "Germany": "🇩🇪", "Belgium": "🇧🇪", "Bulgaria": "🇧🇬", "Greece": "🇬🇷",
    "Turkey": "🇹🇷", "Slovakia": "🇸🇰", "Slovenia": "🇸🇮", "Portugal": "🇵🇹", "Switzerland": "🇨🇭",
    "Morocco": "🇲🇦", "Jordan": "🇯🇴", "Jodan": "🇯🇴", "Namibia": "🇳🇦", "Saudi Arabia": "🇸🇦",
    # the sheet's own spellings
    "Slovinia": "🇸🇮", "Swizzerland": "🇨🇭",
}

_JUL_UTC_OFF = {
    "england": 1, "scotland": 1, "wales": 1, "northern ireland": 1, "ireland": 1,
    "portugal": 1, "morocco": 1,
    "austria": 2, "belgium": 2, "croatia": 2, "czechia": 2, "france": 2,
    "germany": 2, "italy": 2, "namibia": 2, "netherlands": 2, "norway": 2,
    "slovakia": 2, "slovenia": 2, "slovinia": 2, "spain": 2,
    "switzerland": 2, "swizzerland": 2,
    "bulgaria": 3, "greece": 3, "jordan": 3, "saudi arabia": 3, "turkey": 3,
}


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


def flag(country):
    return FLAGS.get(country, "📍")


def weather_url(v):
    """Detailed forecast for the venue (Windy, by coordinates)."""
    return f"https://www.windy.com/?{v['lat']},{v['lon']},9"


def maps_url(v):
    return f"https://www.google.com/maps/search/?api=1&query={v['lat']},{v['lon']}"


def wx_band(rain_pct):
    """Weather → dry/mixed/wet band (same thresholds as the seasonal-outlook copy)."""
    if rain_pct is None:
        return ("Mixed", "mix")
    return ("Dry", "go") if rain_pct <= 30 else ("Mixed", "mix") if rain_pct <= 55 else ("Wet", "wet")


def arc_color(band_cls):
    return {"go": "#C4FF5C", "mix": "#C8A44A", "wet": "#B94438"}.get(band_cls, "#C8A44A")


def short_name(name):
    return name.split("(")[0].split(",")[0].strip()


def _slug(name):
    """Mirror of the client-side slugify() so static venue URLs and the SPA's
    #hash routes agree on names."""
    t = unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", t))


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _sky_label(e):
    """Text version of the tile icon's cloud logic, for the static tables."""
    o = e.get("fc") or e.get("out") or {}
    mm = o.get("precip", e.get("precip")) or 0
    cc = o.get("cloud", e.get("cloud"))
    if mm >= 2:
        return "rain"
    if cc is None:
        return "sunny" if mm < 0.05 else ("sunny intervals" if mm < 0.5 else "cloudy")
    return "sunny" if cc < 25 else ("sunny intervals" if cc < 60 else "cloudy")


def _sun_times(lat, lon, d):
    """Sunrise/sunset for date d at lat/lon as (rise, set) minutes since UTC
    midnight, via the NOAA approximation (±2 min — plenty for a head-torch
    call). Returns "day"/"night" when the sun never crosses the horizon
    (Lofoten still has the midnight sun in late July)."""
    rad, deg = math.radians, math.degrees
    # 1721425 anchors toordinal() to the integer Julian DAY (noon), which is
    # what this formula's day-count n wants — not the midnight JD (…424.5)
    n = d.toordinal() + 1721425.0 - 2451545.0 + 0.0008
    jstar = n - lon / 360.0
    m = (357.5291 + 0.98560028 * jstar) % 360
    c = 1.9148 * math.sin(rad(m)) + 0.02 * math.sin(rad(2 * m)) + 0.0003 * math.sin(rad(3 * m))
    lam = (m + c + 180 + 102.9372) % 360
    jtransit = 2451545.0 + jstar + 0.0053 * math.sin(rad(m)) - 0.0069 * math.sin(rad(2 * lam))
    sindec = math.sin(rad(lam)) * math.sin(rad(23.4397))
    cosw = ((math.sin(rad(-0.833)) - math.sin(rad(lat)) * sindec)
            / (math.cos(rad(lat)) * math.cos(math.asin(sindec))))
    if cosw < -1:
        return "day"
    if cosw > 1:
        return "night"
    w = deg(math.acos(cosw))

    def mins(j):
        return ((j + 0.5) % 1.0) * 1440.0
    # daylight comes from the hour angle, not set−rise: near the arctic the
    # sun can set after local midnight, so the wrapped clock times would
    # difference to nonsense (Lofoten: rise 01:55, set 00:29 the NEXT day)
    return mins(jtransit - w / 360.0), mins(jtransit + w / 360.0), w / 360.0 * 48.0


def _venue_utc_off(v):
    if "tenerife" in (v.get("name") or "").lower():
        return 1                       # Canaries run an hour behind mainland Spain
    off = _JUL_UTC_OFF.get((v.get("country") or "").strip().lower())
    if off is None:
        off = round((v.get("lon") or 0) / 15)   # solar-time guess for new venues
    return off


def _uv_est(lat, d, cloud_pct):
    """Estimated midday UV index for typical/outlook days, until the live
    forecast supplies the real uv_index_max: clear-sky UVI from solar
    elevation (McKenzie et al. ~12.5·cosZ^2.42 at sea level), knocked down
    up to ~50% under full cloud. ±1–2 UVI — fine for a suncream call, and
    the tooltip labels it 'est.'."""
    doy = d.timetuple().tm_yday
    dec = 23.44 * math.sin(math.radians((284 + doy) / 365.0 * 360.0))
    cosz = math.cos(math.radians(abs(lat - dec)))   # solar zenith at local noon
    if cosz <= 0:
        return 0
    uvi = 12.5 * cosz ** 2.42
    if cloud_pct is not None:
        uvi *= 1.0 - 0.5 * (cloud_pct / 100.0)
    return round(uvi)


def _day_sun(lat, lon, d, off):
    """One day's [local sunrise "HH:MM", local sunset, daylight hours] for the
    weather tiles; [None, None, 24/0] when the sun never sets/rises."""
    st = _sun_times(lat, lon, d)
    if st == "day":
        return [None, None, 24.0]
    if st == "night":
        return [None, None, 0.0]
    r, s, dl = st

    def hm(mn):
        mn = int(mn + off * 60) % 1440
        return "%02d:%02d" % (mn // 60, mn % 60)
    return [hm(r), hm(s), round(dl, 1)]


def guidebook(v, guidebooks):
    """Guidebook per venue (title, publisher, £) — curated, with an Amazon
    search link. Keyed by the venue's exact name."""
    gb = guidebooks.get(v["name"])
    if not gb:
        return None
    amazon = "https://www.amazon.co.uk/s?k=" + urllib.parse.quote(gb["title"])
    return {"title": gb["title"], "pub": gb["pub"], "price": f"£{gb['price']}", "url": amazon}


def extra_climbing(v, extra_climbing_data):
    """Extra climbing references per venue — hand-researched, not derived from
    a live API or the spreadsheet (see extra-climbing.json)."""
    return extra_climbing_data.get(v["name"])


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


@dataclass
class TagSpec:
    """Derived from knowledge/data/tag-spec.json — the single source of truth
    for the venue "Area character" pills' colours, tooltips, legend line and
    emit-order. Edit the spec, not the code."""
    fams: dict
    order: dict
    fam_of: dict
    fams_meta: dict
    tips: dict
    css: str
    legend: str
    venue_css: str

    @classmethod
    def load(cls, tag_spec_path):
        spec = json.loads(tag_spec_path.read_text())
        fams = spec["families"]
        order = {t["k"]: i for i, t in enumerate(spec["tags"])}
        fam_of = {t["k"]: t["family"] for t in spec["tags"]}
        fams_meta = {fk: {"label": f["label"], "color": f["color"], "tier": f["tier"]}
                     for fk, f in fams.items()}
        tips = {t["k"]: f"{fams[t['family']]['tipLabel']} · {t['tip']}" for t in spec["tags"]}
        css = "".join(
            ",".join(f".tag-{t['k']}" for t in spec["tags"] if t["family"] == fk)
            + f"{{color:{f['color']};border-color:{f['border']};background:{f['bg']}}}"
            for fk, f in fams.items()
        ) + "".join(f".tag-{t['k']}{{font-weight:600}}" for t in spec["tags"] if t.get("strong"))
        t1 = next(f["label"] for f in fams.values() if f["tier"] == 1)
        legend = (f"grouped by family · <b>{t1}</b> is about your trip; the rest is static "
                  "area taxonomy — hover any tag, or open the ? for the full key")
        venue_css = (
            ":root{--dry-bg:rgba(87,166,100,.10);--mixed-bg:rgba(185,138,46,.10)}"
            ".tagleg{font-size:11.5px;color:var(--faint);margin:2px 0 13px;max-width:760px}"
            ".taghelp{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;"
            "border-radius:50%;border:1px solid var(--line2);color:var(--muted);font-size:11px;font-weight:600;"
            "text-decoration:none;vertical-align:2px;margin-left:6px}"
            ".taghelp:hover{color:var(--ink);border-color:var(--muted)}"
            ".taglanes{display:flex;flex-direction:column;gap:6px;max-width:820px}"
            ".taglane{display:flex;gap:11px;align-items:flex-start}"
            ".taglane.tb{margin-top:3px;padding-top:10px;border-top:1px solid var(--line)}"
            ".tll{flex:0 0 92px;font-family:var(--mono);font-size:9.5px;letter-spacing:.04em;text-transform:uppercase;"
            "padding-top:5px;line-height:1.35}"
            ".tlp{display:flex;gap:6px;flex-wrap:wrap;flex:1;min-width:0}"
            ".tag{font-family:var(--mono);font-size:11px;padding:4px 9px;border-radius:5px;border:1px solid var(--line2);"
            "white-space:nowrap;color:var(--ink)}"
            + css
        )
        return cls(fams, order, fam_of, fams_meta, tips, css, legend, venue_css)


def venue_tag_section(v, tag_spec):
    """Server-rendered 'Area character' section for a static venue page — reads the
    same v['tags'] already in the venue's JSON payload (no recompute, no hardcoding)
    and groups them into one labelled row per family, exactly like the dashboard."""
    tags = v.get("tags") or []
    if not tags:
        return ""
    rows, cur, curfam = [], [], None
    for t in tags:                       # tags arrive pre-sorted in spec/family order
        fam = tag_spec.fam_of.get(t["k"], "")
        if curfam is not None and fam != curfam:
            rows.append((curfam, cur))
            cur = []
        curfam = fam
        cur.append(t)
    if cur:
        rows.append((curfam, cur))
    lanes, prev_tier = [], None
    for fam, ts in rows:
        meta = tag_spec.fams_meta.get(fam, {})
        tb = " tb" if prev_tier is not None and meta.get("tier") != prev_tier else ""
        prev_tier = meta.get("tier")
        pills = "".join(
            f'<span class="tag tag-{_esc(t["k"])}" title="{_esc(tag_spec.tips.get(t["k"], ""))}">'
            f'{_esc(t["t"])}</span>' for t in ts)
        lanes.append(
            f'<div class="taglane{tb}"><div class="tll" style="color:{meta.get("color", "var(--muted)")}">'
            f'{_esc(meta.get("label", ""))}</div><div class="tlp">{pills}</div></div>')
    return ('<h2>Area character <a class="taghelp" href="../knowledge/data/tags.html" '
            'title="What every tag means">?</a></h2>'
            f'<p class="tagleg">{tag_spec.legend}</p>'
            f'<div class="taglanes">{"".join(lanes)}</div>')


def venue_tags(v, cards, grades, tag_spec, cond_txt=None, tidal=False):
    """Colored tag chips in two tiers, emitted in a FIXED order so every venue
    card reads the same way (see knowledge/data/tags.md — the reader-facing key
    the dashboard's "?" links to).

    Tier 1 · Trip fit (dynamic — this trip's dates/origin/window; violet):
        cond · time · trip
    Tier 2 · Area taxonomy (static facts about the crag — the same vocabulary
    that will tag each climb later), three families:
        Character (grey):        rock · aspect · wallheight · appr
        Scale & grade (green):   vol · diff · grade · pitches · tallest · routes
        Hazards (amber):         tidal · hazard

    Every kind maps to exactly one family colour; no kind is reused for two
    unrelated facts (the old `height`/`grade` collisions are split into
    wallheight/tallest and grade/pitches)."""
    sh = v.get("sheet") or {}
    tags = []

    def add(kind, text):
        if text:
            tags.append({"k": kind, "t": text})

    def approach_txt():
        walks = [x.get("approach") for x in cards if x.get("approach") is not None]
        if not walks:
            return None
        med = sorted(walks)[len(walks) // 2]
        return "long walk-ins" if med >= 60 else ("roadside cragging" if med <= 20 else f"~{med} min walk-ins")

    # ── Tier 1 · Trip fit (dynamic: your dates, your origin, your window) ──
    if cond_txt:
        add("cond", cond_txt)
    add("time", sh.get("travel_time") and f"{sh['travel_time']} from UK")
    add("trip", sh.get("min_trip") and f"min trip {sh['min_trip']}")

    # ── Tier 2a · Character (static physical crag) ──
    add("rock", v.get("rock"))
    asp = (v.get("aspect") or "").upper()
    if asp:
        adj = ASPECT_ADJ.get(asp, 0)
        add("aspect", f"{asp}-facing" + (" · shade" if adj < 0 else " · sun-baked" if adj >= 3 else ""))
    add("wallheight", sh.get("max_height") and f"walls to {sh['max_height']}m")
    if cards:
        add("appr", approach_txt())

    # ── Tier 2b · Scale & grade (how much / how hard / how big) ──
    add("vol", sh.get("volume") and f"{sh['volume']} volume")
    add("diff", sh.get("difficulty"))
    if grades:
        add("grade", f"Trad {grades}")
    if cards:
        pitches = [x.get("pitches") or 0 for x in cards]
        if max(pitches) >= 6:
            add("pitches", f"up to {max(pitches)} pitches")
        _tall = max(cards, key=lambda x: x.get("length") or 0)
        if _tall.get("length"):
            add("tallest", f"tallest {_tall['length']}m · {_tall['cliff']}")
        add("routes", f"{len(cards)} route{'s' if len(cards) != 1 else ''} on multi-pitch.com")

    # ── Tier 2c · Hazards (safety & access; from explicit route evidence only) ──
    if tidal:
        add("tidal", "tide-dependent access")
    if cards:
        seen_flags = {f for x in cards for f in (x.get("flags") or [])}
        if tidal:
            seen_flags.discard("Tidal")   # already the venue-level tidal chip
        for f in sorted(seen_flags):
            add("hazard", f)
        if any((x.get("appDiff") or 0) >= 3 for x in cards):
            add("hazard", "serious approach")
    # canonical family order comes from the spec — not the append sequence
    tags.sort(key=lambda t: tag_spec.order.get(t["k"], 999))
    return tags[:18]


def venue_payload(n, r, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec):
    """One venue's data as a plain dict → embedded as JSON and rendered client-side."""
    v = r["venue"]
    ok = bool(r.get("ok") and r["score"] >= 0)
    c = r.get("climo") or {}
    fc = r.get("fc")
    sea = r.get("seasonal")
    cards = nearby_climb_cards(v, mp_climbs) if ok else []
    rain = c.get("rain_pct")
    tag, tcls = wx_band(rain)
    grades = grade_range(cards)
    live = bool(fc and fc.get("in_window"))
    tidal = venue_is_tidal(v, mp_climbs)
    fl = r.get("flights") or {}
    out_date, back_date = ctx.rep_combo["out"], ctx.rep_combo["back"]

    def fallback_flight(who):
        cfg = v.get("travel", {}).get(who, {})
        m = cfg.get("mode")
        if m in ("local", "drive"):
            return {"mode": m}
        if m == "fly" and cfg.get("to"):
            return {"mode": "fly", "options": [], "to": cfg["to"],
                    "book_url": skyscanner_url(ctx.origin[who].split(",")[0], cfg["to"], out_date, back_date)}
        return {"mode": "unknown"}

    mf = fl.get("michel") or fallback_flight("michel")
    md = fl.get("dan") or fallback_flight("dan")

    facts = []

    # weather chart series: typical (climatology) days enriched with weekday labels,
    # plus per-day overlays — live forecast ("fc") when it reaches the window,
    # otherwise the 45-day ensemble outlook ("out").
    fcd = r.get("fc_days") or {}
    sead = (sea or {}).get("daily") or {}
    utc_off = _venue_utc_off(v)
    series = []
    for s in (c.get("series") or []):
        m = s.get("month", ctx.target_start.month)
        try:
            dt = date(ctx.target_start.year, m, s["day"])
            wd = dt.strftime("%a")
        except Exception:
            dt, wd = None, str(s["day"])
        entry = {"day": s["day"], "lbl": wd, "tmax": s["tmax"], "dir": s.get("dir"),
                 "precip": s["precip"], "wind": s.get("wind", 0),
                 "cloud": s.get("cloud"), "trip": s["trip"]}
        if dt and v.get("lat") is not None and v.get("lon") is not None:
            entry["sun"] = _day_sun(v["lat"], v["lon"], dt, utc_off)
        md_key = (m, s["day"])
        if md_key in fcd:
            entry["fc"] = fcd[md_key]
        elif md_key in sead:
            entry["out"] = sead[md_key]
        # estimated UV until the live forecast (which carries the real value)
        # reaches this day; attenuated by the best cloud signal we have
        if dt and v.get("lat") is not None and (entry.get("fc") or {}).get("uv") is None:
            cc = (entry.get("out") or {}).get("cloud")
            if cc is None:
                cc = entry.get("cloud")
            entry["uv"] = _uv_est(v["lat"], dt, cc)
        if dt and (r.get("tides") or {}).get(dt.isoformat()):
            entry["tide"] = r["tides"][dt.isoformat()]
        series.append(entry)

    return {
        "rank": n, "name": v["name"], "shortName": short_name(v["name"]),
        "lat": v.get("lat"), "lon": v.get("lon"),
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
                       else f"Typical {ctx.period_lbl} daily pattern (avg {ctx.climo_years[0]}–{ctx.climo_years[-1]})"),
        "grades": grades, "hero": (cards[0]["img"] if cards else None), "climbs": cards,
        "facts": facts,
        "flights": {"michel": mf, "dan": md},
        "stays": r.get("stays"), "guide": guidebook(v, guidebooks),
        "extraClimbing": extra_climbing(v, extra_climbing_data),
        "maps": maps_url(v), "weather": weather_url(v), "mpMap": MP_MAP_URL,
        "tidal": tidal,
        "tags": venue_tags(v, cards, grades, tag_spec,
                            (f"{tag} · {rain}% wet days" if rain is not None else tag), tidal),
        "listInfo": _list_info(v, r, cards)["txt"],
        "listTemp": _list_info(v, r, cards)["temp"],
        "breakdown": r.get("breakdown"),
        "auto": bool(v.get("auto")),
    }


PAGE_HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src https: data:">
<title>Multi-pitch climbing trip planner — European trad venues ranked daily by weather</title>
<meta name="description" content="Free multi-pitch climbing trip planner: 40+ European venues — Gredos, Fair Head, the Dolomites, Écrins and more — ranked every day by live weather, flight prices and places to stay.">
<link rel="canonical" href="https://uncinimichel.github.io/climbing-agent/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="multi·pitch trip planner">
<meta property="og:title" content="Multi-pitch climbing trip planner — venues ranked daily by weather">
<meta property="og:description" content="40+ European trad venues ranked every day by live weather, flights and stays.">
<meta property="og:url" content="https://uncinimichel.github.io/climbing-agent/">
<meta property="og:image" content="https://multi-pitch.com/img/tiles/aiguille-debona.jpg">
<meta name="twitter:card" content="summary_large_image">
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
.sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.allv{padding:24px 22px 30px;border-top:1px solid var(--line2);background:var(--panel)}
.allv nav{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:9px;max-width:1100px}
.allv a{font-family:var(--mono);font-size:11.5px;color:var(--muted);text-decoration:none;white-space:nowrap}
.allv a:hover{color:var(--ink);text-decoration:underline}
.allv-note{margin-top:12px;font-size:11px;color:var(--faint)}
.allv-note a{color:var(--faint)}
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
.wx-key{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin:0 0 10px;max-width:920px}
.wxtiles{display:flex;overflow-x:auto;max-width:920px;background:var(--card);border:1px solid var(--line);border-radius:12px;scrollbar-width:thin;scrollbar-color:var(--line2) transparent}
.wxtile{flex:1 1 0;min-width:72px;display:flex;flex-direction:column;align-items:center;gap:7px;padding:12px 4px;border-left:1px solid var(--line);cursor:default}
.wxtile:first-child{border-left:none}
.wxtile:hover{background:#252A32}
.wxtile.trip{background:var(--dry-bg);box-shadow:inset 0 2px 0 var(--dry)}
.wxtile.trip:hover{background:rgba(87,166,100,.16)}
.wxtile .wd{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}
.wxtile.trip .wd{color:var(--dry)}
.wxtile .ti svg{display:block}
.wxtile .t-out{font-family:var(--mono);font-weight:600;font-size:19px;line-height:1}
.wxtile .t-typ{font-family:var(--mono);font-size:10.5px;color:var(--faint);white-space:nowrap}
.wxrain{width:22px;height:44px;border-radius:4px;background:var(--panel);border:1px solid var(--line);position:relative;overflow:hidden;flex-shrink:0}
.wxrain .rt{position:absolute;left:0;right:0;bottom:0;background:repeating-linear-gradient(45deg,rgba(160,161,154,.28) 0 3px,transparent 3px 6px)}
.wxrain .ro{position:absolute;left:4px;right:4px;bottom:0;border-radius:2px 2px 0 0}
.wxtile .mm{font-family:var(--mono);font-size:10px;color:var(--faint)}
.wxdial{width:34px;height:34px;border-radius:50%;border:1.5px solid;display:flex;align-items:center;justify-content:center;position:relative;flex-shrink:0}
.wxdial .wn{font-family:var(--mono);font-size:11px;font-weight:600;color:var(--ink)}
.wxdial svg{position:absolute;inset:-8px;width:50px;height:50px}
.wxtile .suns{display:flex;flex-direction:column;align-items:center;gap:1px;font-family:var(--mono);font-size:9.5px;color:var(--faint);line-height:1.25;white-space:nowrap}
.wxtile .tds{font-family:var(--mono);font-size:9.5px;color:#6FC7D9;line-height:1.25;white-space:nowrap}
.wxtile .suns .dl{color:var(--muted)}
.wxtile .irow{display:flex;align-items:center;gap:4px}
.uvr{width:20px;height:20px;border-radius:50%;border:1.5px solid;display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:9.5px;font-weight:600;color:var(--ink);flex-shrink:0}
#wxtip{position:fixed;z-index:70;pointer-events:none;background:var(--card);border:1px solid var(--line2);color:var(--ink);font-family:var(--mono);font-size:11.5px;line-height:1.6;border-radius:7px;padding:8px 11px;max-width:260px;box-shadow:0 8px 24px rgba(0,0,0,.5);opacity:0;transition:opacity .12s}
#wxtip .dim{color:var(--muted)}
@media(prefers-reduced-motion:reduce){#wxtip{transition:none}}
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
.xnote{font-size:11.5px;color:var(--mixed);background:var(--mixed-bg);border:1px solid rgba(185,138,46,.35);border-radius:8px;padding:9px 12px;margin-bottom:12px;max-width:640px;line-height:1.5}
.xlinks{display:flex;flex-direction:column;gap:8px;max-width:640px}
a.xlink{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;text-decoration:none;border:1px solid var(--line2);border-radius:9px;padding:9px 13px;background:var(--card)}
a.xlink:hover{border-color:var(--muted)}
.xlink-src{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);flex-shrink:0}
.xlink-title{font-size:13px;font-weight:600;color:var(--ink)}
.xlink-note{font-size:11.5px;color:var(--faint);width:100%}
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
.taglane{display:flex;gap:11px;align-items:flex-start;max-width:880px}
.taglane+.taglane{margin-top:6px}
.taglane.tags-tb{margin-top:9px;padding-top:10px;border-top:1px solid var(--line)}
.tll{flex:0 0 84px;font-family:var(--mono);font-size:9px;letter-spacing:.04em;text-transform:uppercase;padding-top:5px;line-height:1.35}
.tlp{display:flex;gap:6px;flex-wrap:wrap;flex:1;min-width:0}
.tag{font-family:var(--mono);font-size:10.5px;padding:4px 9px;border-radius:5px;border:1px solid var(--line2);white-space:nowrap}
/* per-family .tag-* colour rules are generated from knowledge/data/tag-spec.json
   and injected here by render_page() — do not hardcode them */
/*TAG_CSS*/
.taghelp{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;border-radius:50%;border:1px solid var(--line2);color:var(--muted);font-size:10px;font-weight:600;text-decoration:none;vertical-align:1px;margin-left:6px}
.taghelp:hover{color:var(--ink);border-color:var(--muted)}
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
  /* phones: drop the key line (the same info lives in the tap-tooltips),
     shrink the tiles — the strip scrolls sideways inside its own card */
  .wx-key{display:none}
  .wxtile{min-width:60px;gap:6px;padding:10px 3px}
  .wxtile .t-out{font-size:17px}
  .wxrain{width:18px;height:38px}
  .wxdial{width:30px;height:30px}
  .wxdial svg{inset:-7px;width:44px;height:44px}
  .wxtile .suns{font-size:8.5px}
  .uvr{width:18px;height:18px;font-size:8.5px}
  .wxtile .irow{gap:3px}
}
</style></head>"""

PAGE_BODY = """<body>
<h1 class="sr">Multi-pitch climbing trip planner — European trad venues ranked daily by weather</h1>
<header class="top">
  <div class="wordmark"><img class="mplogo" src="https://multi-pitch.com/img/logo/mp-logo-white.png" alt="" onerror="this.style.display='none'">multi<b>·</b>pitch<em>trip planner</em></div>
  <div class="trip-line" id="tripline"></div>
  <nav class="top-links">
    <button class="tl" onclick="help(1)" title="How the ranking works" aria-label="How the ranking works">?</button>
    <a class="tl" href="knowledge/index.html">Knowledge</a>
    <a class="tl" href="knowledge/corpus-inspector.html" title="Browse every climb with its taxonomy + weather (reads corpus.json)">Inspector</a>
    <a class="tl" href="knowledge/data-dependencies.html" title="How climb/venue data flows — the source of truth (decision #27)">Data map</a>
    <a class="tl" href="knowledge/operations/serpapi-quota.html" title="Live SerpApi/flight-search quota and API cost status">API Status</a>
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
      <p><b style="color:var(--rain)">Weather · 55%</b> — rain and heat are now penalised
      <b>symmetrically</b>, so the sweet spot is genuinely <b>cool and dry</b> and <i>neither</i>
      a wet venue nor a baking-hot one can sit near the top. Wet days follow a curve that
      mirrors the heat one: dry climates (under ~12% wet days) pay nothing, then it slopes up
      and <b>steepens past 40% wet</b> — so a cool-but-drizzly area (Snowdonia, the Dolomites)
      now drops out of the top tier instead of coasting on mild temperatures. Temperature is
      scored <b>through a climbing lens</b>: friction research puts ideal sending temps around
      <b>7–18°C</b>, so points fall away gently above 18°C, steeply above 24°C, and brutally
      above 28°C (numb-fingers penalty below 8°C too — this is multi-pitch, hours exposed on
      the wall). <b>Sun exposure matters as much as air temperature</b>: a south-facing wall
      in full sun feels far hotter than the thermometer says, while a shaded north face
      climbs cooler — each crag's <b>aspect</b> shifts its felt temperature, weighted by how
      sunny it actually is (cloud/sunshine from the live forecast once in range; dryness as
      a proxy before that). Once the trip is inside the 16-day forecast, friction terms
      (dew point, drying sun, gusts) join in.</p>
      <p><b style="color:var(--temp)">Travel · 25%</b> — real return-flight prices for both
      of you when priced (now the <b>top 10</b> venues each day), and for anything not yet
      priced a <b>distance-based fare estimate</b> stands in so a far-flung venue can't hide
      behind a neutral score. Local/drivable venues score near-perfect. The <b>cheapest
      realistic bed near the crag</b> counts too (from OpenStreetMap): an area with a campsite
      stays cheap, a hotel-only area costs points — using typical nightly prices per type of
      stay, not live quotes.</p>
      <p><b style="color:var(--dry)">Venue fit · 20%</b> — from the spreadsheet's judgment
      columns: how much multi-pitch there is, its difficulty spread, and whether the
      minimum sensible trip fits your dates — plus <b>distance from home</b> (London for
      Michel, Belfast/Dublin for Dan), so nearby European crags edge out ones in Africa or
      the US when all else is close.</p>
      <p>Ranking basis by date: <b>typical weather for your trip dates</b> (recent-year averages) blended with the
      <b>long-range outlook</b> now (a forecast model that can see up to ~45 days ahead — the ‘45-day’ is the model’s reach, not your trip length). As the <b>live 16-day forecast</b> reaches into your window it takes over <b>only for the days it actually covers</b> — a venue whose forecast reaches 2 of your 6 trip days is scored ⅓ on those live days and ⅔ on typical weather for the rest, so a couple of dry days at the edge of the forecast can’t out-rank a whole typical-week verdict. It fully supersedes once it spans the trip. The page
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
  // Icon chips for the headline climbing signals — always visible, so the
  // conditions never hide behind the tiles' hover/tap tooltips. Most need the
  // live forecast; the tidal flag is a fixed venue trait, so it shows now.
  var w=v.wx||{},chips=[];
  if(w.live&&w.friction){
    var fc=w.friction==='greasy'?'bad':w.friction==='humid'?'warn':'good';
    chips.push('<span class="cc '+fc+'"><span class="ci">🪨</span>rock <b>'+esc(w.friction)+'</b></span>');
  }
  if(w.live&&w.gustMax!=null){
    var gc=w.gustMax>=55?'bad':w.gustMax>=40?'warn':'good';
    chips.push('<span class="cc '+gc+'"><span class="ci">🌬️</span>gusts <b>'+num(w.gustMax)+' km/h</b></span>');
  }
  if(w.live&&w.amDry&&w.amDry[1]){
    var dc=w.amDry[0]===w.amDry[1]?'good':(w.amDry[0]===0?'bad':'warn');
    chips.push('<span class="cc '+dc+'"><span class="ci">🌅</span><b>'+num(w.amDry[0])+'/'+num(w.amDry[1])+'</b> dry mornings</span>');
  }
  if(v.tidal)chips.push('<span class="cc warn"><span class="ci">🌊</span><b>tidal</b> — plan around low water</span>');
  return chips.length?'<div class="wx-cond">'+chips.join('')+'</div>':'';
}

function wxHtml(v){
  var s=v.series||[];
  if(!s.length)return '<div class="sec"><div class="eyebrow">Weather</div><div class="empty">No weather data for this area yet.</div></div>';
  return '<div class="sec"><div class="sec-hd"><div class="eyebrow">Weather · '+esc(D.trip.dates)+'</div>'
    +(safeUrl(v.weather)?'<a class="lk sm" target="_blank" rel="noopener" href="'+safeUrl(v.weather)+'">Full forecast on Windy ↗</a>':'')+'</div>'
    +takeaway(v)
    +'<div id="wxChart"></div>'
    +(v.seasonal?'<div class="outlook">Long-range outlook (model reach ~45 days, experimental '+num(v.seasonal.members)+'-member ensemble) supplies the big per-day numbers until the live forecast lands ~8 July.</div>':'')
    +'</div>';
}

// Severity colours shared across the whole weather chart (bars, dots, wind
// labels) — the SAME three-tier scale already used everywhere else on this
// page (leaderboard bars, condition chips, the trip-score ring), so a reader
// only has to learn one "green = fine, amber = caution, red = rough" language
// for the whole dashboard rather than a chart-specific one. Cold gets its own
// blue tier for temperature only — the thermometer convention is universal
// enough that a 4th colour there reads as MORE obvious, not less.
// Wind/temp thresholds come from D.trip.climateThresholds — the SAME
// cold/heat/gust breakpoints heat_penalty()/day_score() use to compute the
// score itself (see engine/weather.py), not a separately-eyeballed copy, so
// the chart can never quietly disagree with the score about what counts as
// cold/hot/windy. Rain has no equivalent scorer constant to share (the score
// works off a period's wet-day %, not a single day's mm) so its thresholds
// are tuned directly from the trip's own daily rainfall distribution.
var CT=(D.trip&&D.trip.climateThresholds)||{cold:8,warm:20,hot:25,gustBad:30};
function rainColor(mm){mm=num(mm);return mm>=6?'#D06A57':(mm>=2?'#B98A2E':'#57A664');}
function windColor(k){k=num(k);return k>=CT.gustBad?'#D06A57':(k>=CT.gustBad/2?'#B98A2E':'#57A664');}
function tempColor(t){t=num(t);return t>=CT.hot?'#D06A57':(t>=CT.warm?'#B98A2E':(t>=CT.cold?'#57A664':'#3987e5'));}
// WHO UV bands folded onto the page's severity colours (violet = the WHO
// "extreme" tier — it exists nowhere else on the page, like temp's cold blue)
function uvColor(u){u=num(u);return u>=11?'#B07ADB':(u>=6?'#D06A57':(u>=3?'#B98A2E':'#57A664'));}

// Per-day tiles (BBC-style strip, one column per day) — replaced the ECharts
// line/bar chart 4 Jul 2026; Michel picked this from four mockup options.
// Per tile, top to bottom: sky icon, big °C = outlook (forecast once it
// lands ~8 Jul), small °C = typical, rain bar on a scale shared across all
// days (hatched = typical, solid = outlook), wind dial (ring colour =
// severity, arrow flies WITH the wind — same convention as the old chart's
// axis arrows). Plain HTML/SVG: dropping ECharts here removed the page's
// only CDN script.
function wxCloud(d){
  // best cloud-cover signal for the day: live forecast, else ensemble
  // outlook, else the 2021-24 typical mean
  if(d.fc&&d.fc.cloud!=null)return num(d.fc.cloud);
  if(d.out&&d.out.cloud!=null)return num(d.out.cloud);
  return d.cloud!=null?num(d.cloud):null;
}
function wxIcon(d){
  var o=d.fc||d.out,mm=o?num(o.precip):num(d.precip);
  var cc=wxCloud(d);
  var sf=(d.fc&&d.fc.sunFrac!=null)?num(d.fc.sunFrac):null;
  // sky from the best signal available: rain trumps everything, then real
  // cloud cover, then live sun fraction, then expected rain as a proxy
  var kind=mm>=2?'rain'
    :cc!=null?(cc<25?'sun':(cc<60?'partly':'cloud'))
    :sf!=null?(sf>=.6?'sun':(sf>=.3?'partly':'cloud'))
    :(mm<0.05?'sun':(mm<0.5?'partly':'cloud'));
  function rays(cx,cy,r1,r2,wd){var s3='';[0,45,90,135,180,225,270,315].forEach(function(a){var r=a*Math.PI/180;
    s3+='<line x1="'+(cx+r1*Math.cos(r)).toFixed(1)+'" y1="'+(cy+r1*Math.sin(r)).toFixed(1)+'" x2="'+(cx+r2*Math.cos(r)).toFixed(1)+'" y2="'+(cy+r2*Math.sin(r)).toFixed(1)+'" stroke="#E5B93F" stroke-width="'+wd+'" stroke-linecap="round"/>';});return s3;}
  var inner,label;
  if(kind==='sun'){inner='<circle cx="15" cy="15" r="5.4" fill="#E5B93F"/>'+rays(15,15,8,11,2);label='sunny';}
  else if(kind==='partly'){inner='<circle cx="11" cy="11" r="4.4" fill="#E5B93F"/>'+rays(11,11,6.4,9,1.8)
    +'<path d="M12 23a4 4 0 0 1 .5-8 5.4 5.4 0 0 1 10.4 1.1A3.6 3.6 0 0 1 22.4 23Z" fill="#7E838D"/>';label='sunny intervals';}
  else if(kind==='cloud'){inner='<path d="M8 20a4.5 4.5 0 0 1 .6-9 6 6 0 0 1 11.6 1.2A4 4 0 0 1 19.6 20Z" fill="#7E838D"/>';label='cloudy';}
  else{inner='<path d="M12 21a4 4 0 0 1 .5-8 5.4 5.4 0 0 1 10.4 1.1A3.6 3.6 0 0 1 22.4 21Z" fill="#7E838D"/>'
    +'<g fill="#3987e5"><path d="M12 25l-1.6 3.2a1.8 1.8 0 1 0 3.2 0Z"/><path d="M19 25l-1.6 3.2a1.8 1.8 0 1 0 3.2 0Z"/></g>';label='rain';}
  return '<span class="ti"><svg width="30" height="30" viewBox="0 0 30 30" role="img" aria-label="'+label+'">'+inner+'</svg></span>';
}
function wxTipHtml(d){
  var o=d.fc||d.out;
  var ARR=['↓','↙','←','↖','↑','↗','→','↘'];
  function warr(x){return x==null?'':ARR[Math.round((((num(x)%360)+360)%360)/45)%8];}
  var h='<b>'+esc(d.lbl)+' '+num(d.day)+(d.trip?' · TRIP DAY':'')+'</b><br><span class="dim">typical:</span> '+num(d.tmax)+'°C · '+num(d.precip)+' mm · wind '+num(d.wind)+' km/h';
  if(o)h+='<br><b>'+(d.fc?'forecast':'outlook')+': '+num(o.tmax)+'°C · '+num(o.precip)+' mm</b>';
  if(d.sun)h+='<br><span class="dim">daylight:</span> '+(d.sun[0]
    ?esc(d.sun[0])+' → '+esc(d.sun[1])+' · '+num(d.sun[2])+' h'
    :(d.sun[2]>=24?'sun never sets (24 h)':'sun never rises'));
  var tcc=wxCloud(d),tuv=(d.fc&&d.fc.uv!=null)?num(d.fc.uv):(d.uv!=null?num(d.uv):null);
  if(tcc!=null||tuv!=null)h+='<br><span class="dim">'
    +(tcc!=null?'cloud '+tcc+'%':'')
    +(tcc!=null&&tuv!=null?' · ':'')
    +(tuv!=null?'UV '+tuv+((d.fc&&d.fc.uv!=null)?'':' est.'):'')+'</span>';
  if(d.fc){
    if(d.fc.wind!=null)h+='<br>wind '+num(d.fc.wind)+' km/h'+(d.fc.dir!=null?' from '+compass(d.fc.dir)+' '+warr(d.fc.dir):'')+(d.fc.gust!=null?' · gusts '+num(d.fc.gust):'');
    if(d.fc.friction)h+='<br>friction: '+esc(d.fc.friction)+(d.fc.dew!=null?' (dew '+num(d.fc.dew)+'°C)':'');
    if(d.fc.sunFrac!=null)h+=' · sun '+Math.round(num(d.fc.sunFrac)*100)+'%';
  }
  if(d.tide&&d.tide.length)h+='<br><span class="dim">tide (vs mean sea level):</span> '
    +d.tide.map(function(x){return (x.k==='L'?'▼':'▲')+esc(x.t)+' '+num(x.h)+'m';}).join(' · ');
  return h;
}
var _wxTipEl=null;
function wxTip(){
  if(!_wxTipEl){
    _wxTipEl=document.createElement('div');_wxTipEl.id='wxtip';document.body.appendChild(_wxTipEl);
    var off=function(){_wxTipEl.style.opacity=0;};
    document.addEventListener('click',off);
    window.addEventListener('scroll',off,{passive:true});
  }
  return _wxTipEl;
}
function wireWxTips(root,s2){
  var tip=wxTip();
  function show(el){
    var d=s2[+el.getAttribute('data-i')];if(!d)return;
    tip.innerHTML=wxTipHtml(d);tip.style.opacity=1;
    var r=el.getBoundingClientRect(),tw=tip.offsetWidth||220;
    var x=Math.min(Math.max(8,r.left+r.width/2-tw/2),window.innerWidth-tw-8);
    var y=r.top-tip.offsetHeight-10;if(y<8)y=r.bottom+10;
    tip.style.left=x+'px';tip.style.top=y+'px';
  }
  var els=root.querySelectorAll('.wxtile');
  for(var k=0;k<els.length;k++)(function(el){
    el.addEventListener('mouseenter',function(){show(el);});
    el.addEventListener('mouseleave',function(){tip.style.opacity=0;});
    el.addEventListener('focus',function(){show(el);});
    el.addEventListener('blur',function(){tip.style.opacity=0;});
    el.addEventListener('click',function(e){show(el);e.stopPropagation();});
  })(els[k]);
}
function renderWx(v){
  var el=document.getElementById('wxChart');
  if(!el)return;
  var s2=v.series||[];if(!s2.length)return;
  var anyFc=s2.some(function(d){return d.fc;}),ov=anyFc?'forecast':'outlook';
  // one rain scale for the whole strip; floor of 2 mm so trace amounts don't
  // fill the bar on a dry week (thresholds match rainColor's amber cutoff)
  var mx=2;
  s2.forEach(function(d){var o=d.fc||d.out;mx=Math.max(mx,num(d.precip),o?num(o.precip):0);});
  mx=Math.ceil(mx);
  function pc(mm){mm=num(mm);return mm<=0?0:Math.max(4,Math.round(mm/mx*100));}
  var h=s2.map(function(d,i){
    var o=d.fc||d.out;
    var w=(d.fc&&d.fc.wind!=null)?num(d.fc.wind):num(d.wind);
    var dd=(d.fc&&d.fc.dir!=null)?d.fc.dir:d.dir;
    var wc=windColor(w),big=o?o.tmax:d.tmax;
    var mm=o?num(o.precip):num(d.precip);
    var uv=(d.fc&&d.fc.uv!=null)?num(d.fc.uv):(d.uv!=null?num(d.uv):null);
    var uvEst=!(d.fc&&d.fc.uv!=null);
    return '<div class="wxtile'+(d.trip?' trip':'')+'" data-i="'+i+'" tabindex="0" role="listitem">'
      +'<span class="wd">'+esc(d.lbl)+' '+num(d.day)+'</span>'
      +'<span class="irow">'+wxIcon(d)
      +(uv!=null?'<span class="uvr" style="border-color:'+uvColor(uv)+'" title="UV index '+uv+(uvEst?' (estimated)':'')+'">'+uv+'</span>':'')+'</span>'
      +'<span class="t-out" style="color:'+tempColor(big)+'">'+num(big)+'°</span>'
      +'<span class="t-typ">'+(o?'typ '+num(d.tmax)+'°':'typical')+'</span>'
      +'<span class="wxrain"><span class="rt" style="height:'+pc(d.precip)+'%"></span>'
      +(o?'<span class="ro" style="height:'+pc(o.precip)+'%;background:'+rainColor(o.precip)+'"></span>':'')
      +'</span>'
      +'<span class="mm">'+(mm>0?mm+'mm':'·')+'</span>'
      +'<span class="wxdial" style="border-color:'+wc+'">'
      +'<svg viewBox="0 0 50 50" aria-hidden="true"><g transform="rotate('+((num(dd)+180)%360)+' 25 25)"><path d="M25 2l4 7h-8Z" fill="'+wc+'"/></g></svg>'
      +'<span class="wn">'+w+'</span></span>'
      +(d.sun?'<span class="suns">'+(d.sun[0]
        ?'<span title="sunrise">↑'+esc(d.sun[0])+'</span><span title="sunset">↓'+esc(d.sun[1])+'</span><span class="dl" title="daylight">'+num(d.sun[2])+' h</span>'
        :'<span>'+(d.sun[2]>=24?'☀ 24 h':'no sun')+'</span>')+'</span>':'')
      +(function(){
        if(!d.tide)return '';
        var lows=d.tide.filter(function(x){return x.k==='L';});
        return lows.length?'<span class="tds" title="low water, local time">'+lows.map(function(x){return '▼'+esc(x.t);}).join(' ')+'</span>':'';
      })()
      +'</div>';
  }).join('');
  var anyTide=s2.some(function(d){return d.tide&&d.tide.length;});
  el.innerHTML='<div class="wx-key">big °C = '+ov+' · small = typical '+esc(D.trip.periodLbl)+' · icon = cloud cover · ring by icon = UV index'+(anyFc?'':' (est.)')+' · bar = rain mm, 0–'+mx+' scale (hatch = typical, solid = '+ov+') · dial = wind km/h, arrow = where it blows · ↑↓ = sunrise/sunset, local + daylight h'+(anyTide?' · ▼ = low water, local':'')+' · green/amber/red = fine/caution/rough</div>'
    +'<div class="wxtiles" role="list" aria-label="Daily weather, one tile per day">'+h+'</div>'
    +(v.tidal&&!anyTide?'<div class="wx-key">🌊 tide-dependent access — low-water times appear on these tiles once the 10-day tide forecast reaches the trip dates.</div>':'');
  wireWxTips(el,s2);
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
// hover and flicker. Pure SVG, like everything else on the page.
function renderBrk(v){
  var el=document.getElementById('brkChart');
  if(!el)return;
  var b=v.breakdown;
  if(!b){el.innerHTML='';return;}
  var W=b.weights||{weather:55,travel:25,fit:20};
  var FACT=[
    {key:'weather',name:'WEATHER',val:num(b.weather),wt:W.weather,color:'#3987e5',fn:'100 −rain −heat −wind −grease'},
    {key:'travel',name:'TRAVEL',val:num(b.travel),wt:W.travel,color:'#d95926',fn:'(flights + time + stay) / 3'},
    {key:'fit',name:'VENUE FIT',val:num(b.fit),wt:W.fit,color:'#57A664',fn:'(vol + diff + trip + routes + distance) / 5'}
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

// Tooltips (TAGT) and the colour legend (TAGLEG) are generated from
// knowledge/data/tag-spec.json and injected by render_page — see window.DATA line.
var TAGT=window.TAGT||{};
function tagsHtml(v){
  if(!v.tags||!v.tags.length)return '';
  // one labelled pill row per family (Trip fit · Character · Scale & grade ·
  // Hazards), in spec order; a rule marks the break between the dynamic tier and
  // the static area taxonomy.
  var FAM=window.TAGFAM||{},FAMS=window.TAGFAMS||{},rows=[],cur=[],curFam=null;
  v.tags.forEach(function(t){
    var f=FAM[t.k]||'';
    if(curFam!==null&&f!==curFam){rows.push({fam:curFam,html:cur.join('')});cur=[];}
    curFam=f;
    cur.push('<span class="tag tag-'+esc(t.k)+'" title="'+esc(TAGT[t.k]||'')+'">'+esc(t.t)+'</span>');
  });
  if(cur.length)rows.push({fam:curFam,html:cur.join('')});
  var lanes=rows.map(function(r,i){
    var meta=FAMS[r.fam]||{},prev=i>0?(FAMS[rows[i-1].fam]||{}):null;
    var tb=(prev&&meta.tier!==prev.tier)?' tags-tb':'';
    return '<div class="taglane'+tb+'"><div class="tll" style="color:'+(meta.color||'var(--muted)')+'">'+esc(meta.label||'')+'</div><div class="tlp">'+r.html+'</div></div>';
  }).join('');
  return '<div class="sec"><div class="eyebrow">Area character<a class="taghelp" href="knowledge/data/tags.html" target="_blank" rel="noopener" title="What every tag means">?</a></div><div class="tagleg">'+(window.TAGLEG||'')+'</div>'+lanes+'</div>';
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
function extraClimbingHtml(v){
  var links=v.extraClimbing;
  if(!links||!links.length)return '';
  var rows=links.map(function(l){
    return '<a class="xlink" target="_blank" rel="noopener" href="'+safeUrl(l.url)+'">'
      +'<span class="xlink-src">'+esc(l.source)+'</span>'
      +'<span class="xlink-title">'+esc(l.title)+'</span>'
      +(l.note?'<span class="xlink-note">'+esc(l.note)+'</span>':'')
      +'</a>';
  }).join('');
  return '<div class="sec"><div class="sec-hd"><div class="eyebrow">More climbing in the area</div></div>'
    +'<div class="xnote">⚠ not curated like the rest of this page — found via web search, not verified against a live database. Names, grades or access details may be out of date; treat as a starting point, not ground truth.</div>'
    +'<div class="xlinks">'+rows+'</div></div>';
}

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
    +extraClimbingHtml(v)
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
  renderBrk(V[i]);renderWx(V[i]);
  if(_booted)try{history.replaceState(null,'','#'+slugify(V[i].shortName));}catch(e){}
  if(_booted&&window.innerWidth<900)document.getElementById('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
var _h=location.hash.replace('#',''),_i0=0;
if(_h)V.forEach(function(v,i){if(slugify(v.shortName)===_h)_i0=i;});
sel(_i0);
_booted=true;
window.addEventListener('hashchange',function(){var h=location.hash.replace('#','');V.forEach(function(v,i){if(slugify(v.shortName)===h&&i!==_cur)sel(i);});});
"""


def build_data(ranked, now, banner, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec):
    """The embedded-data dict: every venue's payload + trip-level context."""
    from . import weather as _weather
    payload = [venue_payload(n, r, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec)
               for n, r in enumerate(ranked, 1)]
    trip = {
        "pills": ["✈ Michel · London", "✈ Dan · Belfast / Dublin",
                  f"📅 {ctx.rep_out_lbl} – {ctx.rep_back_lbl}",
                  f"🧗 {len(payload)} areas ranked"],
        "dates": f"{ctx.rep_out_lbl} → {ctx.rep_back_lbl}",
        "periodLbl": ctx.period_lbl,
        "repoUrl": REPO_URL,
        "mapUrl": MP_MAP_URL, "sheetUrl": SHEET_URL, "mpUrl": SITE_URL,
        "updated": now.strftime("%a %d %b %Y, %H:%M UTC"),
        # single source of truth for the weather chart's severity colouring —
        # the same breakpoints the scorer itself uses, so the chart can never
        # quietly disagree with the score about what counts as cold/hot/windy
        "climateThresholds": {"cold": _weather.COLD_C, "warm": _weather.HEAT_WARM_C,
                               "hot": _weather.HEAT_HOT_C, "gustBad": _weather.GUST_BAD_KMH},
    }
    return {"venues": payload, "trip": trip,
            "banner": {"cls": (banner[0] or "info"), "html": banner[1]}}


def render_page(data, tag_spec):
    """Assemble the final page from the embedded-data dict. Kept separate from
    build_html so the page can be re-rendered from an existing index.html's
    window.DATA without re-hitting any API."""
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    # server-rendered venue links: crawlable text + the discovery path to the
    # static venues/ pages, since the SPA's own nav is JS + #hashes
    links = "".join(
        f'<a href="venues/{_slug(v["shortName"])}.html">{_esc(v["shortName"])} ({_esc(v["country"])})</a>'
        for v in data["venues"])
    footer = ('<footer class="allv"><div class="eyebrow">All climbing areas</div><nav>'
              + links + '</nav><div class="allv-note">Multi-pitch venues ranked daily by weather · '
              f'routes from <a href="{SITE_URL}" rel="noopener">multi-pitch.com</a> · '
              f'weather from <a href="https://open-meteo.com/" rel="noopener">Open-Meteo</a></div></footer>')
    # tag colours (CSS) + tooltips + legend are generated from tag-spec.json
    tagt = json.dumps(tag_spec.tips, ensure_ascii=False).replace("</", "<\\/")
    tagleg = json.dumps(tag_spec.legend, ensure_ascii=False).replace("</", "<\\/")
    return (PAGE_HEAD.replace("/*TAG_CSS*/", tag_spec.css)
            + "\n<script>window.DATA=" + blob
            + ";window.TAGT=" + tagt + ";window.TAGLEG=" + tagleg
            + ";window.TAGFAM=" + json.dumps(tag_spec.fam_of)
            + ";window.TAGFAMS=" + json.dumps(tag_spec.fams_meta, ensure_ascii=False) + ";</script>\n"
            + PAGE_BODY
            + footer
            + "<script>" + PAGE_JS + "</script>\n</body></html>\n")


def build_html(ranked, now, banner, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec):
    """Light 'guidebook' dashboard: left = ranked leaderboard (score bars), right =
    area detail (contour-map header with the weather score at the summit, weather
    rows, flights, climbs, sample stays). All per-venue data is embedded as JSON
    and rendered client-side so one static file (GitHub Pages) supports switching
    between areas."""
    data = build_data(ranked, now, banner, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec)
    return render_page(data, tag_spec)


def venue_page(v, trip, tag_spec):
    """Static, crawlable page per venue (SEO): the SPA's #hash routes all look
    like ONE page to search engines, so each venue gets a real URL with the
    weather table, routes and resources server-rendered. Carries the planner's
    own .top header (Michel's request, 4 Jul) so hopping between the static
    pages and the live site feels like one website; the article body itself
    stays name-free."""
    name, slug = v["name"], _slug(v["shortName"])
    pills = " · ".join(trip.get("pills") or [])
    period = trip.get("periodLbl", "late July")
    why = re.sub(r"\s*—\s*auto-summary.*$", "", v.get("why") or "", flags=re.S).strip()
    wx = v.get("wx") or {}
    desc = (f"{name} ({v.get('country','')}) multi-pitch climbing: {v.get('style','')}. "
            f"Typical {period}: {wx.get('tmax','?')}°C, wind {wx.get('wind','?')} km/h. "
            "Daily-updated weather outlook, classic routes, and travel notes.")
    # low-water column only once tide data reaches the window (tidal venues only)
    has_tide = any(e.get("tide") for e in v.get("series") or [])
    rows = []
    for e in v.get("series") or []:
        o = e.get("fc") or e.get("out") or {}
        sun = e.get("sun") or [None, None, None]
        uv = (e.get("fc") or {}).get("uv", e.get("uv"))
        lows = " / ".join(x["t"] for x in (e.get("tide") or []) if x.get("k") == "L")
        rows.append(
            "<tr><td>%s %s Jul</td><td>%s</td><td>%s°C</td><td>%s°C</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s h</td><td>%s</td>%s</tr>" % (
                _esc(e.get("lbl", "")), _esc(e.get("day", "")), _sky_label(e),
                _esc(o.get("tmax", "–")), _esc(e.get("tmax", "–")),
                _esc(o.get("precip", e.get("precip", "–"))), _esc(e.get("wind", "–")),
                _esc(sun[0] or "–"), _esc(sun[1] or "–"), _esc(sun[2] if sun[2] is not None else "–"),
                _esc(uv if uv is not None else "–"),
                f"<td>{_esc(lows or '–')}</td>" if has_tide else ""))
    climbs = "".join(
        f'<li><a href="{_esc(c["url"])}" rel="noopener">{_esc(c.get("route",""))}</a> '
        f'({_esc(c.get("grade",""))}{", " + str(c.get("pitches")) + " pitches" if c.get("pitches") else ""}) '
        f'on {_esc(c.get("cliff",""))}</li>'
        for c in (v.get("climbs") or []) if c.get("url"))
    extras = "".join(
        f'<li><a href="{_esc(x["url"])}" rel="noopener">{_esc(x.get("title",""))}</a> '
        f'<span class="src">({_esc(x.get("source",""))})</span> — {_esc(x.get("note",""))}</li>'
        for x in (v.get("extraClimbing") or []) if isinstance(x, dict) and x.get("url"))
    fl = []
    for who, lbl in (("michel", "from London"), ("dan", "from Belfast / Dublin")):
        f = (v.get("flights") or {}).get(who) or {}
        opts = f.get("options") or []
        if f.get("mode") == "fly" and opts:
            o0 = opts[0]
            fl.append(f"Flights {lbl} from £{_esc(o0['price'])} "
                      f"({_esc(o0['from'])}→{_esc(o0['to'])}, {_esc(o0['airline'])})")
        elif f.get("mode") == "drive":
            fl.append(f"Drive/train {lbl}")
        elif f.get("mode") == "local":
            fl.append(f"Local {lbl}")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(name)} multi-pitch climbing — weather, routes &amp; travel</title>
<meta name="description" content="{_esc(desc)}">
<link rel="canonical" href="{PAGES_BASE}venues/{slug}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="{_esc(name)} multi-pitch climbing">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{PAGES_BASE}venues/{slug}.html">
{f'<meta property="og:image" content="{_esc(v["hero"])}">' if v.get("hero") else ""}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#14161A;--panel:#191C21;--card:#20242B;--ink:#E9E7E1;--muted:#A0A19A;--faint:#6E7069;--line:#2A2E36;--line2:#353A44;
--disp:'Bricolage Grotesque',sans-serif;--body:'IBM Plex Sans',sans-serif;--mono:'IBM Plex Mono',monospace}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.6}}
/* .top header: keep in sync with PAGE_HEAD's .top rules — same markup, same look */
.top{{display:flex;align-items:center;flex-wrap:wrap;gap:10px 18px;padding:13px 22px;border-bottom:1px solid var(--line2);background:var(--panel)}}
.mplogo{{width:22px;height:22px;object-fit:contain;margin-right:8px;vertical-align:-5px}}
.wordmark{{font-family:var(--disp);font-weight:800;font-size:19px;letter-spacing:-.02em;white-space:nowrap;display:flex;align-items:center;color:var(--ink);text-decoration:none}}
.wordmark em{{font-style:normal;font-weight:500;font-size:10px;font-family:var(--mono);color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-left:8px}}
.trip-line{{font-size:12.5px;color:var(--muted)}}
.top-links{{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}}
.tl{{font-size:12px;font-weight:500;text-decoration:none;color:var(--ink);border:1px solid var(--line2);border-radius:7px;padding:5px 11px;background:var(--card);white-space:nowrap}}
.tl:hover{{border-color:var(--muted)}}
.tl.strong{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.tl.strong:hover{{opacity:.88}}
.wrap{{max-width:820px;margin:0 auto;padding:28px 20px 60px}}
a{{color:#57A664}} h1{{font-family:var(--disp);font-size:30px;line-height:1.15;margin-bottom:4px}} h2{{font-family:var(--disp);font-size:17px;margin:28px 0 10px}}
.meta{{color:var(--muted);font-size:13px}} .src{{color:var(--faint);font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;font-family:var(--mono)}}
.twrap{{overflow-x:auto}} th,td{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{color:var(--muted);font-weight:600}} li{{margin-bottom:7px}} ul{{padding-left:20px}}
.cta{{display:inline-block;margin-top:20px;background:var(--ink);color:var(--bg);border-radius:8px;padding:8px 14px;text-decoration:none;font-weight:600}}
footer{{margin-top:34px;color:var(--faint);font-size:12px;border-top:1px solid var(--line);padding-top:12px}}
{tag_spec.venue_css}
</style></head><body>
<header class="top">
  <a class="wordmark" href="../"><img class="mplogo" src="https://multi-pitch.com/img/logo/mp-logo-white.png" alt="" onerror="this.style.display='none'">multi<b>·</b>pitch<em>trip planner</em></a>
  <div class="trip-line">{_esc(pills)}</div>
  <nav class="top-links">
    <a class="tl" href="../" title="How the ranking works — in the live planner">?</a>
    <a class="tl" href="../knowledge/index.html">Knowledge</a>
    <a class="tl" href="../knowledge/operations/serpapi-quota.html" title="Live SerpApi/flight-search quota and API cost status">API Status</a>
    <a class="tl" href="{_esc(trip.get('mapUrl',''))}" target="_blank" rel="noopener">Map</a>
    <a class="tl" href="{_esc(trip.get('sheetUrl',''))}" target="_blank" rel="noopener">Spreadsheet</a>
    <a class="tl" href="{_esc(trip.get('repoUrl',''))}" target="_blank" rel="noopener">GitHub</a>
    <a class="tl strong" href="{_esc(trip.get('mpUrl',''))}" target="_blank" rel="noopener">multi-pitch.com ↗</a>
  </nav>
</header>
<main class="wrap">
<h1>{_esc(name)} — multi-pitch climbing</h1>
<p class="meta">{_esc(v.get('country',''))} · {_esc(v.get('rock',''))} · {_esc(v.get('style',''))}{(' · grades ' + _esc(v['grades'])) if v.get('grades') else ''}{' · tidal access — plan around low water' if v.get('tidal') else ''}</p>
{f'<p>{_esc(why)}</p>' if why else ''}
{venue_tag_section(v, tag_spec)}
<h2>Weather — typical {_esc(period)} vs current outlook</h2>
<div class="twrap"><table>
<tr><th>Day</th><th>Sky</th><th>Outlook high</th><th>Typical high</th><th>Rain mm</th><th>Wind km/h</th><th>Sunrise</th><th>Sunset</th><th>Daylight</th><th>UV</th>{'<th>Low water</th>' if has_tide else ''}</tr>
{''.join(rows)}
</table></div>
<p class="meta">Updated {_esc(trip.get('updated',''))} · typical = 2021–2024 average · outlook = 45-day ensemble, replaced by the live 16-day forecast as the window approaches.</p>
{f'<h2>Classic routes</h2><ul>{climbs}</ul>' if climbs else ''}
{f'<h2>More climbing &amp; guidebook resources</h2><ul>{extras}</ul>' if extras else ''}
{f'<h2>Getting there</h2><p>{_esc(" · ".join(fl))}</p>' if fl else ''}
<a class="cta" href="../#{slug}">Open {_esc(v.get('shortName',name))} in the live planner →</a>
<footer>Part of the <a href="{PAGES_BASE}">multi-pitch climbing trip planner</a> — 40+ European venues ranked daily by weather.
Data: <a href="https://open-meteo.com/" rel="noopener">Open-Meteo</a> · routes: <a href="{SITE_URL}" rel="noopener">multi-pitch.com</a>.</footer>
</main>
</body></html>
"""


def write_venue_pages(data, repo_root, tag_spec):
    """Emit venues/<slug>.html for every venue; returns the slugs (for the
    sitemap). The dir is rebuilt from scratch so renamed venues don't leave
    stale pages behind."""
    vdir = repo_root / "venues"
    if vdir.exists():
        for p in vdir.glob("*.html"):
            p.unlink()
    vdir.mkdir(exist_ok=True)
    slugs = []
    for v in data["venues"]:
        slug = _slug(v["shortName"])
        (vdir / f"{slug}.html").write_text(venue_page(v, data["trip"], tag_spec))
        slugs.append(slug)
    return slugs


def write_seo_files(slugs, today, repo_root):
    """sitemap.xml + robots.txt at the repo root (staged into site/ by CI).
    Venue pages + the planner are regenerated daily; knowledge pages get their
    file's mtime."""
    urls = [(PAGES_BASE, today, "daily", "1.0")]
    urls += [(f"{PAGES_BASE}venues/{s}.html", today, "daily", "0.8") for s in sorted(slugs)]
    kdir = repo_root / "knowledge"
    if kdir.exists():
        for p in sorted(kdir.rglob("*.html")):
            rel = p.relative_to(repo_root).as_posix()
            mod = date.fromtimestamp(p.stat().st_mtime).isoformat()
            urls.append((f"{PAGES_BASE}{rel}", mod, "weekly", "0.5"))
    items = "\n".join(
        f"  <url><loc>{_esc(u)}</loc><lastmod>{m}</lastmod>"
        f"<changefreq>{c}</changefreq><priority>{pr}</priority></url>"
        for u, m, c, pr in urls)
    (repo_root / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n</urlset>\n")
    (repo_root / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {PAGES_BASE}sitemap.xml\n")
    return len(urls)


def build_md(ranked, now, banner, ctx, mp_climbs, match_sheet_row=None):
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

    lines = [f"# {ctx.trip_name}", "",
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
        nb = nearby_climbs(v, mp_climbs)
        row = match_sheet_row(v["name"]) if match_sheet_row else None
        src = (f"[mp map]({MP_MAP_URL})" + (f" ({len(nb)})" if nb else "")
               + (f" · [sheet r{row}]({SHEET_URL}#gid=0&range={row}:{row})" if row else " · not in sheet"))
        lines.append(f"| {n} | {flag(v['country'])} {v['name']}<br><sub>{src}</sub> | {r['score']} | {cstr} | {fcell(fl.get('michel'))} | {fcell(fl.get('dan'))} |")
    lines += ["", f"_Flights: top {ctx.top_n_flights} venues, return {ctx.rep_combo['out']}→{ctx.rep_combo['back']} ({ctx.rep_combo['nights']}n); "
              f"date options: {ctx.combo_labels}. Use the book links to adjust. "
              f"Stays: OpenStreetMap lodging within {STAY_RADIUS_KM} km per venue (houses, camping, hotels "
              f"for {STAY_ADULTS} adults) on the dashboard's per-venue cards. Rendered dashboard: "
              "https://uncinimichel.github.io/climbing-agent/_"]
    return "\n".join(lines) + "\n"

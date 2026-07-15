"""Weather signals — moved verbatim from update_report.py, parameterized on
TripContext (for the target/graph window and climatology years) and an
optional EnvCache/Cache instead of module-level globals.

Weather signals (free, no key):
  1. CLIMATOLOGY — typical conditions per venue over recent years (Open-Meteo
     archive). Ranks the venues months ahead of the trip.
  2. FORECAST — Open-Meteo 16-day forecast; shown once the trip enters range.
  3. SEASONAL — Open-Meteo's 45-day sub-seasonal outlook, bridging the gap
     between climatology and the live forecast.
"""
import math
from datetime import date, datetime, timedelta

from .http import get_json

CLIMO_VER = "v3"   # bump to re-fetch every venue once (v3: + cloud_cover_mean)

# Named so the client-side weather-chart colouring (rainColor/windColor/
# tempColor in render.py's PAGE_JS) can share these exact numbers instead of
# guessing its own.
COLD_C = 8            # numb-fingers threshold (climo_score)
HEAT_WARM_C = 18       # heat_penalty: gentle slope starts (top of the ideal band)
HEAT_HOT_C = 24        # heat_penalty: steep slope starts
HEAT_BRUTAL_C = 28     # heat_penalty: brutal slope starts
GUST_BAD_KMH = 30      # day_score: gust penalty starts
RAIN_IDEAL_PCT = 12    # rain_penalty: dry-climate comfort band (no penalty below)
RAIN_STEEP_PCT = 40    # rain_penalty: slope steepens for persistent-rain regimes
ENS_WET_MM = 1.0       # ensemble: a member counts as "wet" at ≥ this daily precip (mm)

# Climbing hours (local): rain inside this window costs full price; rain in the
# night BEFORE (previous evening + pre-dawn) only matters through wet rock at
# breakfast, so it's discounted by NIGHT_RAIN_W × the crag's drying factor —
# a shaded sea cliff still pays ~40% of night rain, a sunny fast-drying face ~15%.
CLIMB_H0, CLIMB_H1 = 7, 19   # 07:00–19:59 local
NIGHT_RAIN_W = 0.25

# Felt temperature ON THE ROCK: direct sun on a wall reads far hotter than air
# temp, and a shaded N face climbs cooler — crag aspect × actual sunniness.
# This cuts BOTH ways: in a heatwave the shaded N face is the better call, in a
# cold snap the sunny S face is (day_score penalises heat AND cold on the felt
# temperature, so the aspect shift rewards whichever face fits the day).
ASPECT_ADJ = {"N": -4, "NE": -3, "NW": -2, "E": -1, "W": 2, "SE": 3, "SW": 3, "S": 4}

# Bearing (°) each aspect looks toward — for wind-vs-face exposure.
ASPECT_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def compass(deg):
    """Nearest 8-point compass name for a bearing in degrees."""
    if deg is None:
        return None
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def wind_factor(v, wdir):
    """Multiplier on the gust penalty from where the wind hits the crag. Wind
    blowing straight ONTO the face (meteorological direction ≈ the wall's
    bearing) bites hardest — belays in the blast, ropes blown sideways — while
    a leeward wall is part-sheltered by its own hillside. A `wind_exposed`
    crag (sea cliff, free-standing tower, summit ridge) has nothing to hide
    behind, so it pays a surcharge whichever way the wind blows."""
    f = 1.0
    deg = ASPECT_DEG.get((v.get("aspect") or "").upper())
    if deg is not None and wdir is not None:
        f += 0.25 * math.cos(math.radians(wdir - deg))   # windward +25% … leeward −25%
    if v.get("wind_exposed"):
        f += 0.25
    return f


def drying_factor(v):
    """How slowly this crag's rock dries after rain — a multiplier on the
    wet-rock penalties. Shade and sea air both hold water: a N face never gets
    the drying sun, and a coastal/tidal crag sits in salt-humid air (sea fog,
    spray), while a sunny S face sheds water fastest. An explicit
    `drying: "fast"|"slow"` on the venue overrides the derivation — a curator
    note like Cornwall's 'dries in minutes in a breeze' beats geometry."""
    d = (v.get("drying") or "").lower()
    if d == "fast":
        return 0.7
    if d == "slow":
        return 1.4
    f = 1.0 - ASPECT_ADJ.get((v.get("aspect") or "").upper(), 1) * 0.05  # N +0.2 … S −0.2
    if v.get("coastal") or v.get("tidal"):
        f += 0.25
    return max(0.6, min(1.6, f))


def drying_traits(v):
    """Short human reason for the venue's drying factor ('' when neutral)."""
    bits = []
    asp = (v.get("aspect") or "").upper()
    if ASPECT_ADJ.get(asp, 0) <= -2:
        bits.append(f"shaded {asp} face")
    elif ASPECT_ADJ.get(asp, 0) >= 3:
        bits.append(f"sunny {asp} face")
    if v.get("coastal") or v.get("tidal"):
        bits.append("sea air")
    d = (v.get("drying") or "").lower()
    if d in ("fast", "slow"):
        bits.append(f"dries {d} (curated)")
    return ", ".join(bits)


def forecast(lat, lon, env_cache=None):
    """16-day live forecast (Open-Meteo's max). Beyond the sky/temp/wind basics we pull
    climbing-quality signals — gusts (exposed multi-pitch), sunshine + precip_hours (rock
    drying), and hourly dewpoint/humidity (friction / 'grease'). All free, one request.
    Served from the venue-env cache when present (fetch_env.py), else fetched live."""
    cached = env_cache.raw(lat, lon, "forecast") if env_cache else None
    if cached is not None:
        return cached
    return get_json(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,precipitation_hours,"
        "windspeed_10m_max,wind_gusts_10m_max,winddirection_10m_dominant,"
        "sunshine_duration,daylight_duration,uv_index_max,cloud_cover_mean"
        "&hourly=dewpoint_2m,relative_humidity_2m,precipitation,"
        "temperature_2m,weathercode,precipitation_probability,"
        "windspeed_10m,wind_gusts_10m,is_day"
        "&timezone=auto&forecast_days=16"
    )


def tides(lat, lon):
    """Hourly tidal sea level (Open-Meteo Marine — free, keyless). Chosen over the
    RapidAPI endpoint multi-pitch.com's lambda uses: that key is shared with the
    live site's daily quota and only returns 24 h per call (decision #22). The
    marine model carries real values ~10 days out; hours beyond come back null."""
    return get_json(
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=sea_level_height_msl&forecast_days=16&timezone=auto"
    )


def tide_extremes(lat, lon, env_cache=None):
    """High/low water from the hourly tide curve, keyed by local ISO date:
    {"2026-07-22": [{"t":"HH:MM","h":metres_vs_MSL,"k":"H"|"L"}, ...], ...}.
    Each turning point's time/height is refined by fitting a parabola through
    the three hours around it — the raw hourly grid would put high water up to
    30 min off, which matters for a tide-window call.
    Served from the venue-env cache when present (fetch_env.py), else derived live."""
    cached = env_cache.raw(lat, lon, "tides") if env_cache else None
    if cached is not None:
        return cached
    d = tides(lat, lon).get("hourly") or {}
    ts, vs = d.get("time") or [], d.get("sea_level_height_msl") or []
    out = {}
    for i in range(1, min(len(ts), len(vs)) - 1):
        v0, v1, v2 = vs[i - 1], vs[i], vs[i + 1]
        if None in (v0, v1, v2):
            continue
        hi = v1 >= v0 and v1 > v2
        if not hi and not (v1 <= v0 and v1 < v2):
            continue
        den = v0 - 2 * v1 + v2                       # 2a of the fitted parabola
        off = (v0 - v2) / (2 * den) if den else 0.0  # vertex, hours from ts[i]
        h = v1 - (v2 - v0) ** 2 / (8 * den) if den else v1
        when = datetime.fromisoformat(ts[i]) + timedelta(hours=off)
        out.setdefault(when.date().isoformat(), []).append(
            {"t": when.strftime("%H:%M"), "h": round(h, 1), "k": "H" if hi else "L"})
    return out


def climatology(lat, lon, ctx, cache=None):
    """Typical trip-window conditions over recent years — ONE ranged request, filtered.
    Days are matched by real (month, day) against the graph/trip windows, so this stays
    correct even when the trip straddles a month boundary (e.g. 30 Jul–3 Aug)."""
    years = ctx.climo_years
    graph_start, graph_end = ctx.graph_start, ctx.graph_end
    graph_md, trip_md = ctx.graph_md, ctx.trip_md
    ck = f"{lat},{lon}|{years[0]}-{years[-1]}|{graph_start:%m%d}-{graph_end:%m%d}|{CLIMO_VER}"
    cached = cache.get(ck) if cache else None
    if cached is not None:
        return cached
    d = get_json(
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={years[0]}-{graph_start:%m-%d}&end_date={years[-1]}-{graph_end:%m-%d}"
        "&daily=temperature_2m_max,precipitation_sum,windspeed_10m_max,winddirection_10m_dominant,"
        "cloud_cover_mean&timezone=auto"
    )["daily"]
    tmaxs, winds, rain_days, total = [], [], 0, 0
    per_day = {}   # (month, day) -> {"t","p","w"} lists for the graph window
    dirs = d.get("winddirection_10m_dominant") or [None] * len(d["time"])
    clouds = d.get("cloud_cover_mean") or [None] * len(d["time"])
    for t, tx, pr, wd, wdir, cc in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"],
                                       d.get("windspeed_10m_max", [None] * len(d["time"])), dirs, clouds):
        dd = date.fromisoformat(t)
        md = (dd.month, dd.day)
        if tx is None:
            continue
        if md in graph_md:                       # graph window (trip ±2)
            e = per_day.setdefault(md, {"t": [], "p": [], "w": []})
            e["t"].append(tx)
            e["p"].append(pr or 0)
            e["w"].append(wd or 0)
            if cc is not None:
                e.setdefault("c", []).append(cc)
            if wdir is not None:
                e.setdefault("dx", []).append(math.cos(math.radians(wdir)))
                e.setdefault("dy", []).append(math.sin(math.radians(wdir)))
        if md in trip_md:                        # trip window aggregate
            total += 1
            tmaxs.append(tx)
            winds.append(wd or 0)
            if (pr or 0) >= 3:
                rain_days += 1
    if not total:
        return None
    series, day = [], graph_start
    while day <= graph_end:
        md = (day.month, day.day)
        pd = per_day.get(md)
        if pd:
            series.append({"day": day.day, "month": day.month,
                           "tmax": round(sum(pd["t"]) / len(pd["t"])),
                           "precip": round(sum(pd["p"]) / len(pd["p"]), 1),
                           "wind": round(sum(pd["w"]) / len(pd["w"])),
                           "cloud": (round(sum(pd["c"]) / len(pd["c"]))
                                     if pd.get("c") else None),
                           "dir": (round(math.degrees(math.atan2(sum(pd["dy"]), sum(pd["dx"]))) % 360)
                                   if pd.get("dx") else None),
                           "trip": md in trip_md})
        day += timedelta(days=1)
    out = {"tmax": round(sum(tmaxs) / len(tmaxs)), "rain_pct": round(100 * rain_days / total),
           "wind": round(sum(winds) / len(winds)), "days": total, "series": series}
    if cache:
        cache.set(ck, out)
    return out


def seasonal_raw(lat, lon, env_cache=None):
    """Raw Open-Meteo seasonal response — served from the venue-env cache when present
    (fetch_env.py), else fetched live. Split out so the cache can hold the raw payload."""
    cached = env_cache.raw(lat, lon, "seasonal") if env_cache else None
    if cached is not None:
        return cached
    return get_json(
        "https://seasonal-api.open-meteo.com/v1/seasonal"
        f"?latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_max,precipitation_sum,cloud_cover_mean&forecast_days=45&timezone=auto"
    )


def seasonal(lat, lon, ctx, env_cache=None):
    """Sub-seasonal (45-day) outlook for the trip window from Open-Meteo's free
    Seasonal Forecast API (CFS ensemble, no key). Averages the ensemble members."""
    d = seasonal_raw(lat, lon, env_cache)["daily"]
    times = d["time"]
    tkeys = [k for k in d if k.startswith("temperature_2m_max")]
    pkeys = [k for k in d if k.startswith("precipitation_sum")]
    ckeys = [k for k in d if k.startswith("cloud_cover_mean")]
    tmaxs, precs, wet, total = [], [], 0, 0
    daily = {}   # (month, day) -> ensemble-mean {tmax, precip, cloud} for the graph window
    graph_md = ctx.graph_md
    for i, day in enumerate(times):
        dd = date.fromisoformat(day)
        gvals = [d[k][i] for k in tkeys if i < len(d[k]) and d[k][i] is not None]
        gp = [d[k][i] for k in pkeys if i < len(d[k]) and d[k][i] is not None]
        gc = [d[k][i] for k in ckeys if i < len(d[k]) and d[k][i] is not None]
        if gvals and (dd.month, dd.day) in graph_md:
            daily[(dd.month, dd.day)] = {
                "tmax": round(sum(gvals) / len(gvals)),
                "precip": round(sum(gp) / len(gp) if gp else 0, 1),
                "cloud": (round(sum(gc) / len(gc)) if gc else None)}
        if not (ctx.target_start <= dd <= ctx.target_end):
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


def ensemble_raw(lat, lon, env_cache=None):
    """Raw Open-Meteo ECMWF-ENS response (51 members) — served from the venue-env cache
    when present (fetch_env.py), else fetched live. This is the honest signal for the
    ~day-7-to-16 tail: a single deterministic run is noise there (the top models split
    from bone-dry to soaking on the *same* day), but the member spread gives a real,
    frequency-based P(rain) and a temperature range. Free, keyless — one request."""
    cached = env_cache.raw(lat, lon, "ensemble") if env_cache else None
    if cached is not None:
        return cached
    return get_json(
        "https://ensemble-api.open-meteo.com/v1/ensemble"
        f"?latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_max,precipitation_sum&models=ecmwf_ifs025"
        "&forecast_days=16&timezone=auto"
    )


def ensemble_metrics(d, wet_mm=ENS_WET_MM):
    """Per-ISO-date confidence signals from an ECMWF-ENS response, keyed by date:
      p_rain   — % of members with daily precip ≥ wet_mm (a member-based rain
                 probability — strictly better than guessing from the weathercode
                 where the deterministic precipitation_probability_max drops out).
      tmax_lo/hi/mean/sd — the member temperature spread = forecast confidence.
    Best-effort: any date without members is skipped; a missing/failed ensemble
    (d is None or has no member columns) just yields {}."""
    daily = (d or {}).get("daily") or {}
    times = daily.get("time") or []
    tkeys = [k for k in daily if k.startswith("temperature_2m_max")]
    pkeys = [k for k in daily if k.startswith("precipitation_sum")]
    out = {}
    for i, ds in enumerate(times):
        tv = [daily[k][i] for k in tkeys if i < len(daily[k]) and daily[k][i] is not None]
        pv = [daily[k][i] for k in pkeys if i < len(daily[k]) and daily[k][i] is not None]
        if not tv:
            continue
        mean = sum(tv) / len(tv)
        sd = (sum((x - mean) ** 2 for x in tv) / len(tv)) ** 0.5
        rec = {"tmax_lo": round(min(tv)), "tmax_hi": round(max(tv)),
               "tmax_mean": round(mean), "tmax_sd": round(sd, 1), "members": len(tv)}
        if pv:
            rec["p_rain"] = round(100 * sum(1 for x in pv if x >= wet_mm) / len(pv))
        out[ds] = rec
    return out


def hourly_by_date(d):
    """Compact per-date hourly strip for the frontend's hour-by-hour panel:
    {ISO date: 24 × [temp°C, mm, prob%, weathercode, wind, gust, is_day]},
    where the array index IS the venue-local hour (the fetch uses
    timezone=auto, so the hourly time strings are already crag-local — never
    re-parse them through a Date object). Hours with no temperature stay None;
    dates with no data at all are omitted."""
    h = (d or {}).get("hourly") or {}
    ts = h.get("time") or []
    cols = [h.get(k) or [] for k in
            ("temperature_2m", "precipitation", "precipitation_probability",
             "weathercode", "windspeed_10m", "wind_gusts_10m", "is_day")]

    def g(col, j, f):
        return f(col[j]) if j < len(col) and col[j] is not None else None
    out = {}
    for j, s in enumerate(ts):
        if len(s) < 13:
            continue
        ds, hr = s[:10], int(s[11:13])
        t = g(cols[0], j, round)
        if t is None or not 0 <= hr <= 23:
            continue
        out.setdefault(ds, [None] * 24)[hr] = [
            t, g(cols[1], j, lambda x: round(x, 1)), g(cols[2], j, round),
            g(cols[3], j, int), g(cols[4], j, round), g(cols[5], j, round),
            g(cols[6], j, int)]
    return out


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


def code_rain_prob(code):
    """Fallback rain probability (%) inferred from the WMO weathercode, for the
    16-day horizon edge where Open-Meteo drops precipitation_probability_max
    (returns None). Without this, a None probability reads as 0% rain and a
    drizzly edge day scores ~perfect — the Dolomites bug. The code still carries
    the sky state, so a drizzle/rain code keeps its penalty even with no prob."""
    if code is None:
        return 0
    if code >= 95:      # thunderstorm
        return 90
    if code >= 80:      # rain showers
        return 75
    if code >= 71:      # snow
        return 80
    if code >= 61:      # rain
        return 80
    if code >= 51:      # drizzle
        return 60
    if code >= 45:      # fog
        return 40
    if code >= 1:       # partly → overcast
        return 20
    return 5            # clear sky


def effective_rain_prob(prob, code, ens_prob=None):
    """Rain probability, best source first: the model's own probability when present
    (near term), else the ECMWF-ensemble member fraction (`ens_prob`, the honest
    horizon-edge signal), else inferred from the weathercode. Shared by day_score
    and the rain sub-signal so the score and the widget agree."""
    if prob is not None:
        return prob
    if ens_prob is not None:
        return ens_prob
    return code_rain_prob(code)


def day_rain_penalty(prob, tol=1.0):
    """Forecast rain-probability → points off. Keeps the gentle 0.8/pt base for
    uncertain days but steepens past 50%, in the same spirit as the climatology
    rain curve (rain_penalty) — so a high-chance-of-rain trip day is penalised
    consistently across horizons, while the weather-code caps below still handle
    'it will definitely rain'. Only ADDS penalty above 50%, so a dry forecast is
    never pushed down. tol = user rain-tolerance (>1 = softer)."""
    prob = prob or 0
    return (prob * 0.8 + max(0, prob - 50) * 0.7) / (tol or 1.0)


def day_score(code, mm, prob, m=None, rain_tol=1.0, heat_tol=1.0):
    """0–100 for a single forecast day. Base = rain probability + amount + storm caps.
    `m` (optional) carries the richer signals — gusts, wet-hours, sunshine (drying) and
    dewpoint (friction) — each a gentle, bounded nudge so ranking never swings wildly.
    rain_tol/heat_tol are user-preference multipliers (>1 = more tolerant), 1.0 = neutral.
    When `m` carries an ensemble `ens_prob` (ECMWF member fraction), it supersedes the
    weathercode guess for the rain base — the confidence signal for the horizon edge.

    When `m` carries the hourly day/night split (rain_day / rain_night /
    wet_hrs_day / prob_day from forecast_metrics), rain is charged by WHEN it
    falls: climbing-window rain at full price, night-before rain discounted to
    NIGHT_RAIN_W × drying factor (a dry sunny day after a wet night is a
    climbing day, not a washout), and the daily-weathercode rain caps only fire
    when the climbing window itself is wet — a code-61 day whose rain fell
    entirely overnight no longer bottoms out at 25."""
    ens_prob = m.get("ens_prob") if m else None
    split = m is not None and m.get("rain_day") is not None
    # rain probability: prefer the climbing-window max over the 24h daily max,
    # so a 90%-chance-overnight day doesn't read as a 90%-chance climbing day
    p = m["prob_day"] if (split and m.get("prob_day") is not None) else prob
    if split:
        night_w = max(0.15, min(0.5, NIGHT_RAIN_W * m.get("dry_f", 1.0)))
        mm_pen = m["rain_day"] * 6 + (m.get("rain_night") or 0) * 6 * night_w
    else:
        mm_pen = (mm or 0) * 6
    s = 100.0 - day_rain_penalty(effective_rain_prob(p, code, ens_prob), rain_tol) - mm_pen
    day_wet = (m["rain_day"] >= 0.5 or (m.get("wet_hrs_day") or 0) >= 1) if split else True
    if code is not None and code >= 61 and day_wet:
        s = min(s, 25)
    if code in (95, 96, 99) and day_wet:
        s = min(s, 15)
    if m:
        if m.get("gust") is not None:            # gusts bite on exposed routes / sea-cliffs —
            # scaled by wind-vs-face exposure (windward wall > leeward, asp_m)
            s -= max(0, m["gust"] - GUST_BAD_KMH) * 0.6 * m.get("wind_f", 1.0)  # 50 km/h ≈ −12
        if m.get("wet_hrs_day") is not None:      # hours of rain INSIDE the climbing
            # window — scaled by how slowly this rock dries (shade / sea air, asp_m)
            s -= min(m["wet_hrs_day"], 12) * 0.8 * m.get("dry_f", 1.0)
        elif m.get("precip_hours") is not None:   # pre-split fallback: 24h wet hours
            s -= min(m["precip_hours"], 12) * 0.8 * m.get("dry_f", 1.0)  # up to ≈ −10 neutral
        if m.get("sun_frac") is not None:         # sun dries rock → reward, dull → penalise
            s += (m["sun_frac"] - 0.5) * 10        # ±5
        if m.get("dew") is not None:              # friction / grease
            s -= max(0, m["dew"] - 12) * 1.2       # dew 20 ≈ −10
        if m.get("tmax") is not None:             # same climbing heat + cold curves as
            s -= heat_penalty(m["tmax"]) / (heat_tol or 1.0)   # climatology — on the FELT
            s -= max(0, COLD_C - m["tmax"]) * 2    # temp, so aspect helps either extreme
    return max(0.0, min(100.0, s))


def heat_penalty(tmax):
    """Climbing-specific heat curve. Friction research puts ideal sending temps at
    ~7–18°C (climbing.com 'Science of Friction'; UKC conditions threads agree);
    rubber and skin grease out past ~18–24°C, and multi-pitch means HOURS exposed
    on the wall with no shade retreat. Slopes bite from the top of the ideal band:
    gentle from 18°C, steep from 24°C, brutal from 28°C — a 25°C felt-on-rock venue
    loses ~15 points, a 31°C coastal venue ~66. Deliberately harsher than the rain
    curve is generous: on multi-pitch, hours of baking heat outweigh a chance of
    showers, so a dry-but-hot venue should not out-rank a cool-but-showery one."""
    return (max(0, tmax - HEAT_WARM_C) * 1.5
            + max(0, tmax - HEAT_HOT_C) * 4
            + max(0, tmax - HEAT_BRUTAL_C) * 6)


def rain_penalty(pct, tol=1.0):
    """Wet-day % → points off, mirroring the heat curve's shape: a dry-climate
    comfort band (no penalty below ~12% wet days), a gentle slope, then a steep
    one for persistent-rain regimes. Deliberately symmetric with heat_penalty so
    a cool-but-wet venue is punished as hard as a dry-but-hot one — neither
    should out-rank a cool, dry venue. Tuned on the historical backtest
    (trip-ni-july-2026/scripts/backtest_ranking.py): 40%+ wet days drops a venue
    out of the top tier (Fair Head 46% ≈ −48), 55% ≈ −76, 67% bottoms out; a
    <12%-wet desert stays untouched. tol = user rain-tolerance (>1 = softer)."""
    pct = pct or 0
    return (max(0, pct - RAIN_IDEAL_PCT) * 1.25
            + max(0, pct - RAIN_STEEP_PCT) * 1.5) / (tol or 1.0)


def climo_score(c, rain_tol=1.0, heat_tol=1.0, dry_f=1.0):
    # dry_f (drying_factor): slow-drying rock loses more per typical wet day —
    # half-weighted here, since climatology already averages over dry-out days
    s = 100 - rain_penalty(c["rain_pct"], rain_tol) * (1 + (dry_f - 1) * 0.5)
    s -= max(0, COLD_C - c["tmax"]) * 2      # too cold: numb fingers below ~8°C
    s -= heat_penalty(c["tmax"]) / (heat_tol or 1.0)
    return max(0, min(100, round(s)))


def sun_adjusted_tmax(v, tmax, sun_frac=None):
    """Aspect comes from venues.json / GAZETTEER ('aspect'; unknown → mild +1 sun
    bump). Sunniness = forecast sunshine fraction when live, dryness as a proxy
    for the climatology/outlook horizons."""
    if tmax is None:
        return tmax
    adj = ASPECT_ADJ.get((v.get("aspect") or "").upper(), 1)
    s = 0.7 if sun_frac is None else max(0.0, min(1.0, sun_frac))
    return tmax + adj * s


def asp_m(v, m):
    """Fold the venue's physical character into a live-forecast day's metrics:
    aspect/sun felt temperature, wind-vs-face gust exposure, drying speed."""
    if not m:
        return m
    m = dict(m)
    if m.get("tmax") is not None:
        m["tmax"] = sun_adjusted_tmax(v, m["tmax"], m.get("sun_frac"))
    m["wind_f"] = wind_factor(v, m.get("wdir"))
    m["dry_f"] = drying_factor(v)
    return m


def forecast_metrics(d):
    """Per-day derived climbing signals from a forecast response, keyed by ISO date.
    Daily gives gusts / sunshine / precip-hours; hourly dewpoint+humidity are averaged
    over daytime (09–18 local) for friction, and 07–12 dryness flags an AM window.
    Hourly precipitation is also split around the climbing day (CLIMB_H0–H1 local):
      rain_day    — mm that falls while you'd actually be on the rock
      rain_night  — mm in the night BEFORE (previous evening 20–24 + pre-dawn 00–07),
                    which only matters through how wet the rock still is at breakfast
      wet_hrs_day — climbing-window hours with ≥0.2 mm (the honest precip_hours)
      prob_day    — max hourly rain probability inside the climbing window
    All hourly timestamps are venue-LOCAL (the fetch uses timezone=auto).
    Everything is best-effort — any missing field just yields None for that signal."""
    daily = d.get("daily", {})
    times = daily.get("time", [])
    gusts = daily.get("wind_gusts_10m_max") or [None] * len(times)
    wdirs = daily.get("winddirection_10m_dominant") or [None] * len(times)
    sun = daily.get("sunshine_duration") or [None] * len(times)
    daylt = daily.get("daylight_duration") or [None] * len(times)
    phours = daily.get("precipitation_hours") or [None] * len(times)

    # aggregate hourly dewpoint/humidity/precip into per-date daytime means
    h = d.get("hourly", {})
    htime = h.get("time", [])
    hdew, hhum, hpre = (h.get("dewpoint_2m") or [], h.get("relative_humidity_2m") or [],
                        h.get("precipitation") or [])
    hprob = h.get("precipitation_probability") or []
    day_dew, day_hum, am_wet = {}, {}, {}
    day_mm, eve_mm, dawn_mm, wet_hrs, day_prob = {}, {}, {}, {}, {}
    for j, ts in enumerate(htime):
        date_s, hr = ts[:10], int(ts[11:13]) if len(ts) >= 13 else 0
        if 9 <= hr <= 18:
            if j < len(hdew) and hdew[j] is not None:
                day_dew.setdefault(date_s, []).append(hdew[j])
            if j < len(hhum) and hhum[j] is not None:
                day_hum.setdefault(date_s, []).append(hhum[j])
        if 7 <= hr <= 12 and j < len(hpre) and (hpre[j] or 0) >= 0.2:
            am_wet[date_s] = True
        mm = hpre[j] if j < len(hpre) and hpre[j] is not None else None
        if mm is not None:
            if CLIMB_H0 <= hr <= CLIMB_H1:
                day_mm[date_s] = day_mm.get(date_s, 0.0) + mm
                if mm >= 0.2:
                    wet_hrs[date_s] = wet_hrs.get(date_s, 0) + 1
            elif hr > CLIMB_H1:
                eve_mm[date_s] = eve_mm.get(date_s, 0.0) + mm
            else:
                dawn_mm[date_s] = dawn_mm.get(date_s, 0.0) + mm
        if (CLIMB_H0 <= hr <= CLIMB_H1 and j < len(hprob)
                and hprob[j] is not None):
            day_prob[date_s] = max(day_prob.get(date_s, 0), hprob[j])

    tmaxs = daily.get("temperature_2m_max") or [None] * len(times)
    have_split = bool(day_mm or eve_mm or dawn_mm)
    out = {}
    for i, ds in enumerate(times):
        dew = round(sum(day_dew[ds]) / len(day_dew[ds]), 1) if day_dew.get(ds) else None
        hum = round(sum(day_hum[ds]) / len(day_hum[ds])) if day_hum.get(ds) else None
        sf = (sun[i] / daylt[i]) if (sun[i] is not None and daylt[i]) else None
        # night-before rain = previous date's evening + this date's pre-dawn
        night = None
        if have_split:
            prev = (date.fromisoformat(ds) - timedelta(days=1)).isoformat() if len(ds) == 10 else None
            night = round(eve_mm.get(prev, 0.0) + dawn_mm.get(ds, 0.0), 1)
        out[ds] = {
            "tmax": tmaxs[i],
            "gust": round(gusts[i]) if gusts[i] is not None else None,
            "wdir": round(wdirs[i]) if wdirs[i] is not None else None,
            "sun_frac": round(sf, 2) if sf is not None else None,
            "precip_hours": round(phours[i], 1) if phours[i] is not None else None,
            "dew": dew, "humid": hum,
            "am_dry": (ds in am_wet) is False if htime else None,
            "friction": friction_label(dew),
            "rain_day": round(day_mm.get(ds, 0.0), 1) if have_split else None,
            "rain_night": night,
            "wet_hrs_day": wet_hrs.get(ds, 0) if have_split else None,
            "prob_day": day_prob.get(ds) if day_prob else None,
        }
    return out

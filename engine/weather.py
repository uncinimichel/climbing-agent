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

# Felt temperature ON THE ROCK: direct sun on a wall reads far hotter than air
# temp, and a shaded N face climbs cooler — crag aspect × actual sunniness.
ASPECT_ADJ = {"N": -4, "NE": -3, "NW": -2, "E": -1, "W": 2, "SE": 3, "SW": 3, "S": 4}


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
        "&hourly=dewpoint_2m,relative_humidity_2m,precipitation"
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


def effective_rain_prob(prob, code):
    """Use the real forecast probability when present, else infer it from the
    weathercode (horizon edge). Shared by day_score and the rain sub-signal so
    the score and the widget agree."""
    return prob if prob is not None else code_rain_prob(code)


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
    rain_tol/heat_tol are user-preference multipliers (>1 = more tolerant), 1.0 = neutral."""
    s = 100.0 - day_rain_penalty(effective_rain_prob(prob, code), rain_tol) - (mm or 0) * 6
    if code is not None and code >= 61:
        s = min(s, 25)
    if code in (95, 96, 99):
        s = min(s, 15)
    if m:
        if m.get("gust") is not None:            # gusts bite on exposed routes / sea-cliffs
            s -= max(0, m["gust"] - GUST_BAD_KMH) * 0.6     # 50 km/h ≈ −12
        if m.get("precip_hours") is not None:     # hours of rain, not just total mm
            s -= min(m["precip_hours"], 12) * 0.8  # up to ≈ −10
        if m.get("sun_frac") is not None:         # sun dries rock → reward, dull → penalise
            s += (m["sun_frac"] - 0.5) * 10        # ±5
        if m.get("dew") is not None:              # friction / grease
            s -= max(0, m["dew"] - 12) * 1.2       # dew 20 ≈ −10
        if m.get("tmax") is not None:             # same climbing heat curve as climatology
            s -= heat_penalty(m["tmax"]) / (heat_tol or 1.0)
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


def climo_score(c, rain_tol=1.0, heat_tol=1.0):
    s = 100 - rain_penalty(c["rain_pct"], rain_tol)
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

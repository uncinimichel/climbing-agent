"""Weather providers — the fetch layer. Sport-agnostic and free (no keys).

Everything here answers "what does the atmosphere do at this lat/lon?", on three
horizons that hand over to each other as a trip approaches:
  1. CLIMATOLOGY — typical conditions per venue over recent years (Open-Meteo
     archive). Ranks venues months ahead of the trip.
  2. SEASONAL — Open-Meteo's 45-day sub-seasonal outlook, bridging the gap.
  3. FORECAST — Open-Meteo 16-day forecast; supersedes once the trip is in range.
Plus the ECMWF ensemble (confidence at the horizon edge) and marine tides.

No scoring lives here. Turning these numbers into "is it a good day for X" is
each domain's job (see domains/<sport>/conditions.py); the shared derived
signals live in core.weather.metrics.
"""
import math
from datetime import date, datetime, timedelta

from ..http import get_json

CLIMO_VER = "v3"   # bump to re-fetch every venue once (v3: + cloud_cover_mean)


def forecast(lat, lon, env_cache=None):
    """16-day live forecast (Open-Meteo's max). Beyond the sky/temp/wind basics we pull
    the signals outdoor sports actually turn on — gusts (exposure), sunshine +
    precip_hours (drying), and hourly dewpoint/humidity (grip). All free, one request.
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

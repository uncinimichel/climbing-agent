"""Derived weather signals — sport-agnostic.

The rule that draws the line between this module and a domain's conditions
module: **core computes physical quantities, domains interpret them.** Dewpoint
belongs here; whether 14°C dewpoint means "greasy rock" or "soft greens" is the
domain's call. Same for gusts, wet hours and sunshine fraction.

The one thing a sport genuinely changes about the *physics* is WHEN it happens:
climbing rain at 03:00 is a different event from rain at 13:00. So the active
window is a parameter (`active_hours`) rather than a constant, and rain is split
around it into during / night-before buckets. Everything else stays fixed.
"""
import math
from datetime import date, timedelta

# A member counts as "wet" at ≥ this daily precip (mm) in an ensemble run.
ENS_WET_MM = 1.0

# Windows used for the generic derived fields. These are daylight conventions,
# not sport rules — a sport that needs a different active window passes
# `active_hours`; these two only shape the humidity mean and the AM-dry flag.
DAYTIME_H = (9, 18)     # dewpoint / humidity averaging window (local hours)
MORNING_H = (7, 12)     # "was the morning dry?" window (local hours)


def compass(deg):
    """Nearest 8-point compass name for a bearing in degrees."""
    if deg is None:
        return None
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


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
    horizon-edge signal), else inferred from the weathercode. Shared by every
    sport's day score and the widgets so score and display agree."""
    if prob is not None:
        return prob
    if ens_prob is not None:
        return ens_prob
    return code_rain_prob(code)


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


def forecast_metrics(d, active_hours=(7, 19)):
    """Per-day derived signals from a forecast response, keyed by ISO date.
    Daily gives gusts / sunshine / precip-hours; hourly dewpoint+humidity are
    averaged over DAYTIME_H for humidity, and MORNING_H dryness flags an AM window.
    Hourly precipitation is split around `active_hours` — the window the sport is
    actually outdoors in (local hours, inclusive):
      rain_day    — mm that falls while you'd actually be out
      rain_night  — mm in the night BEFORE (previous evening after the window +
                    this date's pre-dawn), which only matters through how wet the
                    ground/rock still is at breakfast
      wet_hrs_day — active-window hours with ≥0.2 mm (the honest precip_hours)
      prob_day    — max hourly rain probability inside the active window
    All hourly timestamps are venue-LOCAL (the fetch uses timezone=auto).
    Everything is best-effort — any missing field just yields None for that signal."""
    h0, h1 = active_hours
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
        if DAYTIME_H[0] <= hr <= DAYTIME_H[1]:
            if j < len(hdew) and hdew[j] is not None:
                day_dew.setdefault(date_s, []).append(hdew[j])
            if j < len(hhum) and hhum[j] is not None:
                day_hum.setdefault(date_s, []).append(hhum[j])
        if MORNING_H[0] <= hr <= MORNING_H[1] and j < len(hpre) and (hpre[j] or 0) >= 0.2:
            am_wet[date_s] = True
        mm = hpre[j] if j < len(hpre) and hpre[j] is not None else None
        if mm is not None:
            if h0 <= hr <= h1:
                day_mm[date_s] = day_mm.get(date_s, 0.0) + mm
                if mm >= 0.2:
                    wet_hrs[date_s] = wet_hrs.get(date_s, 0) + 1
            elif hr > h1:
                eve_mm[date_s] = eve_mm.get(date_s, 0.0) + mm
            else:
                dawn_mm[date_s] = dawn_mm.get(date_s, 0.0) + mm
        if (h0 <= hr <= h1 and j < len(hprob)
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
            "rain_day": round(day_mm.get(ds, 0.0), 1) if have_split else None,
            "rain_night": night,
            "wet_hrs_day": wet_hrs.get(ds, 0) if have_split else None,
            "prob_day": day_prob.get(ds) if day_prob else None,
        }
    return out


def circular_mean_deg(degrees):
    """Mean of a list of bearings (°), handling the 359°/1° wrap. None if empty."""
    ds = [x for x in degrees if x is not None]
    if not ds:
        return None
    return round(math.degrees(math.atan2(
        sum(math.sin(math.radians(x)) for x in ds),
        sum(math.cos(math.radians(x)) for x in ds))) % 360)

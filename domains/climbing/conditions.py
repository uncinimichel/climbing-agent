"""What the weather means FOR CLIMBING.

core/weather hands over physical numbers — °C, mm, km/h gusts, dewpoint, hours
of rain. This module is where they become a climbing judgement: that 26°C in
full sun on a south face is worse than 26°C in shade, that a shaded sea cliff
still holds damp at breakfast after overnight rain, that 17°C dewpoint means
greasy rock whatever the sun is doing.

Every threshold, curve and weighting here is climbing's alone, and deliberately
NOT shared with any other sport. A ski or golf domain writes its own — even
where the shape looks similar — so that changing how climbing scores heat can
never move a golf ranking, and so one person (or one agent) can own this file
end to end without reading anything outside domains/climbing/.
"""
import math
import re

from core.weather import metrics

# Named so the client-side weather-chart colouring (rainColor/windColor/
# tempColor in render.py's PAGE_JS) can share these exact numbers instead of
# guessing its own.
COLD_C = 12           # numb-fingers threshold (climo_score): hands lose grip on
                      # cold rock well before 8°C; below ~12°C felt costs points.
                      # Bites cold/winter conditions (any season); summer venues
                      # sit above it, so the warm-season order is barely touched.
HEAT_WARM_C = 18       # heat_penalty: gentle slope starts (top of the ideal band)
HEAT_HOT_C = 24        # heat_penalty: steep slope starts
HEAT_BRUTAL_C = 28     # heat_penalty: brutal slope starts
GUST_BAD_KMH = 30      # day_score: gust penalty starts
RAIN_IDEAL_PCT = 12    # rain_penalty: dry-climate comfort band (no penalty below)
RAIN_STEEP_PCT = 40    # rain_penalty: slope steepens for persistent-rain regimes

# Climbing hours (local): rain inside this window costs full price; rain in the
# night BEFORE (previous evening + pre-dawn) only matters through wet rock at
# breakfast, so it's discounted by NIGHT_RAIN_W × the crag's drying factor —
# a shaded sea cliff still pays ~40% of night rain, a sunny fast-drying face ~15%.
CLIMB_H0, CLIMB_H1 = 7, 19   # 07:00–19:59 local
ACTIVE_HOURS = (CLIMB_H0, CLIMB_H1)
NIGHT_RAIN_W = 0.25

# Felt temperature ON THE ROCK: direct sun on a wall reads far hotter than air
# temp, and a shaded N face climbs cooler — crag aspect × actual sunniness.
# This cuts BOTH ways: in a heatwave the shaded N face is the better call, in a
# cold snap the sunny S face is (day_score penalises heat AND cold on the felt
# temperature, so the aspect shift rewards whichever face fits the day).
ASPECT_ADJ = {"N": -4, "NE": -3, "NW": -2, "E": -1, "W": 2, "SE": 3, "SW": 3, "S": 4}

# Bearing (°) each aspect looks toward — for wind-vs-face exposure.
ASPECT_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
ASPECT_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")   # clockwise


# ── aspect: one face, several faces, or every face ──────────────────────────
# A venue's `aspect` (venues.json / GAZETTEER) is a source-stated compass
# facing. A single crag is one point ("S"). An AREA whose walls look different
# ways lists them slash-joined, dominant first ("S/SW/NW" — the Dolomites), and
# a free-standing tower or dome that has a wall in every direction says "all".
# Every consumer below goes through these helpers, so the scoring, the tag chip
# and the compass-rose widget all read the field the same way.

def aspect_points(aspect):
    """Compass points an `aspect` value names, in the order written; [] when
    unknown. 'all' → all eight."""
    if not aspect:
        return []
    s = str(aspect).strip().upper()
    if s in ("ALL", "*", "ANY"):
        return list(ASPECT_POINTS)
    out = []
    for tok in re.split(r"[/,+|\s]+", s):
        if tok in ASPECT_DEG and tok not in out:
            out.append(tok)
    return out


def aspect_label(aspect):
    """Display form: 'S', 'S/SW', or 'all' — '' when unknown."""
    pts = aspect_points(aspect)
    if not pts:
        return ""
    return "all" if len(pts) == len(ASPECT_POINTS) else "/".join(pts)


def aspect_adj(aspect, default=1):
    """Felt-temperature shift in full sun (°C): the mean over the listed faces
    (an 'all' tower nets to ~0). `default` when the aspect is unknown — the
    callers' historical mild +1 sun bump."""
    pts = aspect_points(aspect)
    if not pts:
        return default
    return sum(ASPECT_ADJ[p] for p in pts) / len(pts)


def aspect_windward(aspect, wdir):
    """Mean of cos(wind − face) over the listed faces: +1 wind straight onto the
    wall … −1 fully leeward; 0 when unknown or when the faces cancel out
    (a tower always has a lee side)."""
    pts = aspect_points(aspect)
    if not pts or wdir is None:
        return 0.0
    return sum(math.cos(math.radians(wdir - ASPECT_DEG[p])) for p in pts) / len(pts)


# ── the crag's physical character ────────────────────────────────────────────

def wind_factor(v, wdir):
    """Multiplier on the gust penalty from where the wind hits the crag. Wind
    blowing straight ONTO the face (meteorological direction ≈ the wall's
    bearing) bites hardest — belays in the blast, ropes blown sideways — while
    a leeward wall is part-sheltered by its own hillside. A `wind_exposed`
    crag (sea cliff, free-standing tower, summit ridge) has nothing to hide
    behind, so it pays a surcharge whichever way the wind blows."""
    f = 1.0 + 0.25 * aspect_windward(v.get("aspect"), wdir)   # windward +25% … leeward −25%
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
    f = 1.0 - aspect_adj(v.get("aspect"), 1) * 0.05  # N +0.2 … S −0.2
    if v.get("coastal") or v.get("tidal"):
        f += 0.25
    return max(0.6, min(1.6, f))


def drying_traits(v):
    """Short human reason for the venue's drying factor ('' when neutral)."""
    bits = []
    asp, adj = aspect_label(v.get("aspect")), aspect_adj(v.get("aspect"), 0)
    if adj <= -2:
        bits.append(f"shaded {asp} face")
    elif adj >= 3:
        bits.append(f"sunny {asp} face")
    if v.get("coastal") or v.get("tidal"):
        bits.append("sea air")
    d = (v.get("drying") or "").lower()
    if d in ("fast", "slow"):
        bits.append(f"dries {d} (curated)")
    return ", ".join(bits)


def sun_adjusted_tmax(v, tmax, sun_frac=None):
    """Aspect comes from venues.json / GAZETTEER ('aspect'; unknown → mild +1 sun
    bump). Sunniness = forecast sunshine fraction when live, dryness as a proxy
    for the climatology/outlook horizons."""
    if tmax is None:
        return tmax
    adj = aspect_adj(v.get("aspect"), 1)
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


def forecast_metrics(d):
    """core's derived signals over the CLIMBING day, plus the friction reading —
    the one label core deliberately refuses to make on climbing's behalf."""
    met = metrics.forecast_metrics(d, active_hours=ACTIVE_HOURS)
    for rec in met.values():
        rec["friction"] = friction_label(rec.get("dew"))
    return met


# ── the curves ───────────────────────────────────────────────────────────────

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
    a cool-but-wet venue is punished as hard as a dry-but-hot one. Tuned on the
    historical backtest (trip-ni-july-2026/scripts/backtest_ranking.py): 40%+ wet
    days drops a venue out of the top tier (Fair Head 46% ≈ −48), 55% ≈ −76, 67%
    bottoms out; a <12%-wet desert stays untouched. tol = rain-tolerance."""
    pct = pct or 0
    return (max(0, pct - RAIN_IDEAL_PCT) * 1.25
            + max(0, pct - RAIN_STEEP_PCT) * 1.5) / (tol or 1.0)


def day_rain_penalty(prob, tol=1.0):
    """Forecast rain-probability → points off. Keeps the gentle 0.8/pt base for
    uncertain days but steepens past 50%, in the same spirit as the climatology
    rain curve — so a high-chance-of-rain trip day is penalised consistently
    across horizons, while the weather-code caps in day_score still handle
    'it will definitely rain'. Only ADDS penalty above 50%, so a dry forecast is
    never pushed down. tol = user rain-tolerance (>1 = softer)."""
    prob = prob or 0
    return (prob * 0.8 + max(0, prob - 50) * 0.7) / (tol or 1.0)


def climo_score(c, rain_tol=1.0, heat_tol=1.0, dry_f=1.0):
    # dry_f (drying_factor): slow-drying rock loses more per typical wet day —
    # half-weighted here, since climatology already averages over dry-out days
    s = 100 - rain_penalty(c["rain_pct"], rain_tol) * (1 + (dry_f - 1) * 0.5)
    s -= max(0, COLD_C - c["tmax"]) * 2      # too cold: numb fingers below ~8°C
    s -= heat_penalty(c["tmax"]) / (heat_tol or 1.0)
    return max(0, min(100, round(s)))


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
    s = 100.0 - day_rain_penalty(
        metrics.effective_rain_prob(p, code, ens_prob), rain_tol) - mm_pen
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

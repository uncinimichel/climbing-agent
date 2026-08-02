"""What the weather means FOR GOLF.

Written from scratch rather than adapted from climbing, on purpose. The two
sports disagree about almost everything the same numbers mean:

  wind    climbing's problem with wind is belays and rope drag past ~30 km/h.
          Golf's problem starts around 15 km/h, because it is the ball that
          gets blown, and it never stops mattering — there is no sheltered
          face to move to.
  heat    climbing falls apart above 24°C (friction). Golf is comfortable
          there; 30°C is merely unpleasant, and cold hurts sooner.
  rain    climbing cares how long the ROCK stays wet afterwards. Golf cares
          whether the COURSE drains — an hour of rain on links sand is
          nothing, on parkland clay it is casual water and cart-path-only.

Nothing here is imported by another domain, and it imports nothing from one.
"""
from core.weather import metrics

# Golf hours (local): a round takes ~4h and nobody tees off in the dark.
GOLF_H0, GOLF_H1 = 8, 18
ACTIVE_HOURS = (GOLF_H0, GOLF_H1)

WIND_FRESH_KMH = 15    # ball flight starts being shaped
WIND_STRONG_KMH = 28   # club selection stops being a choice
WIND_SEVERE_KMH = 45   # putting on exposed greens becomes a lottery

COLD_C = 10            # grip, ball compression and willpower all drop off
HEAT_HIGH_C = 30       # walking 7 km in this is the limiting factor

# How fast the course sheds water. Links sand drains almost instantly; heathland
# is quick; parkland clay holds it and goes cart-path-only for a day.
DRAINAGE = {"links": 0.5, "heathland": 0.8, "parkland": 1.3, "clay": 1.6}


def drainage_factor(v):
    """Multiplier on the wet-course penalty from the venue's soil. An explicit
    `drainage: "fast"|"slow"` on the venue overrides the course-type guess."""
    d = (v.get("drainage") or "").lower()
    if d == "fast":
        return 0.6
    if d == "slow":
        return 1.5
    return DRAINAGE.get((v.get("course_type") or "").lower(), 1.0)


def exposure_factor(v):
    """Links and clifftop courses have no trees to hide behind, so the same wind
    costs more there than on a sheltered parkland layout."""
    if v.get("links") or v.get("coastal"):
        return 1.35
    if (v.get("course_type") or "").lower() == "parkland":
        return 0.85
    return 1.0


def wind_penalty(kmh, exposure=1.0):
    """Points off for wind — golf's dominant signal, and the reason a forecast
    that reads 'dry and mild' can still be a bad golf day."""
    if kmh is None:
        return 0.0
    return (max(0, kmh - WIND_FRESH_KMH) * 1.2
            + max(0, kmh - WIND_STRONG_KMH) * 2.0
            + max(0, kmh - WIND_SEVERE_KMH) * 3.0) * exposure


def temp_penalty(tmax):
    """Cold bites earlier than heat: 5°C is a worse round than 30°C."""
    if tmax is None:
        return 0.0
    return max(0, COLD_C - tmax) * 2.5 + max(0, tmax - HEAT_HIGH_C) * 1.5


def course_penalty(wet_hours, drainage=1.0):
    """Standing water, casual-water relief and cart-path-only — how long the
    course stays unplayable after rain, not how long the rain lasts."""
    if wet_hours is None:
        return 0.0
    return min(wet_hours, 10) * 1.6 * drainage


def forecast_metrics(d):
    """Derived signals over the GOLF day."""
    return metrics.forecast_metrics(d, active_hours=ACTIVE_HOURS)


def day_score(code, mm, prob, m=None, venue=None):
    """0–100 for a single golf day. Rain closes the round, wind ruins it, and a
    soft course is the difference between a good walk and a mud bath."""
    venue = venue or {}
    m = m or {}
    p = metrics.effective_rain_prob(
        m.get("prob_day") if m.get("prob_day") is not None else prob,
        code, m.get("ens_prob"))
    s = 100.0 - (p or 0) * 0.7 - (m.get("rain_day") or mm or 0) * 5
    if code is not None and code >= 95:      # thunderstorms clear the course
        s = min(s, 10)
    s -= wind_penalty(m.get("gust"), exposure_factor(venue))
    s -= temp_penalty(m.get("tmax"))
    s -= course_penalty(m.get("wet_hrs_day"), drainage_factor(venue))
    return max(0.0, min(100.0, s))


def climo_score(c, venue=None):
    """0–100 for a typical-conditions record — how a venue ranks months out,
    before any forecast reaches the dates."""
    venue = venue or {}
    s = 100.0 - (c.get("rain_pct") or 0) * 1.1
    s -= wind_penalty(c.get("wind"), exposure_factor(venue))
    s -= temp_penalty(c.get("tmax"))
    return max(0, min(100, round(s)))


def signals(result, venue):
    """Wind · Rain · Temp · Course · Daylight — golf's five dials. Deliberately
    NOT climbing's five: there is no friction reading and no aspect, because a
    fairway does not face a direction."""
    fc = (result or {}).get("fc") or {}
    if not fc.get("in_window"):
        return None
    exp, drain = exposure_factor(venue), drainage_factor(venue)

    def sig(x):
        return max(0, min(100, round(x)))

    g, t, wh = fc.get("gust_max"), fc.get("tmax"), fc.get("wet_hours")
    return [
        {"n": "Wind", "v": sig(100 - wind_penalty(g, exp)) if g is not None else None,
         "d": f"gusts to {g} km/h" + (" · exposed links" if exp > 1.2 else "")
              if g is not None else "no gust signal"},
        {"n": "Rain", "v": sig(100 - (fc.get("rain_prob") or 0) * 0.8),
         "d": f"max rain prob {fc.get('rain_prob') or 0}% over the trip"},
        {"n": "Temp", "v": sig(100 - temp_penalty(t)) if t is not None else None,
         "d": f"{round(t)}°C" if t is not None else "no temperature signal"},
        {"n": "Course", "v": sig(100 - course_penalty(wh, drain)) if wh is not None else None,
         "d": (f"~{wh}h/day of rain on a "
               f"{'fast' if drain < 0.9 else 'slow' if drain > 1.2 else 'normal'}-draining course")
              if wh is not None else "no wet-hours signal"},
        {"n": "Daylight", "v": None, "d": "activates when the live forecast reaches your dates"},
    ]

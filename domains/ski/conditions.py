"""What the weather means FOR SKIING.

Skiing is the sport where the shared weather layer helps least, and that is
itself the argument for domains owning their own conditions: the signal that
decides a ski trip — how much snow is on the ground and whether the lifts are
turning — is not in a weather forecast at all. It comes from resort feeds, and
the forecast only tells you what will happen to the snow that is already there.

So the curves here read almost nothing like climbing's. Rain is a catastrophe
rather than an inconvenience (it destroys the snowpack); warmth is bad for the
opposite reason to climbing; and wind matters mainly because it shuts lifts.
"""
from core.weather import metrics

# Lift hours (local).
SKI_H0, SKI_H1 = 9, 16
ACTIVE_HOURS = (SKI_H0, SKI_H1)

BASE_THIN_CM = 60      # below this, cover is patchy and the base is at risk
BASE_GOOD_CM = 120     # everything open, off-piste viable

FREEZE_C = 0           # above freezing the snow softens, then goes
SLUSH_C = 6            # spring-slush territory by lunchtime

WIND_HOLD_KMH = 60     # gondolas hold, then chairs — the day shrinks to lower lifts


def snow_score(depth_cm):
    """0–100 from the reported base depth. The single biggest signal, and the
    one that comes from resort feeds rather than a forecast."""
    if depth_cm is None:
        return None
    if depth_cm >= BASE_GOOD_CM:
        return 100
    if depth_cm <= 0:
        return 0
    if depth_cm >= BASE_THIN_CM:
        return round(70 + 30 * (depth_cm - BASE_THIN_CM) / (BASE_GOOD_CM - BASE_THIN_CM))
    return round(70 * depth_cm / BASE_THIN_CM)


def thaw_penalty(tmax):
    """Points off for warmth. Unlike climbing, there is no upside to a sunny
    warm day: it turns the piste to slush and then to grass."""
    if tmax is None:
        return 0.0
    return max(0, tmax - FREEZE_C) * 3.0 + max(0, tmax - SLUSH_C) * 4.0


def rain_penalty(mm, tmax=None):
    """Rain on snow is the worst thing that can happen to a ski week — it is
    charged far harder than climbing charges it, and only when it is warm
    enough to fall as rain rather than accumulate as fresh snow."""
    if mm is None:
        return 0.0
    if tmax is not None and tmax <= FREEZE_C:
        return 0.0          # falling as snow: this is a gift, not a penalty
    return min(mm, 20) * 5.0


def lift_penalty(gust_kmh):
    """High wind closes the top lifts, which is what actually costs you the day."""
    if gust_kmh is None:
        return 0.0
    return max(0, gust_kmh - WIND_HOLD_KMH) * 1.5


def fresh_bonus(snowfall_cm):
    """New snow in the days before you arrive — the whole reason to chase a
    week rather than book one in advance."""
    if not snowfall_cm:
        return 0.0
    return min(snowfall_cm, 40) * 0.5      # 40 cm ≈ +20


def forecast_metrics(d):
    """Derived signals over the LIFT day."""
    return metrics.forecast_metrics(d, active_hours=ACTIVE_HOURS)


def day_score(code, mm, prob, m=None, venue=None):
    """0–100 for a single ski day, given a forecast day. Note what is missing:
    without a base depth from the resort feed this is only half the answer, and
    the ranking must say so rather than pretend."""
    m = m or {}
    t = m.get("tmax")
    s = 100.0 - thaw_penalty(t) - rain_penalty(m.get("rain_day") or mm, t)
    s -= lift_penalty(m.get("gust"))
    if code is not None and 71 <= code <= 75:      # snowing
        s += 8
    return max(0.0, min(100.0, s))


def climo_score(c, venue=None):
    """0–100 for typical conditions — for ski this is mostly a proxy for
    altitude and latitude until resort history is wired in."""
    s = 100.0 - thaw_penalty(c.get("tmax"))
    return max(0, min(100, round(s)))


def signals(result, venue):
    """Snow · Lifts · Fresh · Thaw · Vis — ski's five dials. Snow and Lifts come
    from resort feeds, so they read as pending until that source is connected."""
    fc = (result or {}).get("fc") or {}
    if not fc.get("in_window"):
        return None

    def sig(x):
        return max(0, min(100, round(x)))

    base = (venue or {}).get("base_cm")
    g, t = fc.get("gust_max"), fc.get("tmax")
    pending = "needs the resort feed — not connected yet"
    return [
        {"n": "Snow", "v": snow_score(base),
         "d": f"{base} cm base" if base is not None else pending},
        {"n": "Lifts", "v": sig(100 - lift_penalty(g)) if g is not None else None,
         "d": f"gusts to {g} km/h" + (" — top lifts likely on hold" if g and g > WIND_HOLD_KMH else "")
              if g is not None else pending},
        {"n": "Fresh", "v": None, "d": pending},
        {"n": "Thaw", "v": sig(100 - thaw_penalty(t)) if t is not None else None,
         "d": f"{round(t)}°C at resort level" if t is not None else "no temperature signal"},
        {"n": "Vis", "v": None, "d": "activates when the live forecast reaches your dates"},
    ]

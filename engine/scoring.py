"""Venue evaluation + composite scoring — moved from update_report.py's
evaluate/apply_composite/rank/weather_signals/venue_is_tidal, parameterized on
TripContext (+ explicit caches and the multi-pitch.com climb list) instead of
module-level globals.

Composite score: weather + travel + venue fit. Weather stays dominant; travel
uses live/cached flight prices when known plus the sheet's travel-time band;
venue fit comes from the sheet's judgment columns (volume of multi-pitch,
difficulty spread, minimum-trip length).
"""
import re
import sys
from datetime import date

from . import weather
from .climbs import nearby_climb_cards, nearby_climbs, venue_is_tidal
from .http import redact
from .render import WMO, wmo_icon
from .stays import STAY_ADULTS, stay_options

W_WEATHER, W_TRAVEL, W_FIT = 55, 25, 20
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


def prio_num(v):
    for ch in v.get("priority", "9"):
        if ch.isdigit():
            return int(ch)
    return 9


def evaluate(v, ctx, env_cache=None, climo_cache=None, stays_cache=None,
             link_health_cache=None, mp_climbs=None):
    mp_climbs = mp_climbs or []
    res = {"venue": v, "ok": True, "climo": None, "fc": None, "seasonal": None}
    res["stays"] = stay_options(v, ctx, stays_cache, link_health_cache)
    try:
        res["climo"] = weather.climatology(v["lat"], v["lon"], ctx, climo_cache)
    except Exception as e:
        print(f"[warn] climatology failed for {v['name']}: {redact(e)}", file=sys.stderr)
        res["climo"] = None
    try:
        res["seasonal"] = weather.seasonal(v["lat"], v["lon"], ctx, env_cache)
    except Exception as e:
        print(f"[warn] seasonal failed for {v['name']}: {redact(e)}", file=sys.stderr)
        res["seasonal"] = None
    if venue_is_tidal(v, mp_climbs):
        try:
            res["tides"] = weather.tide_extremes(v["lat"], v["lon"], env_cache)
        except Exception as e:
            print(f"[warn] tides failed for {v['name']}: {redact(e)}", file=sys.stderr)
    try:
        d = weather.forecast(v["lat"], v["lon"], env_cache)
        daily = d["daily"]
        days = daily["time"]
        met = weather.forecast_metrics(d)                     # per-ISO-date derived signals
        valid = [i for i in range(len(days)) if daily["temperature_2m_max"][i] is not None]
        in_win = [i for i in valid if ctx.target_start <= date.fromisoformat(days[i]) <= ctx.target_end]
        winds = daily.get("windspeed_10m_max") or [None] * len(days)
        dirs = daily.get("winddirection_10m_dominant") or [None] * len(days)
        # per-day live forecast for graph-window days (overlaid on the typical chart)
        res["fc_days"] = {}
        uvs = daily.get("uv_index_max") or [None] * len(days)
        ccs = daily.get("cloud_cover_mean") or [None] * len(days)
        graph_md = ctx.graph_md
        for i in valid:
            dd = date.fromisoformat(days[i])
            if (dd.month, dd.day) in graph_md:
                mi = met.get(days[i], {})
                res["fc_days"][(dd.month, dd.day)] = {
                    "tmax": round(daily["temperature_2m_max"][i]),
                    "precip": round(daily["precipitation_sum"][i] or 0, 1),
                    "icon": wmo_icon(daily["weathercode"][i]),
                    "wind": round(winds[i]) if winds[i] is not None else None,
                    "dir": round(dirs[i]) if dirs[i] is not None else None,
                    "uv": round(uvs[i]) if uvs[i] is not None else None,
                    "cloud": round(ccs[i]) if ccs[i] is not None else None,
                    "gust": mi.get("gust"), "dew": mi.get("dew"),
                    "friction": mi.get("friction"), "sunFrac": mi.get("sun_frac"),
                }
        if in_win:
            scores = [weather.day_score(daily["weathercode"][i], daily["precipitation_sum"][i],
                                         daily["precipitation_probability_max"][i],
                                         weather.asp_m(v, met.get(days[i])))
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
                "friction": weather.friction_label(mean_dew), "dew": mean_dew,
                "am_dry_days": (sum(1 for a in am_flags if a), len(am_flags)) if am_flags else None,
                "in_window": True, "horizon": days[-1],
            }
        else:
            res["fc"] = {"in_window": False, "horizon": days[-1] if days else "?"}
    except Exception as e:
        print(f"[warn] forecast failed for {v['name']}: {redact(e)}", file=sys.stderr)
        res["fc"] = None

    fc, sea = res["fc"], res["seasonal"]
    if fc and fc.get("in_window"):
        res["score"], res["basis"] = fc["score"], "live forecast (trip window)"
    elif res["climo"]:
        c = res["climo"]
        sunny = max(0.35, 1 - c["rain_pct"] / 100)   # dry climate ≈ sunny climate
        cs = weather.climo_score({**c, "tmax": weather.sun_adjusted_tmax(v, c["tmax"], sunny)})
        if sea:
            # gentle blend: climatology dominant, 45-day outlook nudges it
            ssun = max(0.35, 1 - sea["rain_pct"] / 100)
            ss = weather.climo_score({"tmax": weather.sun_adjusted_tmax(v, sea["tmax"], ssun),
                                       "rain_pct": sea["rain_pct"]})
            res["score"] = round(0.7 * cs + 0.3 * ss)
            res["basis"] = f"typical {ctx.period_lbl} + long-range outlook"
        else:
            res["score"], res["basis"] = cs, f"typical {ctx.period_lbl} (climatology)"
    else:
        res["score"], res["basis"] = -1, "no data"
    res["wscore"] = res["score"]   # weather-only score; composite overwrites score
    return res


def weather_signals(r, v):
    """Per-signal 'health checks' for the header ring's outer tier: how little
    each weather signal is costing (100 = costing nothing). Uses the same
    numbers/penalty curves as the score itself. Wind + friction only exist on
    the live-forecast horizon — before that they ship as None ('pending')."""
    fc = r.get("fc") or {}
    if fc.get("in_window"):
        t = weather.sun_adjusted_tmax(v, fc["tmax"]) if fc.get("tmax") is not None else None
        g, dw = fc.get("gust_max"), fc.get("dew")
        return [
            {"n": "Rain", "v": _sig(100 - (fc.get("rain_prob") or 0) * 0.8),
             "d": f"max rain prob {fc.get('rain_prob') or 0}% over the trip"},
            {"n": "Heat", "v": _sig(100 - weather.heat_penalty(t) - max(0, 8 - t) * 2) if t is not None else None,
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
    t = weather.sun_adjusted_tmax(v, tm, sunny)
    pend = "activates when the live forecast reaches your dates"
    return [
        {"n": "Rain", "v": _sig(100 - rp * 0.9), "d": f"{rp}% typical wet days"},
        {"n": "Heat", "v": _sig(100 - weather.heat_penalty(t) - max(0, 8 - t) * 2),
         "d": f"{round(t)}°C felt on the rock"},
        {"n": "Wind", "v": None, "d": pend},
        {"n": "Friction", "v": None, "d": pend},
    ]


def apply_composite(r, ctx, mp_climbs=None):
    """Attach r['score'] (composite 0-100) + r['breakdown'] for the UI."""
    mp_climbs = mp_climbs or []
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
        pp_total = st["est"] / STAY_ADULTS * ctx.rep_combo["nights"]
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
    trip_s = 100 if not mt else max(0, 100 - max(0, int(mt.group()) - ctx.trip_days) * 25)
    n_routes = len(nearby_climbs(v, mp_climbs, km=60))
    routes_s = 50 + min(50, n_routes * 10)   # multi-pitch.com coverage: neutral at 0, +10/route
    fit = round((vol_s + diff_s + trip_s + routes_s) / 4)
    fit_bits = []
    if sh.get("volume"):
        fit_bits.append(f"{sh['volume'].lower()} multi-pitch volume")
    if sh.get("difficulty"):
        fit_bits.append(f"difficulty: {sh['difficulty'].lower()}")
    if sh.get("min_trip"):
        fit_bits.append(f"min trip {sh['min_trip'].lower()} vs your {ctx.trip_days} days")
    fit_bits.append(f"{n_routes} multi-pitch.com route{'s' if n_routes != 1 else ''} nearby"
                    if n_routes else "no multi-pitch.com routes indexed yet")
    fit_note = "; ".join(fit_bits)
    r["score"] = round((W_WEATHER * w + W_TRAVEL * travel + W_FIT * fit) / 100)
    r["breakdown"] = {
        "weather": w, "travel": travel, "fit": fit,
        "weights": {"weather": W_WEATHER, "travel": W_TRAVEL, "fit": W_FIT},
        "weather_note": r.get("basis", "") + (
            f" · {v['aspect'].upper()}-facing rock ({weather.ASPECT_ADJ.get(v['aspect'].upper(), 0):+d}°C felt in full sun)"
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
                 "d": f"min trip {sh['min_trip'].lower()} vs your {ctx.trip_days} days" if sh.get("min_trip")
                      else f"no minimum-trip constraint vs your {ctx.trip_days} days"},
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

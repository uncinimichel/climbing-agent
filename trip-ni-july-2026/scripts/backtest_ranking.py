#!/usr/bin/env python3
"""Backtest / A-B harness for the venue ranking function.

Runs the ranking against REAL cached data (offline — no network) so we can try
scoring changes and see how the board reorders, without touching production.

Two harnesses:

  A) SNAPSHOT SANDBOX — replays today's full board from the on-disk caches
     (climo-cache, venue-env, stays, flights-latest) and scores it under the
     baseline scorer and each proposed variant, side by side with rank deltas.

  B) HISTORICAL WEATHER BACKTEST — parses the (temp, wet%, score) the system
     actually recorded for every venue across history/*.md, then recomputes the
     WEATHER sub-score under the new rain curve to show, per historical day, how
     the weather-driven ordering would have shifted. (Travel/fit weren't cached
     per-date, so only the weather component is faithfully reconstructable — and
     that's exactly the piece the recalibration changes.)

Nothing here mutates engine/ or the report; it imports engine data-loading and
re-implements only the scoring math being tuned, parameterized on ScoringParams
+ Preferences. Run:  python3 trip-ni-july-2026/scripts/backtest_ranking.py

NOTE: this harness picked the curve that shipped as decision #28 — production
`engine.weather.rain_penalty` is now the band curve `1.25·(w−12)⁺ + 1.5·(w−40)⁺`.
The "baseline" preset below is the PRE-#28 flat `0.9·rain_pct`, kept so the A/B
still shows the before/after; SYMMETRIC_RAIN here is an earlier no-band variant
of the same idea, retained for reference.
"""
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from engine import climbs, scoring, sheet_venues, weather  # noqa: E402
from engine.cache import DiskCache, EnvCache  # noqa: E402
from engine.geo import haversine_km  # noqa: E402
from engine.models import TripContext  # noqa: E402

# ---------------------------------------------------------------------------
# Home origins for the distance-from-home signal (Michel: London; Dan: NI/Dublin)
# ---------------------------------------------------------------------------
LONDON = (51.5074, -0.1278)
BELFAST = (54.607, -5.926)
DUBLIN = (53.349, -6.260)


def home_distance_km(v):
    """Mean of Michel's reach (from London) and Dan's reach (nearer of
    Belfast/Dublin) — how far *both* travellers have to go, in km."""
    la, lo = v["lat"], v["lon"]
    michel = haversine_km(LONDON[0], LONDON[1], la, lo)
    dan = min(haversine_km(BELFAST[0], BELFAST[1], la, lo),
              haversine_km(DUBLIN[0], DUBLIN[1], la, lo))
    return (michel + dan) / 2


def distance_score(v):
    """0–100: near home = full marks, ~4000 km away = 0. Linear, clamped."""
    return max(0, min(100, round(100 - home_distance_km(v) * 0.025)))


def distance_cost_estimate(v):
    """Rough return-fare proxy (£) from distance, for the travel fallback when
    no live flight price exists. ~£40 base + £0.08/km (mean traveller)."""
    return round(40 + home_distance_km(v) * 0.08)


# ---------------------------------------------------------------------------
# Preferences — per-sub-signal multipliers, all neutral (1.0) today. This is the
# hook the future user-preferences UI writes into; 1.0 everywhere == current.
# ---------------------------------------------------------------------------
@dataclass
class Preferences:
    # weather levers
    heat_tol: float = 1.0        # >1 tolerates heat better (softens heat penalty)
    rain_tol: float = 1.0        # >1 tolerates rain better (softens rain penalty)
    # travel levers
    cost: float = 1.0
    distance: float = 1.0
    # fit levers
    volume: float = 1.0
    difficulty: float = 1.0
    trip_fit: float = 1.0
    coverage: float = 1.0
    fit_distance: float = 1.0
    # top-level component emphasis
    weather: float = 1.0
    travel: float = 1.0
    fit: float = 1.0


def wmean(pairs):
    """Weighted mean of (value, weight) pairs, skipping value None."""
    ps = [(v, w) for v, w in pairs if v is not None]
    if not ps:
        return None
    return round(sum(v * w for v, w in ps) / sum(w for _, w in ps))


# ---------------------------------------------------------------------------
# ScoringParams — the knobs we're tuning. rain_penalty is the headline change.
# ---------------------------------------------------------------------------
@dataclass
class ScoringParams:
    name: str
    rain_penalty: callable                       # wet_pct -> points off
    rain_cap: float | None = None                # hard weather cap above rain_veto_pct
    rain_veto_pct: float = 50.0
    use_distance_in_fit: bool = False
    use_distance_travel_fallback: bool = False
    prefs: Preferences = field(default_factory=Preferences)


# Rain curves --------------------------------------------------------------
BASELINE_RAIN = lambda w: w * 0.9                                   # current production
SYMMETRIC_RAIN = lambda w: w * 1.15 + max(0, w - 45) * 1.6          # steepens like the heat curve

PRESETS = {
    "baseline": ScoringParams("baseline", BASELINE_RAIN),
    "rain_symmetric": ScoringParams("rain_symmetric", SYMMETRIC_RAIN),
    "rain_veto": ScoringParams("rain_veto", BASELINE_RAIN, rain_cap=30, rain_veto_pct=50),
    "all_changes": ScoringParams(
        "all_changes", SYMMETRIC_RAIN,
        use_distance_in_fit=True, use_distance_travel_fallback=True),
}


# ---------------------------------------------------------------------------
# Parameterized weather score (mirrors scoring.evaluate's climo/forecast branch,
# swapping in params.rain_penalty; heat/cold curves unchanged).
# ---------------------------------------------------------------------------
def weather_score(v, r, params):
    fc = r.get("fc") or {}
    if fc.get("in_window"):                       # live-forecast horizon — leave as engine scored it
        return r.get("wscore", -1)                # (day_score rain term not retuned here)
    c, sea = r.get("climo"), r.get("seasonal")
    if not c:
        return -1

    def cscore(rain_pct, tmax, sun):
        t = weather.sun_adjusted_tmax(v, tmax, sun)
        pen = params.rain_penalty(rain_pct) / params.prefs.rain_tol
        heat = weather.heat_penalty(t) / params.prefs.heat_tol
        s = 100 - pen - max(0, weather.COLD_C - t) * 2 - heat
        s = max(0, min(100, round(s)))
        if params.rain_cap is not None and rain_pct >= params.rain_veto_pct:
            s = min(s, params.rain_cap)
        return s

    sunny = max(0.35, 1 - c["rain_pct"] / 100)
    cs = cscore(c["rain_pct"], c["tmax"], sunny)
    if sea:
        ssun = max(0.35, 1 - sea["rain_pct"] / 100)
        ss = cscore(sea["rain_pct"], sea["tmax"], ssun)
        return round(0.7 * cs + 0.3 * ss)
    return cs


# ---------------------------------------------------------------------------
# Parameterized composite (mirrors scoring.apply_composite, adding distance).
# ---------------------------------------------------------------------------
def composite(v, r, w, ctx, params, mp_climbs, flights_by_name):
    if w < 0:
        return -1
    p = params.prefs
    sh = v.get("sheet") or {}
    fl = flights_by_name.get(v["name"]) or {}

    # travel: cost per traveller (live price, drive/local flat, else distance est)
    costs = []
    for who in ("michel", "dan"):
        mode = (v.get("travel", {}).get(who) or {}).get("mode")
        opts = ((fl.get(who) or {}).get("options")) or []
        if mode == "local":
            costs.append(0)
        elif mode == "drive":
            costs.append(90)
        elif opts:
            costs.append(opts[0]["price"])
        elif params.use_distance_travel_fallback:
            costs.append(distance_cost_estimate(v))
        else:
            costs.append(None)
    known = [c for c in costs if c is not None]
    cost_s = round(max(0, min(100, 100 - (sum(known) / len(known)) / 4))) if known else None
    time_s = scoring._band(sh.get("travel_time"), scoring.TIME_BAND, 65)
    st = (r.get("stays") or {}).get("cheapest")
    stay_s = None
    if st:
        pp = st["est"] / 2 * ctx.rep_combo["nights"]
        stay_s = round(max(0, min(100, 100 - pp / 4)))
    travel = wmean([(cost_s, p.cost), (time_s, 1.0), (stay_s, 1.0)])

    # fit: sheet judgment bands (+ optional distance-from-home)
    vol_s = scoring._band(sh.get("volume"), scoring.VOL_BAND, 60)
    diff_s = scoring._band(sh.get("difficulty"), scoring.DIFF_BAND, 70)
    mt = re.search(r"\d+", sh.get("min_trip") or "")
    trip_s = 100 if not mt else max(0, 100 - max(0, int(mt.group()) - ctx.trip_days) * 25)
    n_routes = len(climbs.nearby_climbs(v, mp_climbs, km=60))
    routes_s = 50 + min(50, n_routes * 10)
    fit_pairs = [(vol_s, p.volume), (diff_s, p.difficulty),
                 (trip_s, p.trip_fit), (routes_s, p.coverage)]
    if params.use_distance_in_fit:
        fit_pairs.append((distance_score(v), p.fit_distance))
    fit = wmean(fit_pairs)

    return round((scoring.W_WEATHER * w * p.weather
                  + scoring.W_TRAVEL * travel * p.travel
                  + scoring.W_FIT * fit * p.fit)
                 / (scoring.W_WEATHER * p.weather + scoring.W_TRAVEL * p.travel + scoring.W_FIT * p.fit)
                 * 100 / 100)


# ---------------------------------------------------------------------------
# Load the current board offline
# ---------------------------------------------------------------------------
def load_board():
    venues_cfg = json.loads((ROOT / "venues.json").read_text())
    merged = sheet_venues.build_venues(venues_cfg["venues"], REPO_ROOT / "climbing-trips.csv")
    ctx = TripContext(
        trip_name=venues_cfg["trip"],
        target_start=date.fromisoformat(venues_cfg["target_window"]["start"]),
        target_end=date.fromisoformat(venues_cfg["target_window"]["end"]),
        venues=merged, flights_cfg=json.loads((ROOT / "flights.json").read_text()),
        serpapi_key=None, top_n_flights=10)
    env = EnvCache(ROOT / "venue-env.json")
    climo = DiskCache(ROOT / "climo-cache.json",
                      key_filter=lambda k: k.endswith("|" + weather.CLIMO_VER))
    stays = DiskCache(ROOT / "stays-cache.json")
    lh = DiskCache(ROOT / "link-health-cache.json")
    mp = climbs.load_mp_climbs()
    flights_by_name = (json.loads((ROOT / "flights-latest.json").read_text()).get("venues") or {})
    res = [scoring.evaluate(v, ctx, env, climo, stays, lh, mp) for v in ctx.venues]
    return ctx, res, mp, flights_by_name


def score_board(ctx, res, mp, flights_by_name, params):
    out = []
    for r in res:
        if not r.get("ok"):
            continue
        w = weather_score(r["venue"], r, params)
        comp = composite(r["venue"], r, w, ctx, params, mp, flights_by_name)
        out.append({"name": r["venue"]["name"], "w": w, "score": comp,
                    "climo": r.get("climo")})
    out = [o for o in out if o["score"] is not None and o["score"] >= 0]
    out.sort(key=lambda o: -o["score"])
    for i, o in enumerate(out, 1):
        o["rank"] = i
    return out


def harness_a():
    print("=" * 78)
    print("HARNESS A — snapshot sandbox (offline replay of today's board)")
    print("=" * 78)
    ctx, res, mp, flights_by_name = load_board()
    boards = {k: score_board(ctx, res, mp, flights_by_name, p) for k, p in PRESETS.items()}
    base = {o["name"]: o for o in boards["baseline"]}

    def col(board_key, name):
        o = next((x for x in boards[board_key] if x["name"] == name), None)
        return o

    order = boards["all_changes"]
    print(f"\n{'venue':26} | baseline    | rain_sym    | all_changes  (Δrank vs baseline)")
    print("-" * 90)
    for o in order[:20]:
        n = o["name"]
        b = base.get(n)
        rs = col("rain_symmetric", n)
        ac = col("all_changes", n)
        d = (b["rank"] - ac["rank"]) if b else 0
        arrow = f"{'+' if d>0 else ''}{d}" if d else "·"
        c = o.get("climo") or {}
        wx = f"{c.get('tmax','?')}°/{c.get('rain_pct','?')}%wet"
        print(f"{n[:26]:26} | #{b['rank']:<2} {b['score']:>3} w{b['w']:<3} "
              f"| #{rs['rank']:<2} {rs['score']:>3} "
              f"| #{ac['rank']:<2} {ac['score']:>3}  {arrow:>4}   {wx}")

    # biggest movers under the combined change
    movers = sorted(boards["all_changes"],
                    key=lambda o: (base[o["name"]]["rank"] - o["rank"]) if o["name"] in base else 0)
    print("\nBiggest DROPS (wet/hot/far punished harder):")
    for o in movers[:6]:
        b = base.get(o["name"]);  c = o.get("climo") or {}
        if b:
            print(f"  {o['name'][:24]:24}  #{b['rank']}→#{o['rank']}  "
                  f"score {b['score']}→{o['score']}  ({c.get('tmax','?')}°/{c.get('rain_pct','?')}%wet)")
    print("Biggest CLIMBS (cool/dry/near rewarded):")
    for o in reversed(movers[-6:]):
        b = base.get(o["name"]);  c = o.get("climo") or {}
        if b:
            print(f"  {o['name'][:24]:24}  #{b['rank']}→#{o['rank']}  "
                  f"score {b['score']}→{o['score']}  ({c.get('tmax','?')}°/{c.get('rain_pct','?')}%wet)")


# ---------------------------------------------------------------------------
# Harness B — parse history/*.md and reorder on the recalibrated weather curve
# ---------------------------------------------------------------------------
ROW_RE = re.compile(r"^\|\s*\d+\s*\|(.+?)\|\s*(-?\d+)\s*\|\s*(-?\d+)\s*°C,\s*(\d+)%\s*wet")


def parse_history(md_path):
    rows = []
    for line in md_path.read_text().splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        name = re.sub(r"<.*", "", m.group(1)).strip()
        name = re.sub(r"^[^A-Za-z]*", "", name).strip()
        rows.append({"name": name, "score": int(m.group(2)),
                     "tmax": int(m.group(3)), "rain_pct": int(m.group(4))})
    return rows


def weather_only(tmax, rain_pct, rain_penalty):
    """Weather sub-score from just (tmax, wet%) — no aspect/sun (not in history)."""
    s = 100 - rain_penalty(rain_pct) - max(0, weather.COLD_C - tmax) * 2 - weather.heat_penalty(tmax)
    return max(0, min(100, round(s)))


def harness_b():
    print("\n" + "=" * 78)
    print("HARNESS B — historical weather backtest (weather sub-score reorder)")
    print("=" * 78)
    hist = sorted((ROOT / "history").glob("*.md"))
    print("For each recorded day: venues whose WEATHER ranking moves most when the")
    print("rain curve is stiffened (baseline 0.9/pt  ->  symmetric).\n")
    for md in hist[-4:]:                          # show the last few days in detail
        rows = parse_history(md)
        if not rows:
            continue
        for r in rows:
            r["wb"] = weather_only(r["tmax"], r["rain_pct"], BASELINE_RAIN)
            r["ws"] = weather_only(r["tmax"], r["rain_pct"], SYMMETRIC_RAIN)
        base_order = sorted(rows, key=lambda r: -r["wb"])
        sym_order = sorted(rows, key=lambda r: -r["ws"])
        rank_b = {r["name"]: i for i, r in enumerate(base_order, 1)}
        rank_s = {r["name"]: i for i, r in enumerate(sym_order, 1)}
        movers = sorted(rows, key=lambda r: rank_s[r["name"]] - rank_b[r["name"]])
        print(f"--- {md.stem}  ({len(rows)} venues) ---")
        drops = [r for r in reversed(movers) if rank_s[r["name"]] - rank_b[r["name"]] > 0][:4]
        for r in drops:
            print(f"    DROP {r['name'][:22]:22} weather-rank #{rank_b[r['name']]}→#{rank_s[r['name']]}  "
                  f"({r['tmax']}°/{r['rain_pct']}%wet)  wscore {r['wb']}→{r['ws']}")
        print()

    # aggregate: correlation of wet% with rank change across all history
    allrows = []
    for md in hist:
        for r in parse_history(md):
            r["wb"] = weather_only(r["tmax"], r["rain_pct"], BASELINE_RAIN)
            r["ws"] = weather_only(r["tmax"], r["rain_pct"], SYMMETRIC_RAIN)
            allrows.append(r)
    wet = [r for r in allrows if r["rain_pct"] >= 45]
    dry = [r for r in allrows if r["rain_pct"] <= 20]
    if wet:
        print(f"Across all {len(allrows)} recorded venue-days:")
        print(f"  wet venues (≥45%): avg weather score {sum(r['wb'] for r in wet)/len(wet):.0f} "
              f"→ {sum(r['ws'] for r in wet)/len(wet):.0f}  ({len(wet)} rows)")
        print(f"  dry venues (≤20%): avg weather score {sum(r['wb'] for r in dry)/len(dry):.0f} "
              f"→ {sum(r['ws'] for r in dry)/len(dry):.0f}  ({len(dry)} rows)")


if __name__ == "__main__":
    harness_a()
    harness_b()

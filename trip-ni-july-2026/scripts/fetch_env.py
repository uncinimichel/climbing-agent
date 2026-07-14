#!/usr/bin/env python3
"""Fetch the trip-INDEPENDENT environment layer — weather + tide — once per venue
and write it to `venue-env.json`, keyed by venue. This is decision #24 / the design
in knowledge/architecture/venue-env-cache.md.

Why this exists as its own script: weather/wind/tide are a pure function of
(lat/lon, date) — they don't depend on who's travelling or which trip is active. So
we compute them ONCE here, and `update_report.py` (and, later, the website's
"browse a venue before committing to a trip" path) consume the cache instead of each
re-hitting the APIs. Weather stays O(venues) no matter how many trips or users exist.

What we cache:
  • raw Open-Meteo `forecast` (16-day, hourly + daily) — what the report actually needs
  • raw Open-Meteo `seasonal` (~45-day outlook)
  • derived tide extremes (high/low water) for tidal venues
  Climatology is NOT re-cached here: it's the fixed 2021-24 archive, already persisted
  in `climo-cache.json` and committed (it never changes), so re-fetching it would be waste.

The file carries two views of the same data:
  • `raw`  — the provider payloads engine.weather consumes (so output is identical
             to a live run: it needs hourly dewpoint/precip/gusts the normalized view drops).
  • `days` — a normalized, per-(venue, date), latest-only view {src, tmax, precip, wind,
             dir, code, tide_hw/lw} — the reuse/website/future-Postgres surface.

Latest-only: overwritten every run, no forecast-as-of history (see the design doc).
Degrade, never crash: any venue whose fetch fails is written with nulls and skipped —
engine.weather then falls back to a live fetch for that venue.

Stdlib only. Run BEFORE update_report.py.
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from engine import climbs, sheet_venues, trips, weather  # noqa: E402
from engine.http import redact  # noqa: E402
from engine.render import _slug  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
CLIMBING_CSV = REPO_ROOT / "climbing-trips.csv"
ENV_CACHE_F = REPO_ROOT / "cache" / "venue-env.json"


def _iso(d):
    return d.isoformat()


def _load_context():
    trip = trips.trip_for_dir(REPO_ROOT, ROOT)
    venues_cfg = json.loads((ROOT / "venues.json").read_text())
    flights_cfg = json.loads((ROOT / "flights.json").read_text())
    merged_venues = sheet_venues.build_venues(venues_cfg["venues"], CLIMBING_CSV)
    return trips.context_for(trip, merged_venues, flights_cfg)


def _norm_days(fc_raw, sea_raw, tide_ex):
    """Normalized per-date view: forecast (0-16d) wins; seasonal fills the tail (~17-45d).
    Tide times are attached to forecast days for tidal venues, within the marine horizon."""
    days = {}
    # forecast band
    if fc_raw:
        d = fc_raw.get("daily") or {}
        t = d.get("time") or []
        for i, iso in enumerate(t):
            tx = (d.get("temperature_2m_max") or [None])[i] if i < len(d.get("temperature_2m_max") or []) else None
            if tx is None:
                continue
            rec = {"src": "forecast", "tmax": round(tx)}
            def g(key):
                arr = d.get(key) or []
                return arr[i] if i < len(arr) and arr[i] is not None else None
            pr, wd, wdir, code = g("precipitation_sum"), g("windspeed_10m_max"), g("winddirection_10m_dominant"), g("weathercode")
            if pr is not None:
                rec["precip"] = round(pr, 1)
            if wd is not None:
                rec["wind"] = round(wd)
            if wdir is not None:
                rec["dir"] = round(wdir)
            if code is not None:
                rec["code"] = int(code)
            if tide_ex and iso in tide_ex:
                rec["tide_hw"] = [x["t"] for x in tide_ex[iso] if x["k"] == "H"]
                rec["tide_lw"] = [x["t"] for x in tide_ex[iso] if x["k"] == "L"]
            days[iso] = rec
    # seasonal tail — only dates the forecast didn't already cover
    if sea_raw:
        d = sea_raw.get("daily") or {}
        t = d.get("time") or []
        tkeys = [k for k in d if k.startswith("temperature_2m_max")]
        pkeys = [k for k in d if k.startswith("precipitation_sum")]
        for i, iso in enumerate(t):
            if iso in days:
                continue
            tv = [d[k][i] for k in tkeys if i < len(d[k]) and d[k][i] is not None]
            if not tv:
                continue
            pv = [d[k][i] for k in pkeys if i < len(d[k]) and d[k][i] is not None]
            rec = {"src": "seasonal", "tmax": round(sum(tv) / len(tv))}
            if pv:
                rec["precip"] = round(sum(pv) / len(pv), 1)
            days[iso] = rec
    return dict(sorted(days.items()))


def build_env():
    ctx = _load_context()
    mp_climbs = climbs.load_mp_climbs()   # tidal derivation reads nearby MP routes
    print(f"multi-pitch climbs loaded: {len(mp_climbs)}", file=sys.stderr)
    now = datetime.now(timezone.utc)
    out = {
        "generated_at": now.isoformat(),
        "target_window": {"start": _iso(ctx.target_start), "end": _iso(ctx.target_end)},
        "venues": {},
    }
    for v in ctx.venues:
        lat, lon = v["lat"], v["lon"]
        tidal = False
        try:
            tidal = climbs.venue_is_tidal(v, mp_climbs)
        except Exception as e:
            print(f"[warn] tidal check failed for {v['name']}: {redact(e)}", file=sys.stderr)
        fc_raw = sea_raw = ens_raw = tide_ex = None
        # env_cache=None here forces a LIVE fetch of every venue — this script's whole
        # job is to populate that cache fresh, never to read a prior run's copy back.
        try:
            fc_raw = weather.forecast(lat, lon, env_cache=None)
        except Exception as e:
            print(f"[warn] forecast failed for {v['name']}: {redact(e)}", file=sys.stderr)
        try:
            sea_raw = weather.seasonal_raw(lat, lon, env_cache=None)
        except Exception as e:
            print(f"[warn] seasonal failed for {v['name']}: {redact(e)}", file=sys.stderr)
        try:
            ens_raw = weather.ensemble_raw(lat, lon, env_cache=None)
        except Exception as e:
            print(f"[warn] ensemble failed for {v['name']}: {redact(e)}", file=sys.stderr)
        if tidal:
            try:
                tide_ex = weather.tide_extremes(lat, lon, env_cache=None)
            except Exception as e:
                print(f"[warn] tides failed for {v['name']}: {redact(e)}", file=sys.stderr)
        out["venues"][_slug(v["name"])] = {
            "name": v["name"], "lat": lat, "lon": lon, "tidal": tidal,
            "fetched_at": now.isoformat(),
            "raw": {"forecast": fc_raw, "seasonal": sea_raw, "ensemble": ens_raw, "tides": tide_ex},
            "days": _norm_days(fc_raw, sea_raw, tide_ex),
        }
        print(f"env: {v['name']} — {len(out['venues'][_slug(v['name'])]['days'])} days"
              f"{' (tidal)' if tidal else ''}", file=sys.stderr)
    return out


def main():
    env = build_env()
    ENV_CACHE_F.write_text(json.dumps(env))
    n = len(env["venues"])
    tot = sum(len(x["days"]) for x in env["venues"].values())
    print(f"Wrote {ENV_CACHE_F.name}: {n} venues, {tot} venue-days "
          f"(generated {env['generated_at']})")


if __name__ == "__main__":
    main()

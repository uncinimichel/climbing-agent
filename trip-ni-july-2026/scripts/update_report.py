#!/usr/bin/env python3
"""Build the trip dashboard: free weather (climatology + forecast) ranking with
per-venue flights for BOTH travellers folded into the same table.

This is now a thin driver over the `engine/` package (see knowledge/roadmap/
decisions.md #25): it loads this trip's venues.json/flights.json, builds a
TripContext, and calls engine.weather/engine.stays/engine.scoring/
engine.flights/engine.render in the same 3-pass rank→price→re-rank loop as
before. Behavior is unchanged — same disk caches, same output files — this
split just makes the underlying logic reusable for an arbitrary user-defined
trip (a future Lambda), not only this hardcoded one.

Weather signals (free, no key):
  1. CLIMATOLOGY — typical late-July conditions per venue (Open-Meteo archive).
     Ranks the venues now, months ahead.
  2. FORECAST — Open-Meteo 16-day forecast; shown once the trip enters range.

Flights (Google Flights via SerpApi, key from SERPAPI_KEY / gitignored .env):
  For the TOP-N ranked venues we price a representative round-trip for Michel
  (from London) and Dan (from Belfast) into that venue's airport, with view/book
  links. NI venues: Dan is local. UK-mainland: Michel drives. To stay within the
  SerpApi quota we price only the top N venues, one representative combo each.

Stays (OpenStreetMap Overpass — free, no key):
  Named accommodation near each venue in three shapes — houses/apartments
  (Airbnb-style), campsites (bring your own kit), hotels/hostels/huts (one room,
  2 adults) — with date-filled Airbnb/Booking search links. Typical per-type
  nightly estimates feed the travel component of the composite score.

Outputs: index.html (Pages), daily-report.md, history/<date>.md. Stdlib only.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from engine import climbs, flights, quota, render, scoring, sheet_venues, weather  # noqa: E402
from engine.cache import DiskCache, EnvCache  # noqa: E402
from engine.models import TripContext  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
HISTORY = ROOT / "history"
DAILY = ROOT / "daily-report.md"
INDEX = REPO_ROOT / "index.html"
CLIMBING_CSV = REPO_ROOT / "climbing-trips.csv"


def _dotenv():
    f = REPO_ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_dotenv()
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def build_context():
    """Load venues.json/flights.json, merge the Google-Sheet venue list, and
    return the TripContext + reference data (guidebooks, extra-climbing links,
    tag taxonomy, sheet rows for match_sheet_row, mp_climbs) the rest of the
    pipeline needs."""
    venues_cfg = json.loads((ROOT / "venues.json").read_text())
    flights_cfg = json.loads((ROOT / "flights.json").read_text())
    merged_venues = sheet_venues.build_venues(venues_cfg["venues"], CLIMBING_CSV)
    ctx = TripContext(
        trip_name=venues_cfg["trip"],
        target_start=date.fromisoformat(venues_cfg["target_window"]["start"]),
        target_end=date.fromisoformat(venues_cfg["target_window"]["end"]),
        venues=merged_venues,
        flights_cfg=flights_cfg,
        serpapi_key=SERPAPI_KEY,
        top_n_flights=4,
    )
    sheet_rows = sheet_venues.load_sheet_rows(CLIMBING_CSV)
    guidebooks = _load_json(ROOT / "guidebooks.json", {})
    extra_climbing_data = _load_json(ROOT / "extra-climbing.json", {})
    tag_spec = render.TagSpec.load(REPO_ROOT / "knowledge" / "data" / "tag-spec.json")
    mp_climbs = climbs.load_mp_climbs()
    print(f"multi-pitch climbs loaded: {len(mp_climbs)}")
    return ctx, sheet_rows, guidebooks, extra_climbing_data, tag_spec, mp_climbs


def build_banner(ctx, ranked):
    in_window = any(r.get("fc") and r["fc"].get("in_window") for r in ranked)
    horizon = next((r["fc"]["horizon"] for r in ranked if r.get("fc")), "?")
    now = datetime.now(timezone.utc)
    if in_window:
        return ("ok", "✅ Trip dates are within the 16-day forecast — venues ranked on the <b>actual trip-window forecast</b>.")
    days_out = (ctx.target_start - now.date()).days
    has_sea = any(r.get("seasonal") for r in ranked)
    sea_txt = (" blended with a <b>long-range outlook</b> (model reach ~45 days; shown per venue)" if has_sea else "")
    # The 16-day forecast covers today + 15 days, so it first reaches the trip
    # start 15 days before it — that's the day this banner flips to the ✅ version.
    reaches_start = ctx.target_start - timedelta(days=15)
    try:
        horizon_lbl = date.fromisoformat(horizon).strftime("%-d %b")
    except ValueError:
        horizon_lbl = horizon
    return ("", f"📅 Trip starts <b>{ctx.target_start:%-d %b}</b> ({days_out} days out) — still past the live "
                f"forecast, which currently reaches {horizon_lbl}. "
                f"Ranked on <b>typical {ctx.period_lbl} weather</b> ({ctx.climo_years[0]}–{ctx.climo_years[-1]}){sea_txt}. "
                f"Live forecast reaches your dates on {reaches_start:%-d %b}.")


def main():
    ctx, sheet_rows, guidebooks, extra_climbing_data, tag_spec, mp_climbs = build_context()

    env_cache = EnvCache(ROOT / "venue-env.json")
    climo_cache = DiskCache(ROOT / "climo-cache.json",
                             key_filter=lambda k: k.endswith("|" + weather.CLIMO_VER))
    stays_cache = DiskCache(ROOT / "stays-cache.json")
    link_health_cache = DiskCache(ROOT / "link-health-cache.json")
    quota_guard = quota.AlwaysAllowQuotaGuard()
    flight_cache = quota.NullFlightCache()
    flights_data = _load_json(ROOT / "flights-latest.json", {})

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    results = [scoring.evaluate(v, ctx, env_cache, climo_cache, stays_cache, link_health_cache, mp_climbs)
               for v in ctx.venues]
    for r in results:                 # composite = weather + travel + venue fit
        scoring.apply_composite(r, ctx, mp_climbs)
    ranked = scoring.rank(results)

    prev_prices = flights_data.get("venues") or {}
    priced = flights.price_top_venues(ranked, ctx, quota_guard, flight_cache, prev_prices)  # provisional top-N (quota-capped)
    for r in ranked[:ctx.top_n_flights]:  # refine those with real flight prices…
        scoring.apply_composite(r, ctx, mp_climbs)
    ranked = scoring.rank(results)            # …then price any NEWCOMERS to the top-N
    priced = flights.price_top_venues(ranked, ctx, quota_guard, flight_cache, prev_prices)  # (already-priced venues are skipped)
    for r in ranked[:ctx.top_n_flights]:
        scoring.apply_composite(r, ctx, mp_climbs)
    ranked = scoring.rank(results)            # …and settle the final order

    # persist (so history captures prices and a no-key run can reuse them)
    flights_data["rep_combo"] = ctx.rep_combo
    flights_data["venues"] = priced
    flights_data["checked_at"] = (now.strftime("%Y-%m-%d %H:%M UTC")
                                   + (" (Google Flights/SerpApi)" if ctx.serpapi_key else " (no key — links only)"))
    (ROOT / "flights-latest.json").write_text(json.dumps(flights_data, indent=2) + "\n")

    banner = build_banner(ctx, ranked)

    data = render.build_data(ranked, now, banner, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec)
    INDEX.write_text(render.render_page(data, tag_spec))
    slugs = render.write_venue_pages(data, REPO_ROOT, tag_spec)
    n_urls = render.write_seo_files(slugs, today, REPO_ROOT)
    md = render.build_md(ranked, now, banner, ctx, mp_climbs,
                          match_sheet_row=lambda name: sheet_venues.match_sheet_row(name, sheet_rows))
    DAILY.write_text(md)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(md)
    print(f"Wrote index.html, {len(slugs)} venue pages, sitemap ({n_urls} urls), "
          f"daily-report.md, history/{today}.md")
    print("Ranking:", " > ".join(r["venue"]["name"] for r in ranked if r.get("ok") and r["score"] >= 0))


if __name__ == "__main__":
    main()

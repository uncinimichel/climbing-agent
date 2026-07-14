"""One registry trip, end to end (decision #33 M3): evaluate → rank → price →
flex → render → write. Extracted verbatim from update_report.py's main() so
the identical code path renders the legacy NI trip to the site root and any
other registry trip to trips/<slug>/.

Sharing model: everything trip-independent is loaded ONCE per run via
load_shared() — the repo-root cache/ objects (lat/lon keys, so venue data is
fetched once per venue per day no matter how many trips), the tag taxonomy,
multi-pitch.com climbs and the sheet rows — and passed to every run_trip().
DiskCache serves from memory after load, so trip B's lookups hit what trip A
just fetched even mid-run.
"""
import json
from datetime import date, datetime, timedelta, timezone

from . import climbs, flights, quota, rank_history, render, scoring, sheet_venues, trips, weather
from .cache import DiskCache, EnvCache


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def load_shared(repo_root):
    """Trip-independent state, loaded once per run however many trips render."""
    cache_dir = repo_root / "cache"
    return {
        # 18h: a same-day re-render reuses the cron's fetch; an older file is
        # rejected so a manual run can't rank the board on a days-old forecast
        "env_cache": EnvCache(cache_dir / "venue-env.json", max_age_hours=18),
        "climo_cache": DiskCache(cache_dir / "climo-cache.json",
                                  key_filter=lambda k: k.endswith("|" + weather.CLIMO_VER)),
        "stays_cache": DiskCache(cache_dir / "stays-cache.json"),
        "link_health_cache": DiskCache(cache_dir / "link-health-cache.json"),
        "tag_spec": render.TagSpec.load(repo_root / "knowledge" / "data" / "tag-spec.json"),
        "mp_climbs": climbs.load_mp_climbs(),
        "sheet_rows": sheet_venues.load_sheet_rows(repo_root / "climbing-trips.csv"),
    }


def trip_context(trip, repo_root, serpapi_key=None, top_n_flights=10):
    """TripContext from a registry entry + its trip dir's config files. The
    Google-Sheet venue merge only applies to the trip the sheet curates
    (registry flag `sheet_merge`) — other trips rank exactly the venues in
    their own venues.json."""
    d = trips.trip_dir(repo_root, trip)
    venues_cfg = json.loads((d / "venues.json").read_text())
    flights_cfg = json.loads((d / "flights.json").read_text())
    base = venues_cfg["venues"]
    merged = (sheet_venues.build_venues(base, repo_root / "climbing-trips.csv")
              if trip.get("sheet_merge") else base)
    return trips.context_for(trip, merged, flights_cfg,
                              serpapi_key=serpapi_key, top_n_flights=top_n_flights)


def build_banner(ctx, ranked):
    fcs = [r["fc"] for r in ranked if r.get("fc") and r["fc"].get("in_window")]
    kmax = max((f.get("cover_days", 0) for f in fcs), default=0)
    n = ctx.trip_days
    horizon = next((r["fc"]["horizon"] for r in ranked if r.get("fc")), "?")
    now = datetime.now(timezone.utc)
    if fcs and kmax >= n:
        return ("ok", "✅ Trip dates are within the 16-day forecast — venues ranked on the <b>actual trip-window forecast</b>.")
    if kmax > 0:
        # forecast reaches only the first part of the window — be honest that most
        # venues are a coverage-weighted blend, not a full-window forecast
        return ("", f"🛰️ The 16-day forecast now reaches the <b>first {kmax} of your {n} trip days</b> — "
                    f"those venues blend the live forecast with typical {ctx.period_lbl} weather for the "
                    f"days still beyond range; the rest rank on typical weather. "
                    f"Full-window forecast fills in over the next few days.")
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


def run_trip(trip, repo_root, shared, serpapi_key=None, site_root=False,
             quota_guard=None, flight_cache=None, now=None):
    """Render one trip completely. site_root=True keeps the legacy layout
    (repo_root/index.html + venues/ + sitemap — the NI trip until M4);
    otherwise the dashboard goes to trips/<slug>/index.html with no per-venue
    pages or SEO files (M4 decides their multi-trip shape). Per-trip state
    (flights-latest, rank-history, daily report, history/) always lives in
    the trip's own directory. Returns the ranked list."""
    ctx = trip_context(trip, repo_root, serpapi_key=serpapi_key)
    d = trips.trip_dir(repo_root, trip)
    quota_guard = quota_guard or quota.AlwaysAllowQuotaGuard()
    flight_cache = flight_cache or quota.NullFlightCache()
    flights_data = _load_json(d / "flights-latest.json", {})
    mp_climbs = shared["mp_climbs"]

    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()

    results = [scoring.evaluate(v, ctx, shared["env_cache"], shared["climo_cache"],
                                shared["stays_cache"], shared["link_health_cache"], mp_climbs)
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

    # ±flex_days trip shifts for the TOP venue only (quota-capped by design):
    # last-known flex prices are reused only if yesterday's top venue is the same
    top = next((r for r in ranked if r.get("ok") and r["score"] >= 0), None)
    flex = None
    if top:
        prev_flex_blk = flights_data.get("flex") or {}
        prev_flex = (prev_flex_blk.get("travellers")
                     if prev_flex_blk.get("venue") == top["venue"]["name"] else None)
        flex = flights.flex_alternatives(top["venue"], ctx, quota_guard, flight_cache, prev_flex)
        if flex:
            top["flex"] = flex
    flights_data["flex"] = ({"venue": top["venue"]["name"], "travellers": flex}
                            if flex else None)

    # day-over-day movement: annotate vs yesterday's order, record today's
    rank_history.apply(d / "rank-history.json", today, ranked)

    # persist (so history captures prices and a no-key run can reuse them)
    flights_data["rep_combo"] = ctx.rep_combo
    flights_data["venues"] = priced
    flights_data["checked_at"] = (now.strftime("%Y-%m-%d %H:%M UTC")
                                   + (" (Google Flights/SerpApi)" if ctx.serpapi_key else " (no key — links only)"))
    (d / "flights-latest.json").write_text(json.dumps(flights_data, indent=2) + "\n")

    banner = build_banner(ctx, ranked)
    guidebooks = _load_json(d / "guidebooks.json", {})
    extra_climbing_data = _load_json(d / "extra-climbing.json", {})
    tag_spec = shared["tag_spec"]

    data = render.build_data(ranked, now, banner, ctx, mp_climbs, guidebooks, extra_climbing_data, tag_spec)
    if site_root:
        (repo_root / "index.html").write_text(render.render_page(data, tag_spec))
        slugs = render.write_venue_pages(data, repo_root, tag_spec)
        n_urls = render.write_seo_files(slugs, today, repo_root)
        where = f"index.html, {len(slugs)} venue pages, sitemap ({n_urls} urls)"
    else:
        out = repo_root / "trips" / trip["slug"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(render.render_page(
            data, tag_spec, depth=2, canonical_path=f"trips/{trip['slug']}/"))
        where = f"trips/{trip['slug']}/index.html"
    md = render.build_md(ranked, now, banner, ctx, mp_climbs,
                          match_sheet_row=lambda name: sheet_venues.match_sheet_row(name, shared["sheet_rows"]))
    (d / "daily-report.md").write_text(md)
    (d / "history").mkdir(exist_ok=True)
    (d / "history" / f"{today}.md").write_text(md)
    print(f"[{trip['slug']}] wrote {where}, daily-report.md, history/{today}.md")
    print(f"[{trip['slug']}] ranking:",
          " > ".join(r["venue"]["name"] for r in ranked if r.get("ok") and r["score"] >= 0))
    return ranked

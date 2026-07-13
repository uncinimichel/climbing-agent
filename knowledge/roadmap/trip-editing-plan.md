# Trip editing plan — multi-trip, file-backed, local admin forms

*(Stage 6 slice, planned 13 Jul 2026 — see decision [#33](decisions.md). Approved UI
mockup: three screens — trips list / new trip / manage trip — in the dashboard's own
design language, with a live "dashboard header pill" preview as the signature element.)*

## Decisions this plan is built on (Michel, 13 Jul 2026)

1. **Storage stays files + JSON for now.** Trips live in a committed `trips.json`;
   per-trip data keeps the directory-per-trip pattern. A DB + API comes *later* —
   the schema below is designed to be that API's contract, not a throwaway.
2. **Single editor: Michel**, via a **local-only admin server** (the `agent/server.py`
   pattern: FastAPI on localhost, never deployed). No auth, no AWS.
3. **Flight quota: nearest live trip only.** Only the soonest-departing live trip
   spends SerpApi quota; every other trip shows the existing distance-based estimates.
4. **Build now, behind a flag.** Multi-trip rendering lands guarded by an env flag;
   the NI trip stays on the untouched default path until proven (trip ends 28 Jul).
5. **Public root becomes the trips list.** Each trip dashboard moves to
   `trips/<slug>/`; the NI move happens **after** the trip ends (M4), with hash-link
   forwarding and sitemap updates.
6. **Traveller homes are geocoded from city text** (Open-Meteo geocoding API, free);
   airports derived with manual override in the form. `"Belfast / Dublin"`-style
   alternatives keep working — cheaper origin wins, nearest home coord used.

## Where the code already is

The heavy lifting was done by the `engine/` extraction: `TripContext`
(`engine/models.py`) already parameterises dates, venues and flight config, and
`flights.json` already carries per-traveller `route.traveller_origins` /
`traveller_coords`. What is still hardcoded to `("michel", "dan")`:

- `engine/models.py:44-51` — `TRAVELLERS`, `ORIGIN_CITY`, `ORIGIN_COORDS` constants.
- `engine/render.py` — pills (`:1659`), flight cards in `PAGE_JS` (`:1638`), payload
  (`:229`, `:435`, `:520`), markdown table (`:1775`, `:1943`).
- `trip-ni-july-2026/venues.json` — per-venue `travel` dicts keyed by traveller.
- One trip, one output: the driver (`trip-ni-july-2026/scripts/update_report.py`,
  now a 187-line thin shell) renders root `index.html` only.

## trips.json — the future API contract

Repo root `trips.json` (validated by a new `engine/trips.py`):

```json
{ "schema": 1, "trips": [ {
    "slug": "ni-july-2026",
    "name": "Northern Ireland",
    "status": "live",                    // live | draft | ended
    "start": "2026-07-24", "end": "2026-07-28",
    "dir": "trip-ni-july-2026",          // legacy; new trips default trips/<slug>/
    "travellers": [
      { "key": "michel", "name": "Michel",
        "homes": [ {"city": "London", "lat": 51.5074, "lon": -0.1278} ],
        "airports": ["LGW","LHR","LTN","STN","LCY"] },
      { "key": "dan", "name": "Dan",
        "homes": [ {"city": "Belfast", "lat": 54.607, "lon": -5.926},
                   {"city": "Dublin",  "lat": 53.349, "lon": -6.260} ],
        "airports": ["BFS","BHD","DUB"] } ]
} ] }
```

Per-trip venue lists, caches, history and `flights.json` stay in the trip's `dir`
(unchanged shapes; `venues.json` `travel` dicts become *optional* per-traveller
overrides — unknown travellers fall back to the existing distance estimate).
When the DB/API arrives, `trips.json` rows become table rows and the admin server's
read/write functions become the first API endpoints (a `TripStore` seam mirroring
`engine/cache.py`'s `Cache` protocol keeps that swap mechanical).

## Milestones

**M1 — `trips.json` + loader (no behaviour change).** Schema above; `engine/trips.py`
with `load_trips()` / `trip_context(trip)`; NI entry generated from today's config;
driver reads its `TripContext` through it. Smoke test: rendered output unchanged.

**M2 — traveller generalisation** (the "M2+" flagged in `models.py`). Kill the
`TRAVELLERS`/`ORIGIN_CITY`/`ORIGIN_COORDS` constants; thread `ctx.travellers` through
`flights.py`, `scoring.py`'s distance signal, and `render.py` (pills, flight cards,
payload, markdown all data-driven). The `render.py:1659` hardcode dies here.

**M3 — multi-trip rendering, behind `MULTI_TRIP=1`.** Driver loops live trips from
`trips.json`: each renders to `trips/<slug>/` (own venue pages, own daily report).
Nearest-departing live trip gets SerpApi pricing; the rest estimate. Includes the
shared fetch layer below. Flag stays off in `weather.yml` until after 28 Jul.

## Shared fetch layer — one API call per venue per day, however many trips

Every weather fetch in `engine/weather.py` is already keyed purely on coordinates —
`forecast`/`tides`/`seasonal`/`ensemble` go through `EnvCache.raw(lat, lon, kind)`
(decision #24's trip-independent env layer), and stays/link-health caches are
lat/lon-keyed too. What makes calls duplicate across trips today is only *where the
cache files live*: inside the trip's own directory
(`trip-ni-july-2026/venue-env.json`, `climo-cache.json`, `stays-cache.json`, …).
M3 therefore:

1. **Moves the caches to a shared repo-root `cache/`** (seeded by merging the NI
   trip's existing files — keys don't collide, they're coordinates).
2. **Union-fetch pass before the trip loop:** the driver collects the unique
   venues across all live trips, refreshes the env layer once per unique
   `(lat, lon)`, then every trip ranks/renders from it.
3. **One cache instance per run:** the same `EnvCache`/`DiskCache` objects are
   passed to every trip — `DiskCache` serves from memory, so even a mid-run fetch
   by trip A is a memory hit for trip B.
4. **Flights dedupe on route + dates, deliberately not more.** `FlightCache` is
   already keyed `("DEP->ARR", "out|back")`, so two travellers (or trips) sharing a
   route *and* dates cost one SerpApi call; different dates correctly re-price.
   With the nearest-trip-only policy the cross-trip case is mostly moot, but the
   shared cache makes it free when it happens. `prev_prices`
   (`flights-latest.json`) stays per-trip — last-known-good is date-specific.

Known non-reuse: `climatology()`'s cache key embeds the trip's graph window
(`{lat},{lon}|{years}|{mmdd}-{mmdd}|ver`), so two trips with different dates fetch
separate climatology slices. Correct today, cheap (archive API, free); if it ever
matters, widen to one whole-year fetch per venue and slice in code.

When the DB/API arrives (M6), these caches become tables with the same keys — this
was exactly the paused plan's `DynamoCache` observation: no trip/user in the key
means caching is shared across everyone's trips for free.

**M4 — root becomes the trips list** (*gated on the NI trip ending, ~29 Jul*).
Server-rendered trips-list page at root per the approved mockup (status tags,
per-day condition strips: forecast / typical-hatched / as-it-happened from each
trip's history). NI dashboard moves to `trips/ni-july-2026/`; a small shim on the
new root forwards legacy `/#venue-slug` deep links to the primary trip's page;
`sitemap.xml` and venue back-links regenerate.

**M5 — local admin server (the approved forms).** Localhost FastAPI app (pattern:
`agent/server.py`) serving the three mockup screens wired to `trips.json`: list,
create (city → Open-Meteo geocode → coords + suggested airports, editable), manage
(edit fields, pause = `status: draft`, delete with confirm). Validates via
`engine/trips.py` before writing; optional auto-commit. Local page can load the real
Bricolage Grotesque / IBM Plex webfonts. Only depends on M1 — can land early.

**M6 — DB + API (deferred, deliberately).** Not in scope now. Path: `TripStore`
protocol → SQLite/Postgres implementation → the admin server's endpoints become the
API → revisit the paused multi-user plan (auth/quota-guard) only if editing ever
goes beyond Michel.

## Sequencing & risk

M1 → M2 now (each with the render-unchanged smoke test), M3 next with the flag off,
M5 any time after M1. M4 waits for the trip to end — the one user-facing URL move
happens once, when nobody is mid-trip on the page. Riskiest step is M2 (touches
ranking + render for the live trip); the smoke test plus the flag keep the 06:00 UTC
report safe. SerpApi exposure is unchanged by design (one trip prices, same as today).

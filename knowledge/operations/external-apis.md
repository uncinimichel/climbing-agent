# External APIs

Every external source the engine touches, with keys, quotas, and failure behaviour.
Golden rule: **any single source failing must not fail the build** — degrade to a weaker
basis or a search link.

## Open-Meteo — weather (free, no key)

Three endpoints, one provider, consistent format. The backbone of the ranking.

| Endpoint | Host | Gives | Used for |
|---|---|---|---|
| **Archive** | `archive-api.open-meteo.com` | ERA5 historical (July averages) | Climatology base ranking + per-venue mini-graph. One ranged request/venue → deterministic, and **disk-cached** (below). |
| **Forecast** | `api.open-meteo.com` | 16-day live forecast — sky/temp/precip **plus** gusts, sunshine, precip-hours, wind direction (daily) and dew point/humidity (hourly) | Ranks the trip once in range (~8 July); supersedes other bases. Extra fields feed the friction/drying/heat score terms — see [condition-algorithm](../data/condition-algorithm.html). |
| **Seasonal** | `seasonal-api.open-meteo.com` | CFS ensemble, ~45 days–9 months | Sub-seasonal outlook; blended 70/30 into ranking beyond live range + per-day overlay on the chart. |
| **Geocoding** | `geocoding-api.open-meteo.com` | place-name → lat/lon | Fallback for spreadsheet venue rows not in the script's `GAZETTEER`. |

- **Key:** none. **Retry:** 4× on failure (4xx except 429 not retried; errors redacted).
- **Limits:** free non-commercial tier ≈ **10,000 calls/day** (~5,000/hour, ~600/minute) —
  but archive requests are **weight-multiplied** by their date span. Observed in practice
  (2026-07-03): **2–3 full 42-venue runs within an hour trip 429s** on the archive host.
- **Mitigation:** climatology never changes (fixed 2021–24 years), so it's cached in
  **`trip-ni-july-2026/climo-cache.json`** (committed). Steady-state archive load is now
  ~zero; only *new* venues fetch. Forecast/seasonal stay live every run.
- **Degradation:** seasonal failure → climatology-only; the banner stays honest about the
  basis.

## Google Sheets — the venue master list (free, public CSV export)

- **What:** Michel curates candidate areas (38+ rows) with judgment columns — volume,
  difficulty, travel time, hub, minimum trip — in the
  [venue spreadsheet](https://docs.google.com/spreadsheets/d/1N4Xs-aSGFc8-ibysqpdCvQIfMH4Rjx4n5WQnqITGPC8/edit).
- **How:** CI re-downloads the CSV export every run into `climbing-trips.csv` (committed,
  so history tracks sheet evolution) and `build_venues()` turns **every row** into a
  ranked venue — curated `venues.json` entries are enriched, unknown rows get coords +
  airports from `GAZETTEER` or the geocoder.
- **Degradation:** download failing or malformed → the committed CSV copy is used.

## SerpApi — Google Flights (keyed, quota-limited)

- **Host:** `serpapi.com` (Google Flights engine).
- **Key:** `SERPAPI_KEY` — GitHub Actions secret + gitignored `.env`. Never committed.
- **What:** a representative round-trip per venue for Michel (from London) and Dan (from
  Belfast/Dublin) into the venue airport; 3 best-value options with **outbound** times +
  book links.
- **Quota:** free plan = **250 searches/month**, **250/hour** rate limit. This is the one
  hard ceiling in the stack (Open-Meteo is effectively unlimited for our volume).
- **Quota discipline:** only the **top-N (=4)** ranked venues are priced, one combo each
  → ≤ 8 searches/day. `TOP_N_FLIGHTS` throttles this.
- **Monitoring:** every build logs remaining quota via `account.json` (which consumes **no**
  search) → [live API usage & cost page](serpapi-quota.html) (SerpApi meter + a cost/limits
  table for the **whole** stack, incl. Overpass/Open-Meteo cache sizes), history in
  `trip-ni-july-2026/serpapi-usage.json`. Script: `scripts/serpapi_quota.py`.
- **Degradation:** missing/exhausted key → flight cells fall back to "search ↗" links; the
  build still succeeds.
- **NI special case:** Dan is `local` → no flight priced for him at NI venues.

## OpenStreetMap Overpass — places to stay (free, no key)

- **Hosts:** `overpass-api.de/api/interpreter`, mirror fallback
  `overpass.kumi.systems/api/interpreter`. One query per venue: named
  `tourism=*` lodging within **15 km** of the crag coordinates.
- **What:** real named accommodation in the three shapes that matter for this trip —
  **houses/apartments** (Airbnb-style: `apartment`, `chalet`, `guest_house`),
  **campsites** (`camp_site` — flagged *bring your own tent, mats and cooking kit*),
  and **hotels** (`hotel`, `hostel`, `alpine_hut`, `motel`; one room, 2 adults).
  Up to 3 options per category, nearest first, with the OSM `website` tag,
  a Booking.com name search, and a Google Maps link per option, plus area-level
  **Airbnb/Booking searches pre-filled with the trip dates + 2 adults**.
- **Prices:** OSM has none. Each lodging type carries a **typical nightly estimate**
  (labelled *est.* in the UI — e.g. campsite ~£20, guest house ~£85, hotel ~£115 for 2)
  which also feeds the **stay score** inside the composite's travel component — see
  [condition-algorithm](../data/condition-algorithm.html).
- **Key:** none, but a **real User-Agent is required** — the default Python UA gets
  HTTP 406. `_get` now sends `climbing-agent/1.0` on every request.
- **Limits:** public instance load-sheds bursts (429/504). Mitigation: results are
  **disk-cached in `trip-ni-july-2026/stays-cache.json`** (committed, like the
  climatology cache — lodging stock changes slowly), 1 s pacing between uncached
  queries, retry + mirror fallback.
- **Degradation:** all mirrors failing → that venue shows the date-filled search
  links only, and its stay score drops out of the travel mean. Never fails the build.

## multi-pitch.com `data.json` — curated climbs (free)

- The platform's own climb dataset, pre-cleaned. Nearby climbs are **geo-matched** to each
  venue's `lat`/`lon` and linked from the card.
- No key. Feeds the "source links" and (future) the curated master index.

## Windy — forecast deep-link (no API)

- The card's "forecast ↗" links to Windy for the venue coordinates. Presentation only, no
  data pulled.

## Longer-range weather — researched alternatives

If more sub-seasonal skill/resolution is ever needed (all beyond the current free stack):

| Option | Notes |
|---|---|
| **Open-Meteo Seasonal** | **Chosen** — free, no key, same provider/format. Already wired in. |
| Visual Crossing Timeline | Free tier w/ key; one call returns near-date forecast + statistical estimate beyond. |
| OpenWeather One Call `day_summary` | Statistical estimate for any future date (the old multi-pitch project's key). |
| Meteomatics / AccuWeather 45-day | Paid, higher skill. |

## Planned sources ⛔ (Phase 1 gaps)

- **Social condition scrapers** — Meta groups, X, TikTok geotags, guide whitelists.
  Respect platform ToS + privacy; emit only aggregated, non-personal summaries.
- **Static guidebook/register crawlers** — web-scale ingestion of unstructured guides.
- **Tides** — a free/low-cost tide source for sea-cliff venues (Fair Head, Gower,
  Cornwall) to flag non-tidal climbing windows.

## Rules for adding an API

1. Wrap in a **retrying** fetch; never let it hard-fail the build.
2. **Degrade gracefully** — define the fallback (weaker basis, search link, cached value).
3. Keys go in **secrets + gitignored `.env`**, never in code or committed files.
4. **Quota-guard** paid sources (cap the number of calls; make the cap a constant).
5. Document it **here** — endpoint, key, quota, degradation.

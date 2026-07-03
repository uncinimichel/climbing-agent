# External APIs

Every external source the engine touches, with keys, quotas, and failure behaviour.
Golden rule: **any single source failing must not fail the build** — degrade to a weaker
basis or a search link.

## Open-Meteo — weather (free, no key)

Three endpoints, one provider, consistent format. The backbone of the ranking.

| Endpoint | Host | Gives | Used for |
|---|---|---|---|
| **Archive** | `archive-api.open-meteo.com` | ERA5 historical (July averages) | Climatology base ranking + per-venue mini-graph. One ranged request/venue → deterministic. |
| **Forecast** | `api.open-meteo.com` | 16-day live forecast — sky/temp/precip **plus** gusts, sunshine, precip-hours (daily) and dew point/humidity (hourly) | Ranks the trip once in range (~8 July); supersedes other bases. Extra fields feed the friction/drying score terms — see [condition-algorithm](../data/condition-algorithm.html). |
| **Seasonal** | `seasonal-api.open-meteo.com` | CFS ensemble, ~45 days–9 months | Sub-seasonal outlook; blended 70/30 into ranking beyond live range. |

- **Key:** none. **Retry:** 4× on failure.
- **Limits:** free non-commercial tier ≈ **10,000 calls/day** (~5,000/hour, ~600/minute).
  Our load is 3 calls × venues × 1 run/day → well under 1% of the cap; effectively
  unlimited for us. No usage endpoint exists, so the only signal is HTTP 429.
- **Degradation:** seasonal failure → climatology-only; the banner stays honest about the
  basis.

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
  search) → [live quota page](serpapi-quota.html), history in
  `trip-ni-july-2026/serpapi-usage.json`. Script: `scripts/serpapi_quota.py`.
- **Degradation:** missing/exhausted key → flight cells fall back to "search ↗" links; the
  build still succeeds.
- **NI special case:** Dan is `local` → no flight priced for him at NI venues.

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

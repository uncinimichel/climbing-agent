# Phase 1 — The Scraper (Raw Data Capture)

> **Purpose:** continuous, automated ingestion of both historical records and live
> environmental reality from the open web. The foundation everything else stands on.
> **Status:** ⚠️ Partial — structured API pulls only; social & guidebook scrapers planned.

## Vision

Two tracks of scrapers running continuously:

- **Static scrapers** — crawl legacy, unstructured guidebook registers and text
  databases across the web for the durable facts about a climb (name, sector, length,
  grade, style, protection notes).
- **Live social scrapers** — monitor active regional climbing groups, local
  mountain-guide whitelists, and geotagged hashtags across **Meta, X, TikTok** for
  *immediate, real-world condition updates* ("Fair Head bone dry this weekend").

Static scrapers answer *"what is this climb?"*; social scrapers answer *"what is it
like right now?"*.

## What exists today ✅

Three structured, well-behaved ingestion sources, all inside `update_report.py`:

| Source | What it pulls | Key? |
|---|---|---|
| **Open-Meteo Archive** | July climatology (ERA5 historical averages) | none |
| **Open-Meteo Forecast** | 16-day live forecast | none |
| **Open-Meteo Seasonal** | ~45-day sub-seasonal outlook (CFS ensemble) | none |
| **multi-pitch.com `data.json`** | Nearby curated climbs, geo-matched to venue lat/lon | none |
| **SerpApi (Google Flights)** | Round-trip fares for top-N venues × travellers | `SERPAPI_KEY` |

See [`operations/external-apis.md`](../operations/external-apis.md) for endpoints,
quotas, and retry behaviour.

## What's missing ⛔ (planned)

- **Social condition scrapers** (Meta groups, X, TikTok geotags, guide whitelists).
  This is the highest-value gap — it's the only source of *live, human* condition truth.
- **Static guidebook / register crawlers** at web scale (currently the curated climb
  data comes pre-cleaned from multi-pitch.com's own `data.json`).
- A **raw-record store** distinct from normalized data, so Phase 2 can re-parse.

## Design constraints & principles

1. **Free-tier first.** Prefer keyless, free APIs (Open-Meteo). Paid/keyed sources
   (SerpApi) are quota-guarded and degrade gracefully when unavailable.
2. **Retry, don't crash.** Weather calls retry 4×; any single source failing must not
   fail the build (fall back to a weaker basis or a search link).
3. **Respect sources.** Rate-limit, cache, honour robots/ToS. Social scraping must
   respect platform terms and privacy — no personal data into the public repo.
4. **Raw ≠ clean.** Phase 1's job is capture, not judgement. Cleaning and
   standardization belong to Phase 2; quality filtering to Phase 3.
5. **Geo as the join key.** Venues carry `lat`/`lon`; climbs and conditions are matched
   to venues by geographic proximity.

## Interfaces

- **Input:** `venues.json` (which places to query) + `flights.json` (which routes).
- **Output:** per-venue normalized records consumed by Phase 2 — weather day-records,
  climb lists, flight quotes.

## When building here

- Add a new data source → wrap it in a retrying fetch, degrade gracefully, document it
  in `operations/external-apis.md`, and never commit its key.
- Adding a social scraper → keep raw captures out of the public repo (privacy); emit only
  aggregated, non-personal condition summaries downstream.
- New venues are added in `venues.json`, not in scraper code (config-driven).

# Data Flow

How a single data point travels from the open web to the user's dashboard, and where
state is persisted. Follows the four layers end to end.

## End-to-end path

```
  OPEN WEB / APIs                 INGEST (Phase 1)            NORMALIZE (Phase 2)
  ─────────────                   ────────────────            ───────────────────
  Open-Meteo archive   ─┐
  Open-Meteo forecast  ─┼──▶  update_report.py fetch()  ──▶  per-venue daily records
  Open-Meteo seasonal  ─┘        (retry 4×, JSON)             {rain%, precip_mm, tmax, wind}
  multi-pitch data.json ──▶  geo-match nearby climbs    ──▶  climb list per venue
  SerpApi Google Flights ─▶  price top-N venues         ──▶  {price, times, book URL}

  CURATE (Phase 3)                        RANK & RENDER (Phase 2→4)          PERSIST
  ────────────────                        ─────────────────────────          ───────
  Google Sheet ▸ climbing-trips.csv  ─┐                                       index.html
    (master list, refreshed each run) │   composite score each venue:         daily-report.md
  venues.json (curated overrides)    ─┼─▶  0.55·weather + 0.25·travel         history/<date>.md
  GAZETTEER / geocoder (new rows)    ─┤    + 0.20·venue fit                   flights-latest.json
  flights.json (route + combos)      ─┘    two passes (price top-N between)   climo-cache.json
                                           → donut breakdown + tags + charts  git commit (the archive)
```

## Step by step

1. **Trigger.** GitHub Actions fires (cron 06:00 UTC / push / manual). One build job.
2. **Read config (Phase 3, curation).** CI refreshes `climbing-trips.csv` from the
   Google Sheet, and `build_venues()` turns **every sheet row** into a venue — enriched
   by curated `venues.json` entries where they exist, generated from `GAZETTEER`
   coords/airports (or the free geocoder) where they don't. `flights.json` still defines
   the route + date combos. Editing the sheet is all it takes to change the ranking.
3. **Ingest (Phase 1).** For each venue:
   - Fetch Open-Meteo **archive** → July climatology (deterministic, one ranged request).
   - Fetch Open-Meteo **forecast** → 16-day live (used once the trip is in range).
   - Fetch Open-Meteo **seasonal** → ~45-day outlook.
   - Geo-match **multi-pitch.com `data.json`** → nearby curated climbs.
4. **Normalize + score (Phase 2).** Reduce each horizon to per-day records and compute
   `day_score` / `climo_score`; blend into one venue score. See
   [`data/condition-algorithm.md`](../data/condition-algorithm.md).
5. **Rank (Phase 2→3).** Sort venues by score desc; tie-break by `priority` (NI preferred).
   Choose the active **weather basis** and state it honestly in the banner.
6. **Price flights (Phase 1, quota-guarded).** For the **top-N** ranked venues only,
   call SerpApi for Michel + Dan; write `flights-latest.json`.
7. **Render (Phase 4).** Emit `index.html` (cards: mini-graph + flights + source links),
   `daily-report.md`, and a dated `history/<date>.md`.
8. **Persist.** `git commit + push` — the commit *is* the archive. `upload-pages-artifact`
   → `deploy-pages` publishes the site.

## Planned: split the environment layer out of the monolith *(⛔ planned)*

Steps 3–7 above run **inline in one script** (`update_report.py`) for one hardcoded trip.
The planned refactor (decision [#24](../roadmap/decisions.md), design in
[`venue-env-cache.md`](venue-env-cache.md)) breaks the single build along its natural seam —
**trip-independent environment data** vs. **trip-specific booking data**:

```
  fetch_env.py    weather + tide + climo   ─▶  venue-env.json   (once per venue/day, latest-only)
                     (steps 3–4 above)              │  keyed (venue, date)
                                                    ▼
  fetch_trip.py   flights + stays for a trip   ── reads env cache ──▶  trip data
                     (steps 5–6 above)
                                                    ▼
  build_report.py  render index.html          ── env cache + trip data ──▶  site (step 7)
```

Weather stays **O(venues)** — computed once and reused by every trip, every user, and the
website's "browse a venue before committing to a trip" path — while flights stay per-trip.
`build_report` reads `fetched_at` from the cache and **degrades** (stale badge → last-good →
climatology) rather than rendering silently-stale numbers. Nothing here is built yet; the
current single-job flow above is what runs today.

## Where state lives (repo-as-database)

| State | Where | Lifecycle |
|---|---|---|
| Which venues to monitor | `venues.json` | Hand-edited; single source of truth. |
| Flight route + date combos | `flights.json` | Hand-edited. |
| Latest flight prices | `flights-latest.json` | Overwritten each run; not wiped by weather-only runs. |
| Per-venue weather/tide *(⛔ planned)* | `venue-env.json` | Overwritten each run, latest-only, keyed `(venue, date)`; see [`venue-env-cache.md`](venue-env-cache.md). |
| Today's dashboard | `index.html`, `daily-report.md` | Regenerated every run. |
| Permanent history | `history/YYYY-MM-DD.md` + git log | Append-only; never overwritten. |
| Secrets | `SERPAPI_KEY` (Actions secret + gitignored `.env`) | Rotated manually. |

## Idempotency & determinism

- **Climatology is reproducible** — running the build twice yields identical rain% and
  ordering (deterministic historical averages). This is a verification checkpoint.
- **No-change runs commit nothing** and simply redeploy — safe to run often.
- **Graceful degradation** — a failed seasonal call drops to climatology-only; a missing
  `SERPAPI_KEY` drops flights to "search ↗" links. The build never hard-fails on an
  external outage.

## How this generalises to the full engine *(planned)*

At platform scale the same shape holds, with the manual/partial boxes filled in:
- Phase-1 gains **social + guidebook scrapers** writing raw records to a store.
- Phase-2 gains the **NLP Taxonomy Engine** (raw text → strict data dictionary) and a
  real **friction/seepage/drying** condition model.
- Phase-3's `venues.json` grows into an automated mapping of scraped data onto a
  **verified master index** of classic sectors.
- Phase-4 gains **embedded vector topos** and the **contingency engine** (auto "3 dry
  alternatives").

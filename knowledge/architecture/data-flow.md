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
  venues.json (master index, manual) ─┐
  climbing-trips.csv (shortlist)      ─┼─▶ score each venue:                  index.html
                                       │    live ▸ (climatology 70 / 45d 30)  daily-report.md
  flights.json (route + combos)       ─┘    sort desc, tie-break priority     history/<date>.md
                                            → build cards + mini-graphs       flights-latest.json
                                            → fold in flights                 git commit (the archive)
```

## Step by step

1. **Trigger.** GitHub Actions fires (cron 06:00 UTC / push / manual). One build job.
2. **Read config (Phase 3, manual curation).** `update_report.py` loads `venues.json`
   (which venues exist + travel modes) and `flights.json` (route + 3 date combos). These
   are the single sources of truth — the script queries only what they list.
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

## Where state lives (repo-as-database)

| State | Where | Lifecycle |
|---|---|---|
| Which venues to monitor | `venues.json` | Hand-edited; single source of truth. |
| Flight route + date combos | `flights.json` | Hand-edited. |
| Latest flight prices | `flights-latest.json` | Overwritten each run; not wiped by weather-only runs. |
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

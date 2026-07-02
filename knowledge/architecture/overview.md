# Architecture Overview

How the four vision layers map onto concrete components. This is the **target**
architecture; components that don't exist yet are marked *(planned)*. For what actually
runs today, see [`current-state.md`](current-state.md).

## The pipeline

```
┌── PHASE 1: SCRAPER ──────────┐  ┌── PHASE 2: AI TAXONOMY ─────┐  ┌── PHASE 3: CURATION ───┐  ┌── PHASE 4: PLANNER ──────┐
│ Static crawlers   (planned)  │  │ Taxonomy Engine  (planned)  │  │ Master index of        │  │ Split-screen dashboard   │
│ Social scrapers   (planned)  │  │  NLP → strict data dict     │  │  classic sectors        │  │  (index.html) ✅         │
│ Weather pulls     ✅         │──▶│ Predictive Condition Algo   │──▶│ Zero-garbage filter     │──▶│ Contingency engine       │
│ Flight pulls      ✅         │  │  friction/dry/seepage ⚠️     │  │  (manual venues.json ⚠️)│  │  (3 dry alts) (planned)  │
│ Climb geo-match   ✅         │  │  weather scoring  ✅         │  │                         │  │ Daily rebuild ✅         │
└──────────────────────────────┘  └─────────────────────────────┘  └─────────────────────────┘  └──────────────────────────┘
        raw JSON / text                normalized records              curated venue set            rendered HTML + history
```

Legend: ✅ live · ⚠️ partial / simplified · *(planned)* not built.

## Component ↔ layer map

| Vision layer | Concrete component (today or planned) | File / location |
|---|---|---|
| 1 · Scraper | Open-Meteo weather pulls (archive/forecast/seasonal) | `scripts/update_report.py` |
| 1 · Scraper | SerpApi Google Flights pulls | `scripts/update_report.py` |
| 1 · Scraper | multi-pitch.com `data.json` climb geo-match | `scripts/update_report.py` |
| 1 · Scraper | Static guidebook crawlers *(planned)* | — |
| 1 · Scraper | Social condition scrapers (Meta/X/TikTok) *(planned)* | — |
| 2 · Taxonomy | Strict data dictionary | `knowledge/data/taxonomy.md` |
| 2 · Taxonomy | NLP text→metadata parser *(planned)* | — |
| 2 · Condition Algo | `day_score` / `climo_score` / seasonal blend ✅ | `scripts/update_report.py` |
| 2 · Condition Algo | Friction / seepage / drying model ⚠️ (rain-proxy only) | `knowledge/data/condition-algorithm.md` |
| 3 · Curation | Master index of classic sectors ⚠️ (hand-curated) | `venues.json`, `climbing-trips.csv` |
| 4 · Planner | Live dashboard ✅ | `index.html` (GitHub Pages) |
| 4 · Planner | Per-venue weather mini-graph + flights ✅ | `index.html` |
| 4 · Contingency | "3 dry alternatives" auto-flag *(planned)* | — |
| — Orchestration | Daily serverless rebuild ✅ | `.github/workflows/weather.yml` |

## Runtime model: fully serverless & free

Everything runs inside **GitHub Actions on a schedule** — no laptop, no Claude in the
daily loop, no paid server.

```
                  ┌─────────────────── GitHub Actions (cloud) ───────────────────┐
 cron 06:00 UTC   │ build job:                                                    │
 (or push, or ──  │   1. checkout repo                                            │
  manual run)     │   2. python update_report.py                                 │
                  │        ├─ Open-Meteo archive   → July climatology + graph    │
                  │        ├─ Open-Meteo forecast  → 16-day live forecast        │
                  │        ├─ Open-Meteo seasonal  → 45-day outlook / venue      │
                  │        ├─ multi-pitch.com data.json → nearby climbs          │
                  │        ├─ rank venues (live ▸ climatology+45d blend)         │
                  │        └─ SerpApi Google Flights → top-N venues × travellers │
                  │   3. write index.html + daily-report.md + history/<date>.md  │
                  │   4. git commit + push  (the commit IS the history)          │
                  │   5. upload-pages-artifact                                   │
                  │ deploy job:                                                  │
                  │   6. deploy-pages ───────────────────────────┐              │
                  └──────────────────────────────────────────── │ ─────────────┘
                                                                 ▼
                          https://uncinimichel.github.io/climbing-agent/  (public)
```

- **Triggers:** `schedule` (daily 06:00 UTC), `push` to `main` (non-docs), and manual
  `workflow_dispatch`. All run the same build.
- **State:** the repo *is* the database. `flights-latest.json` = latest snapshot;
  `history/` + git log = the permanent archive.
- **Secrets:** only `SERPAPI_KEY` (GitHub Actions secret, mirrored in gitignored `.env`).
  Weather APIs need no key.
- **Failure modes:** weather APIs retry; if SerpApi is unavailable the build still
  succeeds and flight cells fall back to search links; a no-change run commits nothing
  and just redeploys.

## Key architectural decisions

See [`roadmap/decisions.md`](../roadmap/decisions.md) for the full log. The load-bearing ones:

1. **Config-driven, not code-driven.** `venues.json` and `flights.json` are single
   sources of truth; the script reads them to decide what to query and price.
2. **Three weather horizons, all free.** Live 16-day forecast › climatology (ERA5) ›
   45-day seasonal outlook, blended and clearly labelled by basis.
3. **Repo-as-database.** No external DB; versioned JSON + git history give reproducibility
   and a free audit trail.
4. **Quota discipline.** Only the top-N venues are priced for flights to stay within the
   SerpApi free quota.

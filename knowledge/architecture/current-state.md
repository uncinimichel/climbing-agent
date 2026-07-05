# Current State — the honest snapshot

**As of 2026-07-05.** This is the unvarnished truth about what exists and runs, versus
the four-layer vision in [`vision/mission.md`](../vision/mission.md). Update this file
whenever the reality changes — it is the antidote to aspirational docs.

## TL;DR

Today the project is a **single-trip, fully-working Phase-4 dashboard** (the "NI July
2026" trip agent) sitting on top of **partial Phase-1 ingestion** and a **simplified,
deterministic slice of Phase-2 scoring**. Phase-3 curation is *manual*, and the
Phase-1 social scrapers, Phase-2 NLP taxonomy, and Phase-4 contingency engine are **not
built yet**.

It is a real, live, useful product for one trip — and a credible foundation for the
larger engine.

## What is live and working ✅

- **Public daily dashboard** — `index.html` served on GitHub Pages:
  <https://uncinimichel.github.io/climbing-agent/>. Mobile-first, best-venue-first,
  one card per candidate venue.
- **Serverless daily rebuild** — `.github/workflows/weather.yml` runs at 06:00 UTC (plus
  on push and manual), with no laptop involved. Commits a dated history snapshot and
  redeploys Pages.
- **Weather ranking across 3 free horizons** — Open-Meteo archive (July climatology),
  forecast (16-day live), and seasonal (45-day outlook), blended 70/30 (climatology
  dominant) until the live forecast is in range (~8 July), then live supersedes.
- **Per-venue weather mini-graph** — rain bars + temperature line + wind dashed line,
  with a legend, rendered per card.
- **Tide windows for sea-cliff venues** — crag-level `tidal` flag + high/low-water times
  from the Open-Meteo marine model (decision #22).
- **Trip-independent weather/tide cache** — `fetch_env.py` fetches weather+tide once per
  venue → git-ignored `venue-env.json`, which the build consumes (decision #24).
- **Per-traveller flight pricing** — SerpApi Google Flights for Michel (from London) and
  Dan (from Belfast/Dublin), 3 best-value options each with outbound times + book links;
  top-N venues only (quota discipline).
- **Data-driven source links** — each venue links to Google Maps, multi-pitch.com climbs
  (geo-matched from its `data.json`), and its spreadsheet row.
- **History preserved** — `history/YYYY-MM-DD.md` snapshots (never overwritten) + full
  git log.

## What is partial ⚠️

- **Phase-1 ingestion** is only four structured API pulls (weather + tide, flights,
  climbs, and OSM Overpass lodging). No static guidebook crawlers, no social scrapers.
- **Phase-2 condition scoring** is a deterministic rain/precip proxy (`day_score`), *not*
  a true friction/seepage/drying model. It doesn't yet use rock type, aspect, or
  humidity physically. See [`data/condition-algorithm.md`](../data/condition-algorithm.md).
- **Phase-3 curation** exists but is **manual** — the master list is the Google
  Sheet (`climbing-trips.csv`, ~38 rows → ~42 ranked venues via `build_venues()`,
  decision #15); `venues.json` only **enriches/overrides** curated rows. Hand-maintained,
  with no automated mapping of scraped data onto a verified sector directory.

## What is not built yet ⛔ (planned)

- **Live social scrapers** (Meta / X / TikTok geotagged condition reports).
- **Static guidebook / register crawlers** at web scale.
- **NLP Taxonomy Engine** — parsing free text into the strict data dictionary
  (rock/style/protection grades). The dictionary is *specified* in
  [`data/taxonomy.md`](../data/taxonomy.md) but nothing populates it automatically.
- **The Automated Contingency Engine** — auto-computing "three dry nearby alternatives"
  on a weather alert.
- **Premium vector topos** in the dashboard (currently links out, no embedded topo).
- **Multi-trip / multi-user platform** — everything is scoped to one hard-coded trip.
- **Price-drop alerting, return-leg flight times, automated tests** — see the backlog in
  [`roadmap/roadmap.md`](../roadmap/roadmap.md). (Tides now shipped — decision #22.)

## Repo inventory (what's on disk)

| Path | Role |
|---|---|
| `index.html` | The live dashboard (generated). |
| `.github/workflows/weather.yml` | Daily serverless build + deploy. |
| `trip-ni-july-2026/scripts/fetch_env.py` | Trip-independent weather+tide → `venue-env.json` (decision #24). |
| `trip-ni-july-2026/scripts/update_report.py` | The build (~3,100 lines): consume env cache → rank → flights → HTML. |
| `trip-ni-july-2026/venues.json` | **Curated overrides/enrichment (manual):** ~13 venues + travel. Master list is the sheet. |
| `trip-ni-july-2026/flights.json` | Flight route + 3 date combos to price. |
| `trip-ni-july-2026/flights-latest.json` | Latest per-venue prices (not wiped by weather runs). |
| `trip-ni-july-2026/daily-report.md` | Markdown mirror of the dashboard (regenerated). |
| `trip-ni-july-2026/history/YYYY-MM-DD.md` | Permanent dated snapshots. |
| `trip-ni-july-2026/forecast-log.md` | Append-only running log. |
| `trip-ni-july-2026/PLAN.md` | Retrospective build + verification plan. |
| `climbing-trips.csv` | **Master venue list** (~38 rows) with per-month weather columns; refreshed from the Google Sheet each run. |
| `dolomites-trip.csv` | Scoped Dolomites routes (backup venue). |
| `prototypes/` | Design explorations (cards vs accordion). |

## Honest limitations (accepted)

- Weather basis **switches at ~8 July**: climatology-ranked before, live after.
- "Wet day" = **≥3 mm/day** from ERA5 — penalises alpine venues with brief afternoon
  convection (Dolomites, Tyrol) more than their climbable mornings deserve.
- Flights: **top-4 venues only**, one representative round-trip, **outbound times only**.
- Sub-seasonal skill is **modest at ~30 days** — the 45-day outlook is a weak signal
  (hence the 70/30 blend, labelled "experimental").
- **Coordinates** are one representative point per area, not per-crag.
- Destination logic is **advisory** — the humans decide.

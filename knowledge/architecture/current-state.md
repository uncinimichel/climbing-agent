# Current State — the honest snapshot

**As of 2026-07-02.** This is the unvarnished truth about what exists and runs, versus
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
- **Per-traveller flight pricing** — SerpApi Google Flights for Michel (from London) and
  Dan (from Belfast/Dublin), 3 best-value options each with outbound times + book links;
  top-N venues only (quota discipline).
- **Data-driven source links** — each venue links to Google Maps, multi-pitch.com climbs
  (geo-matched from its `data.json`), and its spreadsheet row.
- **History preserved** — `history/YYYY-MM-DD.md` snapshots (never overwritten) + full
  git log.

## What is partial ⚠️

- **Phase-1 ingestion** is only three structured API pulls (weather, flights, climbs).
  No static guidebook crawlers, no social scrapers.
- **Phase-2 condition scoring** is a deterministic rain/precip proxy (`day_score`), *not*
  a true friction/seepage/drying model. It doesn't yet use rock type, aspect, or
  humidity physically. See [`data/condition-algorithm.md`](../data/condition-algorithm.md).
- **Phase-3 curation** exists but is **manual** — the "master index" is
  `venues.json` (9 venues) plus `climbing-trips.csv`, hand-maintained. There's no
  automated mapping of scraped data onto a verified sector directory.

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
- **Price-drop alerting, return-leg flight times, tides, tests** — see the backlog in
  [`roadmap/roadmap.md`](../roadmap/roadmap.md).

## Repo inventory (what's on disk)

| Path | Role |
|---|---|
| `index.html` | The live dashboard (generated). |
| `.github/workflows/weather.yml` | Daily serverless build + deploy. |
| `trip-ni-july-2026/scripts/update_report.py` | The whole build (~940 lines): weather → rank → flights → HTML. |
| `trip-ni-july-2026/venues.json` | **Master index (manual):** 9 candidate venues + travel. |
| `trip-ni-july-2026/flights.json` | Flight route + 3 date combos to price. |
| `trip-ni-july-2026/flights-latest.json` | Latest per-venue prices (not wiped by weather runs). |
| `trip-ni-july-2026/daily-report.md` | Markdown mirror of the dashboard (regenerated). |
| `trip-ni-july-2026/history/YYYY-MM-DD.md` | Permanent dated snapshots. |
| `trip-ni-july-2026/forecast-log.md` | Append-only running log. |
| `trip-ni-july-2026/PLAN.md` | Retrospective build + verification plan. |
| `climbing-trips.csv` | ~40-venue shortlist with per-month weather columns. |
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

# PLAN — NI/Europe Multi-pitch Trip Agent (retrospective, for verification)

This documents what was built and **how to verify it**. Hand this to another agent
to audit the work end-to-end.

## Goal

Michel Uncini (London) + Dan Knight (Belfast) want a multi-pitch climbing trip
around **Fri 24 → Tue 28 July 2026**. The destination is **weather-dependent**:
default to Northern Ireland (Dan is local = cheap logistics); switch to a backup if
NI is wet. Need an automated, free, always-on report that (a) ranks candidate
venues by forecast and (b) tracks cheapest flights, with **history preserved**.

## What was built

- **Private→public GitHub repo** `uncinimichel/climbing-agent`.
- **Ranked HTML dashboard** `index.html` (repo root) served via **GitHub Pages**:
  https://uncinimichel.github.io/climbing-agent/ — concise, mobile, best-first.
- **Daily GitHub Action** `.github/workflows/weather.yml` (06:00 UTC + on push +
  manual) runs in the cloud (works with laptop off): fetches flights (optional),
  builds the report, commits a dated history snapshot, deploys Pages.
- **Data / config (single sources of truth):**
  - `venues.json` — 9 candidate venues + target window. Edited here → drives queries.
  - `flights.json` — route (London⇄Belfast) + the 3 date combos (Fri/Sat out,
    Mon/Tue back, **3–4 nights only**).
  - `flights-latest.json` — latest prices per combo (filled by Amadeus or on demand).
- **Scripts:**
  - `scripts/update_report.py` — Open-Meteo weather → score+rank → writes
    `index.html`, `daily-report.md`, `history/<date>.md`.
  - `scripts/fetch_flights.py` — optional Amadeus self-service price fetch;
    self-skips with no API key.
- **History:** `history/YYYY-MM-DD.md` (never overwritten) + full git history.
- **Source CSVs:** `climbing-trips.csv` (40-venue shortlist), `dolomites-trip.csv`.

## Key design decisions

1. **Weather scoring.** `day_score()` = 100 − 0.8·rain% − 6·precip_mm, capped at
   25 if rain code ≥61, 15 for thunderstorms. Venue score = mean over used days.
   Rank by score desc, tie-break by venue priority (NI preferred when tied).
2. **Forecast horizon.** Open-Meteo gives 16 days. The trip is further out until
   ~8 July, so the report **falls back to the nearest queryable day** as a proxy
   and **says so explicitly** in a banner (date + days-before-trip + "indicative").
   From ~8 July it ranks on the real target window automatically.
3. **Flights are decoupled** from weather: prices live in `flights-latest.json` so
   automated weather runs never wipe them. No reliable *free* flight API → Amadeus
   self-service (free tier) is the chosen automation; without a key it's on-demand.
4. **Hosting.** Free rendered HTML requires GitHub Pages → repo made **public**
   (no personal data in repo; home address is only in Claude's local memory).

## How to verify (checklist for the auditing agent)

- [ ] `python3 trip-ni-july-2026/scripts/update_report.py` runs clean and prints a
      ranking; `index.html` parses as valid HTML.
- [ ] `index.html` title states what it is and shows the target dates; the proxy
      banner is present and honest about the forecast horizon.
- [ ] Ranking order matches scores in the table; NI tie-break behaves.
- [ ] `flights.json` contains exactly 3 combos, all 3–4 nights (no 2-night option).
- [ ] `fetch_flights.py` exits 0 and changes nothing when AMADEUS_* env unset.
- [ ] Action `weather.yml`: has `pages: write`/`id-token: write`, a build job that
      commits + uploads artifact, and a deploy job using `deploy-pages`.
- [ ] GitHub Pages is enabled (build_type = workflow) and the URL renders.
- [ ] A `history/<date>.md` snapshot exists and is not overwritten across days.
- [ ] Repo visibility is public; Pages URL loads on mobile.

## Known limitations / TODO

- Weather is a proxy until ~8 July (stated in-report). Re-check ranking then.
- Flight prices are indicative until an Amadeus key is added as repo secrets
  (`AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET`); Amadeus *test* env data is limited.
- Destination logic is advisory (NI-preferred); the human makes the final call.
- Coordinates are one representative point per area, not per-crag.

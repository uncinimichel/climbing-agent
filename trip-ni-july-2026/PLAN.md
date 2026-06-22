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
  - `venues.json` — 9 candidate venues + target window + per-traveller `travel`
    (mode fly|local|drive and destination airport for Michel/London & Dan/Belfast).
  - `flights.json` — origin airports + the 3 date combos (Fri/Sat out, Mon/Tue back,
    **3–4 nights only**); the max-nights combo is the representative round-trip priced.
  - `flights-latest.json` — per-venue cached prices for both travellers (written by
    update_report; never contains the API key).
- **Scripts:**
  - `scripts/update_report.py` — weather rank → prices flights for the top-N venues
    (Michel + Dan, Google Flights via SerpApi) → writes `index.html`,
    `daily-report.md`, `history/<date>.md`. Flights fold into the ranking table.
- **History:** `history/YYYY-MM-DD.md` (never overwritten) + full git history.
- **Source CSVs:** `climbing-trips.csv` (40-venue shortlist), `dolomites-trip.csv`.

## Key design decisions

1. **Weather scoring.** `day_score()` = 100 − 0.8·rain% − 6·precip_mm, capped at
   25 if rain code ≥61, 15 for thunderstorms. Venue score = mean over used days.
   Rank by score desc, tie-break by venue priority (NI preferred when tied).
2. **Forecast horizon + climatology.** Open-Meteo forecast is 16 days. Until the
   trip enters range (~8 July) venues are ranked on **July climatology** (ERA5
   historical, free) via ONE ranged request/venue (deterministic — not per-year
   bursts, which silently dropped samples and made ranking non-reproducible).
   Banner states which basis is used; live forecast takes over automatically.
3. **Flights via Google Flights (SerpApi).** Per venue, a representative round-trip
   is priced for Michel (from London) and Dan (from Belfast) into the venue airport;
   NI = Dan local, UK-mainland = Michel drives. To stay within the SerpApi quota
   only the **top-N (=4)** venues are priced, one combo each (book links adjust dates).
   Key is `SERPAPI_KEY` (GitHub secret + gitignored `.env`), never committed.
4. **Hosting.** Free rendered HTML requires GitHub Pages → repo made **public**
   (no personal data in repo; home address is only in Claude's local memory).

## How to verify (checklist for the auditing agent)

- [ ] `python3 trip-ni-july-2026/scripts/update_report.py` runs clean and prints a
      ranking; `index.html` parses as valid HTML.
- [ ] `index.html` title states what it is and shows the target dates; the banner is
      present and honest about the forecast horizon / climatology basis.
- [ ] Climatology is reproducible: run update_report twice → identical rain% and order.
- [ ] Ranking order matches scores in the table; NI tie-break behaves.
- [ ] Ranking table has ✈️ Michel (London) and ✈️ Dan (Belfast) columns for the top 4,
      with price + airport + book link; NI shows Dan local; venue names link to Maps.
- [ ] `flights.json` contains exactly 3 combos, all 3–4 nights (no 2-night option).
- [ ] `update_report.py` runs without SERPAPI_KEY (flights show search links, no crash).
- [ ] No secret in any committed file; `.env` is gitignored.
- [ ] Action `weather.yml`: has `pages: write`/`id-token: write`, passes SERPAPI_KEY
      secret, a build job that commits + uploads artifact, and a deploy job.
- [ ] GitHub Pages is enabled (build_type = workflow) and the URL renders.
- [ ] A `history/<date>.md` snapshot exists and is not overwritten across days.
- [ ] Repo visibility is public; Pages URL loads on mobile.

## Known limitations / TODO

- Weather ranking uses climatology until ~8 July, then live forecast (stated in-report).
- SerpApi quota: top-4 × 2 travellers ≈ up to 8 searches/day. Balance is finite — may
  need topping up near the trip, or reduce `TOP_N_FLIGHTS` / run less often to throttle.
- Destination logic is advisory (NI-preferred); the human makes the final call.
- Coordinates are one representative point per area, not per-crag.

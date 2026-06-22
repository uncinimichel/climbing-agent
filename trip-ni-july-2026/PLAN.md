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

## Architecture overview

Fully serverless and free — no laptop, no Claude in the daily loop. Everything
runs inside GitHub Actions on a schedule.

```
                  ┌─────────────────────────── GitHub Actions (cloud) ───────────────────────────┐
  cron 06:00 UTC  │                                                                               │
  (or push, or ── │ build job:                                                                    │
   manual run)    │   1. checkout repo                                                            │
                  │   2. python update_report.py                                                  │
                  │        ├─ Open-Meteo  archive  → July climatology per venue (free, no key)    │
                  │        ├─ Open-Meteo  forecast → 16-day forecast per venue (free, no key)     │
                  │        ├─ rank venues by weather score                                        │
                  │        └─ SerpApi (Google Flights) → top-4 venues × {Michel, Dan}             │
                  │              using secret SERPAPI_KEY (never in code)                          │
                  │   3. writes index.html + daily-report.md + history/<date>.md                  │
                  │   4. git commit + push (the commit IS the history)                            │
                  │   5. upload-pages-artifact                                                    │
                  │ deploy job:                                                                   │
                  │   6. deploy-pages  ───────────────────────────────────────────┐              │
                  └────────────────────────────────────────────────────────────── │ ─────────────┘
                                                                                   ▼
                                            https://uncinimichel.github.io/climbing-agent/  (public)
```

- **Triggers:** `schedule` (daily 06:00 UTC), `push` to main, and `workflow_dispatch`
  (manual "Run workflow" button). All three run the same job.
- **Secrets:** only `SERPAPI_KEY`, stored as a GitHub Actions secret and masked in
  logs. `.env` (local mirror) is gitignored. Weather APIs need no key.
- **State:** the repo itself is the database — `flights-latest.json` is the latest
  snapshot; `history/` + git log are the permanent archive.
- **Failure modes:** weather APIs retry (4×); if SerpApi/key is unavailable the build
  still succeeds and flight cells fall back to "search ↗" links; a no-change run
  commits nothing and just redeploys.

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

## Limitations (known, accepted)

- **Weather basis switches at ~8 July**: climatology-ranked before, live-forecast after.
  Climatology is a typical-year average, not a prediction for this specific July.
- **"Wet day" = ≥3 mm/day** from ERA5; alpine venues with daily afternoon convection
  (Dolomites, Tyrol) score worse than their real climbable-mornings would suggest.
- **Flights:** only the **top-4** venues are priced, **one representative round-trip**
  (Fri 24→Tue 28), **outbound-leg times only** (return times need a 2nd SerpApi call).
  Prices are point-in-time, not continuously tracked.
- **SerpApi quota**: top-4 × 2 travellers ≈ up to 8 searches/day. Balance is finite —
  top up near the trip, or lower `TOP_N_FLIGHTS` / run less often to throttle.
- **Coordinates** are one representative point per area, not per-crag.
- **GitHub scheduled jobs** can lag a few minutes and are paused after ~60 days of repo
  inactivity (not a risk here — it commits daily). Node20→24 deprecation is a warning only.
- **Destination logic is advisory** (NI-preferred, weather-ranked); the humans decide.

## Next tasks / backlog

Priority order — pick up here. None are required for daily running; all are enhancements.

1. **Return-leg flight times** — second SerpApi call per option (≈2× searches) to show
   inbound dep→arr, not just outbound.
2. **Price-drop alerting** — compare today's `flights-latest.json` to yesterday's history;
   if a fare drops below a threshold, open a GitHub issue / email / push notification.
3. **Lock the date once chosen** — when Michel & Dan pick a date, pin it in `flights.json`
   and track that single combo's price trend over time (chart from history).
4. **Tides for sea-cliff venues** (Fair Head, Gower, Cornwall) — add a free/low-cost tide
   source so non-tidal climbing windows are flagged. (Old multi-pitch project had tides.)
5. **Per-crag detail** — link each venue to its UKC/theCrag/Mountain-Project page and add
   a guidebook/approach note (data partly in `climbing-trips.csv`).
6. **Wind & sunrise/sunset** in the forecast cell (already fetched by the API) — useful for
   alpine starts and exposed crags.
7. **"Confidence" on climatology** — show spread/variance across years, not just the mean.
8. **Email/Slack digest** — post the daily top pick + cheapest fares to a channel.
9. **Pin the GitHub Action versions** / bump to Node24-based actions to clear the warning.
10. **Tests** — a tiny pytest for `day_score`, `climo_score`, flight ranking, and the
    out-of-window banner logic, run in CI before deploy.

## Maintenance notes

- Add/remove venues or change dates: edit `venues.json` (+ `travel` airports) and
  `flights.json`; everything else flows from there.
- Rotate the SerpApi key: `gh secret set SERPAPI_KEY --repo uncinimichel/climbing-agent`
  and update local `.env`. The key was once pasted in chat → rotating is advisable.
- Manual run: Actions tab → "Run workflow", or `gh workflow run weather.yml`.

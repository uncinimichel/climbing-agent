# Runbook

Day-to-day operations: run it, verify it, maintain it. For the deploy pipeline see
[`deployment.md`](deployment.md); for APIs see [`external-apis.md`](external-apis.md).

## Run locally

```bash
# Optional: refresh the trip-independent weather/tide cache first (once per venue →
# git-ignored venue-env.json). update_report.py consumes it; skip it and update_report
# just fetches live per venue instead (slower, same result).
python3 trip-ni-july-2026/scripts/fetch_env.py

# Full build (weather → rank → flights → HTML). Works without a key (flights degrade).
python3 trip-ni-july-2026/scripts/update_report.py

# With flights:
SERPAPI_KEY=... python3 trip-ni-july-2026/scripts/update_report.py
```

Outputs written: `index.html`, `venues/<slug>.html`, `sitemap.xml`,
`trip-ni-july-2026/daily-report.md`, `trip-ni-july-2026/history/<date>.md`,
`trip-ni-july-2026/flights-latest.json`.

## Run in the cloud

- **Manual:** Actions tab → "Run workflow", or `gh workflow run weather.yml`.
- **Automatic:** daily 06:00 UTC, and on any non-docs push to `main`.

## Verification checklist

Run after any change to the generator, config, or scoring:

- [ ] `update_report.py` runs clean and prints a ranking; `index.html` parses as valid HTML.
- [ ] Title states what it is + the target dates; the banner is present and **honest about
      the forecast horizon / climatology basis**.
- [ ] **Climatology is reproducible** — run twice → identical rain% and order.
- [ ] Each venue is a card with a weather mini-graph (rain bars + temp + wind line) and a
      legend; #1 highlighted; **no horizontal scroll at 390 px**.
- [ ] Out of live-forecast range: each card shows a "🔭 45-day outlook" and the basis reads
      "typical July + 45-day outlook"; seasonal-API failure degrades to climatology only.
- [ ] Flights per card: ✈️ Michel (London) + ✈️ Dan (Belfast/Dublin), 3 options with
      outbound times + book link; NI shows Dan local; venue names link to Maps.
- [ ] `flights.json` has exactly 3 combos, all 3–4 nights (no 2-night option).
- [ ] Runs **without** `SERPAPI_KEY` (flights show search links, no crash).
- [ ] **No secret** in any committed file; `.env` is gitignored.
- [ ] `weather.yml` has `pages: write` / `id-token: write`, passes the `SERPAPI_KEY`
      secret, builds + commits + uploads artifact, and has a deploy job.
- [ ] GitHub Pages enabled (`build_type = workflow`) and the URL renders on mobile.
- [ ] A `history/<date>.md` snapshot exists and is **not overwritten** across days.

(This mirrors the audit checklist in `trip-ni-july-2026/PLAN.md` — keep them in step.)

## Common maintenance tasks

| Task | How |
|---|---|
| **Add / remove a venue** | Edit `venues.json` (+ its `travel` airports). Everything flows from there. |
| **Change trip dates** | Edit `venues.json` `target_window` **and** `flights.json` `combos`. |
| **Change flight routes** | Edit `flights.json` `traveller_origins` / `combos`. |
| **Throttle SerpApi usage** | Lower `TOP_N_FLIGHTS` in `update_report.py`, or run less often. |
| **Rotate the API key** | `gh secret set SERPAPI_KEY --repo uncinimichel/climbing-agent` + update `.env`. |
| **Change the weather formula** | Edit `update_report.py` + `data/condition-algorithm.md`; log in `roadmap/decisions.md`. |
| **Force a rebuild** | `gh workflow run weather.yml` (or push a non-docs change). |

## Trip-lifecycle cadence (from `PLAN.md` / trip README)

- **~10 days out (~14 July):** start reading the daily forecast log closely.
- **~8 July:** live forecast enters range → ranking basis switches from climatology to live.
- **~3–4 days before:** make the go / no-go destination call.
- **Once destination likely:** check flights (London ⇄ Belfast for Michel), several times
  near booking; then **book**.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Flight cells show "search ↗" only | `SERPAPI_KEY` missing/exhausted — expected degradation. Check quota. |
| Ranking didn't change day-to-day | Climatology is deterministic until ~8 July — this is correct. |
| Seasonal outlook absent | Seasonal API failed → degraded to climatology. Non-fatal. |
| Action didn't run on schedule | GitHub cron can lag a few min; jobs pause after ~60 d inactivity (not a risk — daily commits). |
| Page didn't update | Check the deploy job. Deploys are **serialized** (`cancel-in-progress: false`) so they queue, never cancel; a `deploy-pages` "Deployment failed, try again later" is a transient GitHub Pages error (common when pushes land close together) — re-run the failed job. |

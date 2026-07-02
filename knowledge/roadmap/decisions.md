# Decision Log (ADR-lite)

Lightweight record of non-obvious decisions and *why* — so future work (human or agent)
doesn't re-litigate settled calls or silently reverse them. Add an entry when you make a
choice that wasn't forced. Newest at the bottom.

Format: `#N — Title (date) · Decision · Why · Status`.

---

### #1 — Fully serverless on GitHub Actions + Pages (2026-06)
**Decision:** run the daily build in GitHub Actions and serve the dashboard from GitHub
Pages; no laptop, no paid server.
**Why:** free, always-on, zero-maintenance; the trip must update daily regardless of
whether Michel's Mac is on.
**Status:** ✅ Live.

### #2 — The repo is the database (2026-06)
**Decision:** persist all state as versioned JSON + git history; no external DB.
`flights-latest.json` = latest snapshot, `history/` + git log = permanent archive.
**Why:** free, reproducible, auditable; no hidden server state; every run is a diff.
**Status:** ✅ Live.

### #3 — Config as single source of truth (2026-06)
**Decision:** `venues.json` and `flights.json` drive what gets queried/priced; the script
reads them rather than hard-coding venues.
**Why:** change behaviour by editing data, not code; safer, clearer, agent-friendly.
**Status:** ✅ Live.

### #4 — Three free weather horizons, honest basis (2026-06)
**Decision:** rank on live 16-day forecast › climatology (ERA5) › 45-day seasonal, blended
**70/30** (climatology dominant) beyond live range; always state the active basis in the UI.
**Why:** free and keyless (Open-Meteo); sub-seasonal skill is weak so it can't be trusted
alone; users must know how much to trust a ranking.
**Status:** ✅ Live.

### #5 — Deterministic rain-proxy scoring, for now (2026-06)
**Decision:** `day_score = 100 − 0.8·rain% − 6·precip_mm` (capped for rain/thunder), mean
over trip days; keep it deterministic.
**Why:** simple, reproducible (two runs → identical order = a verification checkpoint),
good enough to rank. A true friction/seepage model is deferred to Stage 1.
**Trade-off:** ignores rock/aspect/humidity → penalises alpine afternoon-convection venues.
**Status:** ✅ Live; superseding model planned (see `data/condition-algorithm.md`).

### #6 — Flights: top-N venues only, outbound times only (2026-06)
**Decision:** price only the **top-4** ranked venues, one representative round-trip each,
outbound leg times only.
**Why:** SerpApi free quota (~8 searches/day). Return-leg times need a 2nd call/option.
**Status:** ✅ Live; return-leg times are Stage-0 backlog item #1.

### #7 — Public repo for free Pages (2026-06)
**Decision:** make the repo public to get free rendered GitHub Pages.
**Why:** free hosting requires it. Mitigation: **no personal data in the repo** — the home
address lives only in Claude's local memory, never committed.
**Status:** ✅ Live.

### #8 — Single secret, gitignored `.env` (2026-06)
**Decision:** only `SERPAPI_KEY` as a secret; store in GitHub Actions secret + gitignored
`.env`; weather APIs need no key.
**Why:** minimise secret surface; keep the build runnable without a key (flights degrade).
**Note:** key was once pasted in chat → rotation advisable.
**Status:** ✅ Live.

### #9 — Chose Open-Meteo Seasonal for sub-seasonal (2026-06)
**Decision:** use Open-Meteo Seasonal API for the 45-day outlook.
**Why:** free, no key, CFS ensemble, same provider/format as the rest. Alternatives
(Visual Crossing, OpenWeather day_summary, Meteomatics/AccuWeather) are keyed/paid.
**Status:** ✅ Live.

### #10 — Card-per-venue UI over a table (2026-06)
**Decision:** dashboard is one card per venue (big mini-graph + flights), not a table.
**Why:** mobile-first readability, best-first scanning, room for the weather graph; no
horizontal scroll at 390 px. (Chose design A over the accordion prototype.)
**Status:** ✅ Live.

### #11 — Adopt the multi-pitch.com route data model as the tagging target (2026-07-02)
**Decision:** base the climbing taxonomy on the mature **multi-pitch.com** dataset
(`/dev/multi-pitch`, ~40 fully-tagged routes) — its route schema
([`data/route-schema.md`](../data/route-schema.md)), controlled vocabularies
([`data/taxonomy.md`](../data/taxonomy.md)), and normalized `dataGrade` 1–7 ladder
([`data/grade-conversion.md`](../data/grade-conversion.md)).
**Why:** it's a real, battle-tested model behind guidebook-quality descriptions — no need
to invent one. It gives the Phase-2 Taxonomy Engine a concrete output contract for tagging
a found climb, a cross-system grade normalization for ranking, and a proven description
style guide ("the climber", qualify jargon, prefixed reference links).
**Note:** the grade ladder is calibrated to the Diff→E1 band in that dataset; extend at the
extremes deliberately.
**Status:** ✅ Documented; automated population (parsing) is planned (roadmap Stage 4).

---

*Template for new entries:*
```
### #N — Title (date)
**Decision:** …
**Why:** …
**Status:** ✅ Live | ⚠️ Partial | 🔜 Planned | ❌ Reversed (see #M)
```

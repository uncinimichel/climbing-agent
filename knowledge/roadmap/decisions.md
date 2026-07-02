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

### #12 — Ground the taxonomy in cited authorities (2026-07-02)
**Decision:** back the Data & Taxonomy docs with recognised sources — UIAA, BMC,
*Freedom of the Hills*, Samet's *Climbing Dictionary*, and the grade-system originators
(Welzenbach, O.G. Jones, Robbins/Wilson/Wilts, Ewbank, Devies, Erickson). Captured in
[`data/references.md`](../data/references.md).
**Why:** the Taxonomy Engine must map onto a *defensible* standard, not an invented one; and
two useful, free inference signals fell out of the research — (a) UK trad's adjectival↔
technical gap seeds the `protection` field, and (b) rock-friction/wet-sandstone science
grounds the condition model.
**Status:** ✅ Documented; cross-linked from taxonomy / grade-conversion / condition-algorithm.

### #13 — Learn from the world's climbing databases; target OpenBeta for interop (2026-07-02)
**Decision:** benchmark our taxonomy against UKClimbing, theCrag, Mountain Project, and
**OpenBeta**, and adopt their proven ideas — hierarchical areas with inheritance, a
cascading `gradeContext`, an all-systems `grades{}` object, composable disciplines,
structured `pitches[]`, richer safety (`runout`/`terrain`), editorial stars, structured
first-ascent, and an access/stewardship layer. Captured in
[`../data/external-models.md`](../data/external-models.md).
**Why:** these are battle-tested at 150k–1M-route scale. Crucially, **OpenBeta is open,
CC-licensed data with a GraphQL API** — a license-clean ingestion source (safer than
scraping ToS-restricted UGC sites) and a schema worth aligning to for loss-less interop.
**Scope:** structural changes (hierarchy, gradeContext, multi-system grades) are **Stage-5
schema-v2 work**, not yet applied to the live single-trip model; enum extensions (disciplines,
safety) are documented now in [`../data/taxonomy.md`](../data/taxonomy.md).
**Status:** ⚠️ Documented + enums extended; structural adoption planned.

### #14 — Ingestion plan: free, staged, four named sources + a two-tier store (2026-07-02)
**Decision:** build Phase 1→3 as a **free-tier, staged vertical** starting from a short named
source list — **OpenBeta** (clean CC/GraphQL, first), then **theCrag / UKClimbing / Mountain
Project** (grey-area public scraping), plus **social as aggregated signal**. Scope is
**multi-pitch worldwide**; storage stays **repo-as-database** via a **two-tier store** (durable
tagged corpus in git/SQLite; raw + social firehose in an ephemeral, gitignored cache — only
*aggregated, non-personal* summaries are committed). Full plan:
[`ingestion-plan.md`](ingestion-plan.md).
**Why:** the bounded scope (multi-pitch ≈ 30–150k routes, not millions) plus the two-tier
store is what lets *aggressive + social + repo-as-DB + free* coexist without a paid database.
OpenBeta first because it's the only ToS-clean route DB. Social does three jobs — discovery,
enrichment of existing routes, and a low-confidence *"what people are saying"* planner card —
always aggregated, no PII in the public repo (GDPR).
**Scope:** the first slice is one region end-to-end (OpenBeta → SQLite → LLM-tag → map onto the
master index); grey-area + social tracks follow. Semantic search, managed DB, and paid scraping
APIs are deferred until budget opens.
**Status:** 🔜 Planned — nothing built yet; this is the blueprint the first slice implements.

---

*Template for new entries:*
```
### #N — Title (date)
**Decision:** …
**Why:** …
**Status:** ✅ Live | ⚠️ Partial | 🔜 Planned | ❌ Reversed (see #M)
```

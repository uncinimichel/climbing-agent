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

### #15 — The Google Sheet is the venue master list; ranking is a composite (2026-07-03)
**Decision:** every row of the venue spreadsheet becomes a ranked venue (CI refreshes the
CSV each run; `GAZETTEER`/geocoder supply coords+airports for rows without a curated
`venues.json` entry). The score is now **0.55·weather + 0.25·travel + 0.20·venue fit**,
where travel uses real flight prices when priced (top-N) plus the sheet's travel-time
band, and venue fit uses the sheet's volume/difficulty/min-trip judgment columns. Shown
as an interactive donut in the venue header.
**Why:** Michel curates in the sheet, not in JSON — the ranking should follow his data
with zero config. Weather alone also ignored real decision factors he tracks (cost,
volume, trip length).
**Status:** ✅ Live — 42 areas ranked from 38 sheet rows + curated extras.

### #17 — Aspect × sun: score the felt temperature on the rock (2026-07-03)
**Decision:** adjust `tmax` by crag aspect (N −4°C … S +4°C, unknown +1) weighted by
sunniness (live sunshine fraction, else dryness as proxy) before the heat penalty, in
both climatology and live-forecast scoring. Aspect is a venue field; ranking labels
("typical late July") are derived from the trip dates, never hardcoded.
**Why:** sun on a wall feels far hotter than air temp; shaded north faces climb cooler
(Michel's Anica Kuk shade strategy, now scored: Paklenica +4 pts back). Cloud cover is
implicit in the sunniness weight. Taxonomy's "Aspect / face" field goes from planned to
scored.
**Status:** ✅ Live.

### #16 — Climbing heat curve: penalise heat from 20°C, hard from 30°C (2026-07-03)
**Decision:** `heat_penalty(tmax) = 1.2·(t−20)⁺ + 3·(t−25)⁺ + 5·(t−30)⁺` applied in both
`climo_score` and `day_score`; cold penalty below 8°C. Replaces the old lenient knee at
27°C/33°C.
**Why:** dry-but-hot venues (Costa Blanca, Wadi Rum, Anti Atlas) topped the July ranking
on 0% rain. Friction research (climbing.com *Science of Friction*, UKC conditions
threads) puts ideal sending temps at ~7–18°C, and multi-pitch means hours exposed on the
wall. After the change the top of the table is high/cool venues (Gredos, Teide 2,200 m,
Écrins, Aladağlar) and deserts sit last — matching climber intuition.
**Status:** ✅ Live.

### #18 — Postgres (Docker) is the corpus database; supersedes the committed-SQLite plan (2026-07-04)
**Decision:** store the climbing taxonomy + route corpus in **Postgres with PostGIS**, run
locally via Docker (`db/docker-compose.yml`, `postgis/postgis:16-3.4`). The closed enums
from [`data/taxonomy.md`](../data/taxonomy.md) become **lookup tables** (FK violations
enforce "repair or reject, never surface"); safety-critical hazard flags require an
evidence span (trigger); areas are a hierarchical tree with inherited `gradeContext`;
grades stay system-scoped with the `dataGrade` ladder seeded from
[`data/grade-conversion.md`](../data/grade-conversion.md). Full design:
[`data/database.md`](../data/database.md). **Eventually the DB is the only source of
truth** for venue/route knowledge — `venues.json` and `extra-climbing.json` (→
`area_reference`) migrate in and become exports.
**Why:** the taxonomy is a faceted classification with closed enums, not an ontology —
plain SQL fits (no open-world inference; flat facets; hard queries are geo + filter).
Postgres over the previously planned committed-SQLite: richer constraints, PostGIS geo,
no ceiling at ingestion scale; Docker keeps it free and local (no managed DB yet).
**Supersedes:** the SQLite recommendation inside #14's two-tier store — the *two tiers
themselves stand* (durable vs ephemeral; no PII committed); only the durable tier's
engine changes. Decision #2 (repo-as-DB) still governs the live trip dashboard.
**Status:** ✅ DDL + seeds + smoke test in `db/`; ingestion into it is Stage-5/M2 work.

### #19 — Natural-language retrieval: SQL-first tool-use agent; pgvector in Postgres, no separate vector DB (2026-07-04)
**Decision:** the admin chat agent (roadmap Stage 5½) retrieves climbs via a **Claude
tool-use loop calling a strict, enum-validated `search_climbs` tool** that builds
parameterized SQL against the `db/` corpus — the model never writes raw SQL. Semantic
search over prose/buzz, when it comes, is **pgvector inside the same Postgres**, not a
separate vector database. Design: [`../architecture/retrieval-agent.md`](../architecture/retrieval-agent.md).
**Why:** the target queries ("sandstone near me in August") decompose entirely into
closed-enum + PostGIS + climatology filters — deterministic SQL answers them exactly,
where embedding similarity only approximates. Vectors earn their place on prose and
vague-qualitative asks; keeping them in Postgres lets one query filter by enum/geo *and*
rank by similarity, and avoids operating a second store. Anthropic ships no embedding
API (external provider needed, e.g. Voyage) — one more reason the vector tier stays
budget-gated. Strict tool schemas generated from the DB lookup tables keep agent and
taxonomy in lockstep, with no injection surface.
**Status:** 🔜 Planned — blocked on the corpus having routes (ingestion M2+).

### #20 — Taxonomy v1.1: character facet, richer rock/feature/grade vocabularies, protection style (2026-07-04)
**Decision:** extend the strict data dictionary after an audit against real-world
vocabularies: **+7 rock types** (gritstone, slate, gneiss, schist, basalt, conglomerate,
andesite — the UKC crag-search rocktypes we lacked), **+8 features** (corner, groove,
roof, offwidth, flake, tufa, pockets, pillar), a **new set-valued `character` facet**
(sustained/pumpy/powerful/technical/fingery/crimpy/reachy/delicate/exposed/fluttery —
the Rockfax database-symbol + theCrag route-tag vocabulary for *how a route climbs*),
**+7 grade systems** (Ewbank, Saxon, Brazilian, Drytooling D, Scottish Winter, Via
Ferrata, DWS S0–S3 — via-ferrata and DWS disciplines previously had no grade system at
all), and **`protectionStyle` + `belays` fields** (gear/bolted/mixed — bolted-belay trad
is a first-order multi-pitch planning fact). Applied in lockstep: taxonomy.md → DB
schema/seeds (`character` table + junction, route columns) → retrieval agent (new
`features`/`character` tool filters, enums auto-loaded).
**Why:** Michel's review call — the v1 taxonomy under-described *how routes climb* and
missed vocabularies our own venue list needs (UK grit/slate; Montserrat conglomerate;
alpine gneiss). Sources: Rockfax database symbols (sustained "s"/fingery "f"/fluttery
"h"), theCrag's Rockfax-style tag set (crimpy/pumpy/powerful/technical/reachy), the
full grade-system landscape (Wikipedia "Grade (climbing)"), UKC rocktype facets.
**Deliberately not adopted:** Polish Kurtyka, Russian/Alaskan alpine, Canadian ice,
Japanese Dankyū grades — no venue on our lists needs them; add on first contact. The
`dataGrade` ladder does not yet map the new systems (extend on first ingestion).
**Status:** ✅ Docs + DB + agent updated; smoke test and agent test pass green.

---

*Template for new entries:*
```
### #N — Title (date)
**Decision:** …
**Why:** …
**Status:** ✅ Live | ⚠️ Partial | 🔜 Planned | ❌ Reversed (see #M)
```

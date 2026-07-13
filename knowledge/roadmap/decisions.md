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
**Status:** ⚠️ Superseded by #26 (curve tightened — the knees at 20/25/30°C were still too
lenient; dry-but-warm venues like Gredos out-ranked cooler ones).

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

### #21 — climbing-agent is the engine; multi-pitch.com is the product surface (2026-07-05)
**Decision:** merge in the multi-pitch.com product/content plan (feature brainstorm +
competitor research across Surfline, Magicseaweed, Windguru, OpenSnow, FATMAP, OpenBeta,
etc.) as [`multi-pitch-site-plan.md`](multi-pitch-site-plan.md), cross-linked from
`vision/mission.md` and `roadmap.md` rather than copied wholesale or deep-merged into the
existing phase docs. Framing: **climbing-agent is the engine** (taxonomy, condition
scoring, Postgres corpus, retrieval agent) and **multi-pitch.com is the product surface**
that engine is meant to power — the two stay separate repos/codebases
(`~/dev/multi-pitch`, Node/Lambda, vs. this repo's Python/Postgres stack).
**Why:** the two plans converge almost exactly — mission.md's north star already *is*
"turn multi-pitch.com into a predictive engine" (decision #11 already adopted its data
model as the taxonomy target), and the new plan's Tier 1 conditions engine is a
site-facing version of the condition-algorithm work already live for the NI trip
(`day_score`/`climo_score`, decisions #16/#17). A light cross-linked doc captures the
overlap without risking either doc's existing structure or losing nuance in a rewrite.
**Open question:** where the conditions-engine code should actually run — inside
multi-pitch.com's own lambdas, or exposed as a service climbing-agent's Postgres/agent
stack serves and multi-pitch.com calls. Not decided; revisit once Stage 1 (real condition
intelligence) or the site's Tier 1.1 gets built.
**Status:** ✅ Docs merged/cross-linked; code-location question 🔜 open.

### #22 — Tides from Open-Meteo Marine, not the shared RapidAPI key (2026-07-05)
**Decision:** the planner's tide times (roadmap Stage 0 #5) come from the **Open-Meteo
Marine API** (`sea_level_height_msl`, hourly, free, keyless), with high/low-water times
computed in `update_report.py` by a parabola fit through each turning point of the hourly
curve. We do **not** reuse the RapidAPI "Tides" endpoint that multi-pitch.com's
`lambdaGetTides` uses, even though the `TIDES_HOOD_KEY` is available from the Lambda's
env config.
**Why:** (a) that key is shared with the live multi-pitch.com daily Lambda — burning its
unknown RapidAPI quota from a second daily CI job risks breaking the site's own tide
pages; (b) the RapidAPI call returns 24 h per request, so covering the trip window would
take ~6 requests × venue × day vs. one keyless request; (c) no secret to manage in GitHub
Actions; (d) it matches the stack — every other weather signal here is already Open-Meteo.
Trade-off accepted: the marine model is a tide *model* (~10-day horizon, heights vs. mean
sea level, no station datum), fine for a "which half of the day" access call, not for
navigation. Venue selection is the crag-level `tidal` flag (see #21's taxonomy and
`knowledge/data/taxonomy.md`): explicit in `venues.json`/`GAZETTEER`, or derived from
multi-pitch.com routes flagged `tidal` within 10 km.
**Status:** ✅ Live — tiles/tags/static pages; times reach the trip window ~10 Jul.

### #23 — Chat mode runs on the Claude Code CLI, not the raw Anthropic API (2026-07-05)
**Decision:** the retrieval agent's chat mode (decision #19) drives `claude -p`
(Claude Code CLI, `agent/cli_agent.py`) instead of `client.messages.create()`
directly (`agent/core.py`). The model gets one instructed capability — run
`search_cli.py '<json>'` via its own Bash tool — and `cli_agent.py` parses
`claude`'s `--output-format stream-json` into the same event shape (`text`/`tool`/
`rows`/`refusal`/`done`) `core.py` produces, so both UIs (console, admin web page)
render identically regardless of backend.
**Why:** confirmed live that authenticating via `ant auth login` (OAuth) does
**not** draw on a Claude Pro/Max subscription — any code calling the Messages API
directly still bills against the account's separate, pay-as-you-go API credit
balance, and returned `"Your credit balance is too low"` even after successful
OAuth login. Shelling out to the actual `claude` binary instead uses Claude Code's
own subscription-billed usage path — verified working in the exact scenario that
blocked the raw-API route. `core.py` stays in the repo as an alternative backend
for a future server deployment with funded API credits, where shelling out to a
local `claude` binary isn't an option.
**Trade-off:** the tool restriction (`--allowedTools Bash` / `--disallowedTools
Edit Write NotebookEdit`) is prompt-guided scoping, not a hard sandbox boundary —
fine for a local single-admin dev tool, not for anything exposed further. Console
model defaults to `sonnet` (cheap, capable) rather than `opus-4-8`.
**Status:** ✅ Live — both UIs verified end-to-end (search → tool call → grounded
answer, including honest empty-result retry with a relaxed filter).

### #24 — Split trip-independent environment data into a per-venue cache (2026-07-05)
**Decision:** extract weather/wind/tide out of the monolithic daily build into a standalone
`fetch_env.py` that writes a per-venue `venue-env.json` cache, keyed `(venue, date)`,
**latest-only** (overwritten each run). Flights/stays become a separate `fetch_trip.py` that
reads the env cache; `build_report.py` renders from both. Full design:
[`../architecture/venue-env-cache.md`](../architecture/venue-env-cache.md).
**Why:** weather/tide are a pure function of `(lat/lon, date)` — independent of trip, origin
or user — so computing them once per venue and reusing them keeps the environment layer at
**O(venues)** across every trip and user, and serves the website's "browse a venue before
committing to a trip" path with no trip in existence. Primary driver is **structural
clarity** (one 3086-line script doing three jobs → three single-purpose files), reuse second;
it is *not* a cost play — Open-Meteo is free and the scarce quota lives in the booking layer.
Latest-only (no `issued_at` history) because both use cases only want the current best
forecast for a date; forecast-skill tracking is deferred and recoverable by adding a key
column later. JSON shaped 1:1 with a future `venue_env` Postgres table (decision #18) to
avoid a second migration.
**Trade-off:** splitting the processes splits their failure modes — the renderer must read
`fetched_at`, badge stale weather, and degrade to last-good/`climo` rather than render
silently-stale numbers as fresh.
**Status:** ⚠️ Partial (2026-07-05) — **`fetch_env.py` is live**: it fetches weather+tide
once per venue → git-ignored `venue-env.json`, and `update_report.py` consumes it
(`_env_raw`/`_seasonal_raw`/`tide_extremes`) with a live-fetch fallback; `weather.yml` runs
`fetch_env → update_report`. Verified the cache-fed ranking is byte-identical to a live run.
The cosmetic `fetch_trip.py`/`build_report.py` file-split is **deferred** — scoring and
rendering share in-memory state across the 3-pass flight loop, so separating them is risk
with no functional gain. Publishing the normalized `days` view to the website is a follow-up.

### #25 — Standardized "Area character" tags: two-tier taxonomy + one JSON source of truth (2026-07-05)
**Decision:** the venue-card tags are a fixed **two-tier taxonomy** rendered identically on
the dashboard and the static venue pages: **Tier 1 · Trip fit** (dynamic — `cond`/`time`/
`trip`, about *this* trip's dates/origin/window) and **Tier 2 · Area taxonomy** (static —
`Character` · `Scale & grade` · `Hazards`). Each family is one labelled row, in a fixed
order, one colour per family. The controlled spec — family, colour, tooltip, order and the
"?" page copy for every tag kind — lives in [`../data/tag-spec.json`](../data/tag-spec.json)
as the **single source of truth**: `update_report.py` generates the tag CSS, tooltips,
legend and emit-order from it, and `build_knowledge.py` fills the tables in
[`../data/tags.md`](../data/tags.md) (the reader-facing key the "?" opens) from the same file
via `{{TAGTABLE:…}}` placeholders. Two key collisions were split (`height` → `wallheight`/
`tallest`, `grade` → `grade`/`pitches`) and the meta `auto` pill dropped.
**Why:** pills used to render in append order with two kinds doing double duty, so the same
colour meant different facts on different cards and there was no legend. Dynamic-vs-static is
the real hierarchy — the test is *"would it ever tag a single climb?"* (`cond`/`time`/`trip`
never would; the static families are the exact vocabulary that will tag each climb later,
since a venue value is a rollup of its climbs — see [`../data/taxonomy.md`](../data/taxonomy.md)).
One JSON authority kills the drift between the three copies that existed before (the CSS
grouping, the `TAGT` tooltip dict, the doc tables). It lives in `knowledge/data/` **not** the
trip folder because it is static, trip-independent. Terminology verified against
**multi-pitch.com** (`Rock Type`, `Aspect`, `Grade (BAS)`, the exact hazard flags),
**UKClimbing** crag facets, and our own `taxonomy.md`.
**Trade-off:** how each pill's *text* is computed stays in `venue_tags()` — that is genuinely
code, not data — so the spec is the authority for taxonomy + presentation but not extraction;
a new tag kind still needs a one-line `add()` in `venue_tags()` alongside its spec row.
**Status:** ✅ Live — dashboard + all 42 static venue pages render from the venue's JSON
payload (`v["tags"]`); the "?" opens `knowledge/data/tags.html`; generated CSS/tooltips/legend
verified byte-identical to the prior hand-written versions.

### #26 — Tighten the climbing heat curve: bite from the top of the ideal band (2026-07-05)
**Decision:** move the `heat_penalty` knees down and steepen the slopes —
`heat_penalty(tmax) = 1.5·(t−18)⁺ + 4·(t−24)⁺ + 6·(t−28)⁺` (was `1.2·(t−20)⁺ + 3·(t−25)⁺
+ 5·(t−30)⁺`, decision #16). Gentle from **18°C** (the top of the research ideal band, was
20), steep from **24°C** (was 25), brutal from **28°C** (was 30). Constants
`HEAT_WARM_C/HEAT_HOT_C/HEAT_BRUTAL_C` in `update_report.py`; shared with the chart colouring
and header ring via `climateThresholds`, so the "?" ranking explainer, the felt-temp legend
and the score all move together. No change to the cold penalty (below 8°C) or the aspect/sun
felt-temperature adjustment.
**Why:** even after #16, a dry-but-warm venue still out-ranked a cooler-but-showery one — the
July table put **Gredos #1** on 0% rain despite a ~25°C felt-on-rock seasonal outlook, and
Paklenica/Montserrat/Elbsandstein (28–32°C) sat mid-table. Root cause was an asymmetry: rain
costs `−0.9/%` (a 50%-wet venue loses ~45) while the old heat curve took only ~6 points off a
25°C venue and ~14 off 27°C. On multi-pitch — hours exposed on the wall with no shade retreat
— heat is the bigger enemy, so the curve should be at least as harsh as the rain curve is
generous. The new curve costs ~15 points at 25°C felt and ~66 at 31°C.
**Effect (weather-only score, cached climatology + 45-day outlook):** cool-dry venues rise
(**Aladağlar** 13°C → top on weather), baking venues drop hard (**Zádiel −14, Elbsandstein
−13, Spitzkoppe/Paklenica −11, Freÿr/Gredos −6**). Gredos stays upper-mid — its *climatology*
is genuinely cool at altitude (21°C, the 70% weight); it's the 25°C seasonal term that costs
it. The live composite (weather 55% + travel + fit) reshuffles on the next `weather.yml` run.
**Status:** ✅ Live — curve + "?" explainer + docstrings shipped in `update_report.py`; site
ranking updates on the next scheduled build.

### #27 — One authored `corpus.json` is the source of truth; supersedes the sheet-as-master (#15) (2026-07-06)
**Decision:** consolidate the five scattered climb/venue sources into a **single authored
`db/corpus.json`** — `areas[]` (crag/region tree with coords, rock, aspect) + `routes[]`
(climbs carrying taxonomy *values* inline), shaped 1:1 with the `route`/`area` schema
([`../data/route-schema.md`](../data/route-schema.md)) so it is a **drop-in Postgres seed**,
not a rival store. Curated vs uncurated is a **field, not a file**: `status`
(`publish|draft|quarantined`) + `dataGrade` 1–7. **`GAZETTEER` is deleted** — every area,
curated or not, is a row with coords. **multi-pitch.com/data.json is a *seed*, not a third
live source** (`build_corpus.py` pulls it once into `status: draft` rows). The Google Sheet
stops being the master (**reverses #15**): `climbing-trips.csv` becomes a *derived export*
of the curated slice. Trips become **derived selections** — a `trip.json` holds refs +
per-person travel/priority overlay, never crag facts. Taxonomy *definitions* stay in
`tag-spec.json`/[`taxonomy.md`](../data/taxonomy.md) (**#25**), referenced not duplicated.
Full design: [`../data/source-of-truth.md`](../data/source-of-truth.md).
**Why:** three places (`venues.json`, `GAZETTEER`, geocoder) independently answered "where is
this crag?", and nothing linked the corpus DB (World A) to the trip dashboard (World B) — so
"where do I add a climb?" had five answers. One authored file with a `status` flag gives the
curated/uncurated split Michel wanted, kills the coordinate sprawl, and is exactly the seed/
export shape #18 already wants (JSON now → Postgres at scale). The sheet can't hold coords or
per-climb taxonomy, so mastering venue data in it (#15) had hit its ceiling.
**Supersedes:** #15 (sheet-as-master → derived export). Extends #18 (corpus.json is the
human-authored seed the DB loads) and #25 (taxonomy authority unchanged). Decision #2
(repo-as-DB for the live dashboard) still governs `index.html` generation until the pipeline
reads `corpus.json`.
**Status:** ⚠️ Partial — `db/corpus.json` + `db/tools/build_corpus.py` (seeded from
multi-pitch + `venues.json` + the curated DB routes) and the docs/dependency-map land now;
rewiring `update_report.py`/`sheet_venues.py` to *read* corpus.json (and drop `GAZETTEER`) is
the trip-planner pipeline's follow-up, then ingestion into Postgres (Stage 5 / M2).

### #28 — Symmetric rain curve + distance-from-home + preference weights (2026-07-07)
**Decision:** three ranking changes, tuned/validated on a new offline backtest harness
(`trip-ni-july-2026/scripts/backtest_ranking.py`):
1. **Rain penalty now mirrors the heat curve** (#26): `rain_penalty(wet%) = 1.25·(w−12)⁺ +
   1.5·(w−40)⁺` (was flat `0.9·rain_pct`). A dry-climate comfort band under ~12% wet, then a
   slope that **steepens past 40%** — so a cool-but-wet venue is punished as hard as a
   dry-but-hot one. Shared by `climo_score`; `RAIN_IDEAL_PCT/RAIN_STEEP_PCT` in `weather.py`.
2. **Distance-from-home** added as a 5th `venue_fit` sub-signal (100 near → 0 at ~4000 km,
   mean of Michel-from-London and Dan-from-nearer-of-Belfast/Dublin) **and** as a travel-cost
   fallback (`£40 + £0.08·km`) when a venue has no live flight price — fixing the top-N blind
   spot where an un-priced far venue scored a neutral travel term. `top_n_flights` raised
   **4 → 10** (SerpApi Starter plan).
3. **Per-sub-signal preference weights** (`engine.models.Preferences`, all `1.0` = no-op)
   scaffolded through the composite — the hook a future user-preferences UI writes into.
**Why:** Michel's call — after #26, cool-but-drizzly venues (Snowdonia 58%, Dolomites 67%)
still coasted on mild temperatures above hot-dry ones; *both* extremes should sit low, with
cool-and-dry the sweet spot. And a far venue with no priced flight was hiding behind a neutral
travel score. Distance belongs in the ranking even before flights are fetched.
**Effect (live composite, cached climatology + outlook):** top reshuffles to cool-dry-and-near
— **Écrins #1, Lundy #2, Picos #3**; **Aladağlar #1→#6** (Turkey, distance); wet venues sink
(**Dolomites #36, Snowdonia #28**) and so do hot-dry ones (**Wadi Rum #41, Medina #42**).
Historical backtest: wet venue-days (≥45%) avg weather score **47 → 22**, dry (≤20%) **51 → 49**.
**Extends:** #26 (same symmetry argument, now applied to rain). **Status:** ✅ Live — shipped in
`engine/weather.py`, `engine/scoring.py`, `engine/models.py`, the "?" explainer + donut widget
(`render.py`), and this doc; site ranking rebuilt on deploy.

### #29 — Coverage-weighted forecast blend + weathercode rain fallback (2026-07-08)
**Decision:** two fixes to how the live forecast supersedes climatology, after Michel spotted
a soaking-wet Dolomites ranked #2:
1. **Coverage-weighted blend.** The 16-day forecast reaches the *start* of the window ~15
   days out but doesn't span the trip for days. While it covers only `k` of `N` trip days,
   weather = `(k/N)·forecast_mean + (1−k/N)·climo_component` — it no longer *supersedes* the
   whole typical-week verdict on a 2-day sliver. Fully takes over at `k = N`. Basis label +
   banner now state the `k/N` coverage. (`scoring.evaluate`, `update_report.build_banner`.)
2. **`effective_rain_prob`.** Open-Meteo drops `precipitation_probability_max` past ~14 days;
   `day_score`'s `(prob or 0)` read that None as **0% rain**, scoring drizzly horizon-edge
   days ~perfect. Now infer probability from the weathercode when it's missing (clear 5% …
   drizzle 60% … rain 80% … storm 90%). (`weather.code_rain_prob`/`effective_rain_prob`.)
**Why:** the window (22–27 Jul) had just entered the forecast edge (reaches 23 Jul), so all
27 forecast-basis venues were ranked on **only 22–23 Jul**, and the 9 alpine ones had **no
rain-probability on both days** — the two bugs compounded to launch a 67%-wet venue
(climo weather 0) to weather **87**, #2 overall. Pre-existing latent bugs, surfaced by the
window reaching the horizon; unrelated to the #28 rain curve (that only touches climatology).
**Effect (today's board):** Dolomites weather **87 → 17** (#2 → #31), East Tyrol **78 → 16**;
Écrins stays strong (**83**, good on both bases — correctly *not* penalised). New top:
Lundy · Picos · Tenerife · Gredos · Aladağlar · Mournes · Écrins. **Extends** #28 / the
three-horizon model. **Status:** ✅ Live — `engine/weather.py`, `engine/scoring.py`,
`update_report.py`, the "?" explainer (`render.py`), condition-algorithm.md; deployed.

---

### #30 — ECMWF ensemble as the horizon-edge confidence layer (2026-07-08)
**Decision:** Add Open-Meteo's free, keyless **ECMWF-ENS** (`ecmwf_ifs025`, 51 members) as a
per-date confidence signal over the ~7–16-day band, rather than switching weather providers
or buying a longer (unskillful) deterministic forecast. `weather.ensemble_raw` +
`ensemble_metrics` reduce the members to `ens_prob` (% of members with ≥1 mm) and the `tmax`
spread; `effective_rain_prob` now prefers, in order, the real `precipitation_probability_max`
→ `ens_prob` → the weathercode guess. `scoring.evaluate` fetches the ensemble **only for
in-window venues** and merges `ens_prob` into the per-date metrics, feeding both `day_score`
and the displayed max-rain-probability. Cached per venue by `fetch_env.py`.
**Why:** research (see [`../data/weather-models.md`](../data/weather-models.md)) confirmed
the 16-day cap isn't the limit worth chasing — past ~15 days there's no deterministic skill,
so no "30-day API" helps. The real gap was *confidence* on the 7–16-day edge, where a single
run is noise: on 2026-07-08 the top models split Fair Head's 20 July at **0.0 / 2.2 / 5.6 mm**,
while the 51-member ensemble read a coherent **75% wet, 14–24°C**. This directly hardens the
exact horizon-edge days the #29 coverage blend leans on, replacing the weathercode *guess*
there with a member-based probability. Kept `best_match` for the deterministic layer (it
carries 15/16 days at Fair Head vs ECMWF-only's 14; UKMO/ICON die at ~6–7 d). Live-fallback
path is rate-limited (HTTP 429) → the `fetch_env.py` cache is the intended source; the
in-window gate keeps live fetches to a handful. **Extends** #29 / the three-horizon model.
**Status:** ✅ Live — `engine/weather.py`, `engine/scoring.py`, `fetch_env.py`,
condition-algorithm.md, weather-models.md; tests green (17), driver runs clean.

---

### #31 — Daily weather widget: a provenance-labelled table (2026-07-08)
**Decision:** Rebuild the per-day weather strip from an unlabelled tile row into a **labelled
table** — columns = days, rows = one measurement each, named once down a sticky left gutter
(Sky·UV / Temp / Rain / Wind / Sun / Tide). Every column now carries a **provenance chip**
stating how reliable that day is — **Forecast** (≤7 d, high skill) · **Low conf** (7–16 d,
ensemble-backed) · **Outlook** (45-day seasonal) · **Typical** (climate average) — reinforced
by opacity (fades with certainty) and a dashed amber **"forecast horizon" line** in the strip
where the live forecast gives way. Rain leads with a member-based **chance-of-%** and a single
bar (typical shown as a dashed tick, not a competing fill); low-confidence temperature carries
an **ensemble min–max whisker**; UV rings are solid when measured, dashed when estimated. The
tap/hover panel is rewritten as a plain-language, one-line-per-measurement breakdown led by
what to trust. New per-day fields `prov` + forecast `prob`/`pop`/`tlo`/`thi` plumb the
ensemble (#30) through `scoring.fc_days` → `render.venue_payload`.
**Why:** the old strip rendered a 3-day forecast and a 30-day climate average with identical
pixels, and never named what any bar/ring meant (its one legend was `display:none` on mobile).
Users couldn't tell real weather from a guess — the exact honest-uncertainty gap #29/#30 were
closing in the *ranking*, now closed in the *display*. Design reviewed with Michel via an HTML
teardown before build; "label the rows once" (Approach A) chosen over per-tile labels
(cluttered ×N days) or a detached legend. Verified with headless-Chrome renders on desktop +
mobile. **Extends** #30. **Status:** ✅ Live — `engine/render.py`, `engine/scoring.py`,
condition-algorithm.md; tests green (17).

---

### #32 — Suggestions & ranking read curated (human-tagged) data only (2026-07-13)
**Decision:** One governance rule across both worlds: anything that **recommends** (agent
search results, dashboard venue ranking) may only use rows with **`status: publish` AND
`taggedBy: human`**. To make the tiers queryable, every route in `corpus.json` now carries
**`taggedBy: human | llm | source`**, and LLM-tagged rows keep **`tagProv: {model, date}`**
(carried from `enrichment-cache.json`'s `_prov`, which was previously dropped on merge —
human and machine tags were indistinguishable downstream). `build_corpus.py` also refuses
to overwrite `taggedBy: human` tags with LLM output on rebuild. Live environmental data
(weather/flights/stays) is exempt as *conditions* — provenance-labelled per #31, never a
climb fact. Full policy + tier table: [`data/governance.md`](../data/governance.md).
**Why:** Michel: the data map showed "so many sources" with no way to see at a glance what
is curated — and rankings must not be built on unverified scrape/AI output. Audit found
`agent/search.py` already enforces `status='publish'`, but the dashboard's *Coverage*
sub-score counts raw multi-pitch.com routes and its tidal flag comes from the same
uncurated feed.
**Status:** ⚠️ Partial — provenance fields + governance doc live (`corpus.json` schema 1.1,
50 routes stamped `llm`, 8 `human`); the `scoring.py`/`update_report.py` enforcement rides
on the #27 🔜 pipeline switch (trip-planner process).

---

### #33 — Trips become editable: file-backed multi-trip + local admin forms (2026-07-13)
**Decision:** Generalise from the one hardcoded NI trip to a committed **`trips.json`**
(schema doubles as the future API contract), traveller list fully config-driven (the
"M2+" left in `engine/models.py`), one dashboard per live trip under `trips/<slug>/`,
public root becomes a **trips list**, and the approved three-screen forms (list / new /
manage) ship as a **localhost-only FastAPI admin page**. Storage stays files + JSON for
now — DB + API is an explicit later migration (`TripStore` seam), not built today.
SerpApi policy: **only the nearest-departing live trip prices flights**; others use
distance estimates. Multi-trip rendering lands behind `MULTI_TRIP=1`, off until the NI
trip ends (28 Jul); the root-URL swap is gated on the same date. Full plan:
[`trip-editing-plan.md`](trip-editing-plan.md).
**Why:** Michel: the header pills ("✈ Michel · London …") and the whole trip are
hardcoded — wants to add/remove/edit people and trips; happy to keep hardcoded file
structure/JSON for the time being, "we will move to db and api at one point". Single
editor (Michel), so no auth; quota is the scarce resource, so it never multiplies with
trip count.
**Status:** ⚠️ Partial — M1 (trips.json registry + loader, `dcbe6a6`) and M2 (traveller
generalisation: no hardcoded traveller keys left in engine/; pills/flight cards/markdown
all data-driven) live 13 Jul 2026. Trip window corrected to 24–28 Jul; `flex_days: 2`
in schema (±day flight/stay alternatives — planned, see plan §Date flexibility).
M3 (multi-trip behind flag) next; M4 root swap gated on trip end.

---

*Template for new entries:*
```
### #N — Title (date)
**Decision:** …
**Why:** …
**Status:** ✅ Live | ⚠️ Partial | 🔜 Planned | ❌ Reversed (see #M)
```

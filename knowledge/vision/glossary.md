# Glossary

Shared vocabulary — climbing domain terms and system/architecture terms. Keep this in
sync when new concepts appear in the code or docs.

## Climbing domain

| Term | Meaning |
|---|---|
| **Multi-pitch** | A climb long enough to be split into multiple rope-lengths ("pitches"), with belay stances between. The platform's namesake and focus. |
| **Trad (traditional)** | Climbing where the leader places removable protection (cams, nuts) as they go, rather than clipping pre-placed bolts. |
| **Sport** | Climbing that clips pre-placed bolts; lower gear burden. |
| **Topo** | A diagram of a crag/route showing lines, pitches, grades, and belays. Phase 4 renders "premium vector topos". |
| **Sector / crag** | A discrete climbing area within a larger venue/region. |
| **Venue** | A region or destination the engine ranks (e.g. Fair Head, Dolomites). One row in `venues.json`. |
| **Protection quality** | How safe/available the gear is. Standardized grades: `G`/`PG` (good), `PG-13` (mostly good, some runouts), `R` (serious, injury on fall), `X` (death/ground-fall potential). Phase-2 taxonomy isolates this. |
| **Friction window** | The period when rock friction is good for climbing — cool, dry, low humidity. Core output of the Predictive Condition Algorithm. |
| **Seepage** | Water weeping through rock after rain, keeping routes wet long after the sky clears. Limestone/overhangs seep for days. |
| **Drying rate** | How fast a crag returns to climbable after rain — a function of rock type, aspect, sun, and wind. |
| **Aspect** | The compass direction a crag faces — governs sun/shade and thus both temperature and drying. |
| **Climatology** | Long-run historical averages for a place/date (e.g. "typical July"). Used to rank before a live forecast is available. |
| **Sub-seasonal / seasonal outlook** | Forecasts beyond the ~16-day skillful window (~45 days here). Weak signal; blended, not trusted alone. |

## System / architecture

| Term | Meaning |
|---|---|
| **Trip Decision Engine** | The whole product — the 4-layer pipeline that answers "where/when/how to climb". |
| **The Scraper (Phase 1)** | Raw ingestion layer — static guidebook crawlers + live social scrapers. |
| **Taxonomy Engine (Phase 2)** | NLP/LLM layer that forces raw text into the strict data dictionary. |
| **Predictive Condition Algorithm (Phase 2)** | Scores friction/drying/seepage from micro-climate forecasts × rock parameters. |
| **Master index (Phase 3)** | The verified directory of classic sectors. Automated data maps *only* onto entries here. |
| **Zero-Garbage UGC** | Editorial stance: reject unverified user content; every surfaced climb is vetted. |
| **Dual Workspace (Phase 4)** | The split-screen dashboard: topo on one side, logistics/conditions on the other. |
| **Contingency Engine (Phase 4)** | Watches the plan; on bad weather/seepage, computes 3 dry nearby alternatives. |
| **Single source of truth** | A config file that drives downstream behaviour (`venues.json`, `flights.json`). |
| **Weather basis** | Which horizon a ranking rests on: `live forecast` › `climatology + 45-day outlook`. Always stated to the user. |
| **`day_score` / `climo_score`** | The per-day / climatological weather scoring functions — see `data/condition-algorithm.md`. |
| **`dataGrade`** | A normalized **1–7** difficulty scale that maps every grading system onto one sortable integer. From the multi-pitch.com data model — see `data/grade-conversion.md`. |
| **`gradeSys`** | Which grading system a grade is in (`BAS`/`UIAA`/`YDS`/`ALP`/`FS`/`N` plus further trad systems `EW`/`SX`/`BRZ`/`D`/`SCO`/`VF`/`S` and discipline systems `V`/`Font`/`WI`/`AI`/`M`/`A`/`C`). Always stored beside the raw grade. **Canonical closed list in `data/taxonomy.md`** — treat this as illustrative. |
| **Route record** | The canonical per-climb tagging target (identity, physical, grade, flags, prose, media) — see `data/route-schema.md`. |
| **Hazard / character flags** | Boolean tags — route (`tidal`, `seepage`, `abseil`, `traverse`, `boat`, `polished`, `loose`, `grassLedges`) + objective mountain (`rockfall`, `avalanche`, `serac`, `crevasse`, `altitude`, `stormExposed`, `cornice`). Full list in `data/taxonomy.md`. |
| **`incline`** | Route steepness: `Slab` → `Vertical` → `Overhanging`. |
| **BAS** | British Adjectival System — a two-part grade: adjectival (`VS`, seriousness) + technical (`5a`, hardest move). |
| **Ascent style** | *How* a route was climbed (an ascent event, not a rock attribute) — see `data/taxonomy.md`. |
| **Onsight** | Lead first try, clean (no falls/rests), with **no prior beta** and never having seen it climbed — the purest style. |
| **Flash** | Lead first try, clean, but **with prior beta** (told the moves / watched someone). |
| **Redpoint** | Lead clean **after rehearsing** the route over previous attempts. |
| **Beta** | Prior information about a route's moves/sequence. Having it is what separates a flash from an onsight. |
| **FA / FFA** | First Ascent (first to climb a line) / First Free Ascent (first to climb it free, no aid). |
| **Commitment grade** | Overall size/seriousness of the outing (NCCS `I`–`VII`, or alpine F–ED) — separate from technical difficulty. `IV`≈full day, `VI`≈multi-day. |
| **Escapable** | Whether a party can retreat partway up a multi-pitch route — a core seriousness attribute. |
| **Rack** | The set of protection gear a route needs (cams, nuts, quickdraws). |
| **Half / double ropes** | Two thinner ropes clipped alternately — standard trad multi-pitch practice; enables full-length abseil retreat. |
| **Objective hazard** | Danger from the mountain itself (rockfall, avalanche, serac, lightning), not from the climbing moves. |

## Data & governance vocabulary

The words we use about the data itself — several sound like file names but are **labels on
rows**, not places. One body of data, many stamps. Policy: [`data/governance.md`](../data/governance.md);
wiring: the [Data map](../data-dependencies.md); decisions [#27](../roadmap/decisions.md) / [#32](../roadmap/decisions.md).

| Term | In plain English | Meaning |
|---|---|---|
| **Corpus** (`db/corpus.json`) | *the library* | Latin "body" — the **one complete body** of climb/crag data. Everything else (trips, dashboard, CSV, Postgres) is a selection, view, or export of it. It is a **file**. |
| **Curated** | *verified by a human* | **Not a file** — a *filter* over the corpus: rows with `status:publish` **and** `taggedBy:human`. The only data suggestions/ranking may use (#32). |
| **Seeded** | *imported, unreviewed* | Rows a machine put in the corpus (multi-pitch.com scrape, gazetteer coords). They exist to be reviewed, not served. |
| **`status`** | *verified or not* | Per-row stamp: `publish` (a human verified the facts) / `draft` (nobody has yet). |
| **`source`** | *where it came from* | Per-row stamp: `curated` (hand-entered), `multi-pitch.com` (scraped), `sheet-gazetteer` (coords crutch). |
| **`taggedBy`** | *who did the tags* | Per-row stamp on the descriptive tags (features/character/protection): `human` / `llm` (Claude inferred them from prose) / `source` (came with the scrape). `llm` **never counts as curated**, even on a publish row. |
| **`tagProv`** | *the AI receipt* | On `taggedBy:llm` rows: which model tagged it and when — `{model, date}`. |
| **Promotion** | *review → verified* | The human workflow that turns a draft row curated: check facts against a guidebook, accept/fix each AI tag, flip `status→publish` + `taggedBy→human`. |
| **Enrichment cache** (`db/enrichment-cache.json`) | *the AI's notebook* | Cached LLM tag inferences, one per route, paid for once. Merged into the corpus as `taggedBy:llm`. |
| **World A / World B** | *the two islands* | The corpus DB (routes, the agent) vs the trip planner (venues, the dashboard). Today they don't sync — see the Data map. |
| **Overlay** | *trip choices, not facts* | A file that **references** corpus IDs and adds only trip-scoped judgment (who's going, priority, dates). Never copies crag facts. What `venues.json` becomes. |
| **GAZETTEER** | *the coords crutch* | A hand Python dict in `engine/sheet_venues.py` holding coords for sheet rows with no curated entry. Folded into the corpus by #27; scheduled for deletion. |
| **Environmental data** | *conditions, not climb facts* | Live weather / flights / stays. Can't be human-curated by nature, so it's exempt from the curated-only rule — allowed in scoring as *conditions*, always provenance-labelled (#31). |

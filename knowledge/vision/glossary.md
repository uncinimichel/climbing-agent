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
| **`gradeSys`** | Which grading system a grade is in: `BAS`, `UIAA`, `YDS`, `ALP`, `FS`, `N`. Always stored beside the raw grade. |
| **Route record** | The canonical per-climb tagging target (identity, physical, grade, flags, prose, media) — see `data/route-schema.md`. |
| **Hazard / character flags** | Boolean route tags: `tidal`, `seepage`, `abseil`, `traverse`, `boat`, `polished`, `loose`, `grassLedges`. |
| **`incline`** | Route steepness: `Slab` → `Vertical` → `Overhanging`. |
| **BAS** | British Adjectival System — a two-part grade: adjectival (`VS`, seriousness) + technical (`5a`, hardest move). |

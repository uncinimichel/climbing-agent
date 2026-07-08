# Roadmap — prototype → platform

The path from today's single-trip dashboard to the full four-layer engine. Staged so each
step is shippable and useful on its own. For the honest starting point see
[`architecture/current-state.md`](../architecture/current-state.md).

## Where we are

A **live single-trip Phase-4 dashboard** on **partial Phase-1 ingestion** and a
**deterministic slice of Phase-2 scoring**. Phase-3 curation is manual; Phase-1 social
scrapers, Phase-2 NLP taxonomy, and the Phase-4 contingency engine are not built.

**Product surface:** [`multi-pitch-site-plan.md`](multi-pitch-site-plan.md) is the same
roadmap written as a product plan for multi-pitch.com itself — climbing-agent is the engine,
multi-pitch.com is the surface it's meant to power (see decision #21). Stage 1 below is that
plan's Tier 1 conditions engine; Stage 3 is its Tier 2 curation-as-product.

## Stage 0 — Harden the prototype (near-term, no new layers)

Enhancements to what already runs. None are required for daily operation. Priority order
(carried from `PLAN.md`):

1. **Return-leg flight times** — 2nd SerpApi call per option (≈2× searches) to show
   inbound dep→arr, not just outbound.
2. **Price-drop alerting** — compare today's `flights-latest.json` to yesterday's history;
   below a threshold → **push a notification** (channel TBD, see below).
3. **Lock the date once chosen** — pin the combo in `flights.json`; track that single
   combo's price trend over time.
4. **Overlay live/seasonal forecast on the mini-graph** once in range (currently
   climatology) — show the actual forecast line for the trip window from ~8 July.
5. **Tides for sea-cliff venues** — flag non-tidal windows. Some approaches to tidal
   crags are only safe/possible at low tide, so this needs actual tide **times**, not
   just a yes/no flag. **✅ Shipped (5 Jul 2026):** venues carry a crag-level `tidal`
   flag (explicit in `venues.json`/`GAZETTEER` — Donegal, West Cornwall, Lundy, Devon,
   Isle of Wight — or derived from multi-pitch.com routes flagged `tidal` within 10 km;
   see [`../data/taxonomy.md`](../data/taxonomy.md)). For tidal venues the planner
   fetches hourly tidal sea level from **Open-Meteo Marine** (free, keyless — chosen
   over multi-pitch.com's RapidAPI endpoint, decision #22) and refines per-day high/
   low-water times with a parabola fit through each turning point. Surfaced as:
   low-water times (▼) on the weather tiles + full extremes in the tile tooltip, an
   always-visible "tidal — plan around low water" condition chip, a cyan
   `tide-dependent access` tag, and a Low-water column on the static venue pages. The
   marine model's horizon is ~10 days, so tide times reach the trip-window tiles from
   ~10 July; until then the widget says so explicitly.
6. **Per-crag detail** — link each venue to its UKC/theCrag/Mountain-Project page. **In
   progress (3 Jul 2026):** shipped as a new "More climbing in the area" section, rendered
   below the multi-pitch.com climbs list and explicitly labelled as *not curated* (unlike
   the rest of the page, it isn't backed by a live API or the spreadsheet). Data lives in
   the committed `trip-ni-july-2026/extra-climbing.json`, keyed by venue name, populated by
   hand/agent research rather than regenerated on every build (same pattern as
   `stays-cache.json`). Process per venue: real web search (never an invented/reconstructed
   URL — that's the exact class of bug fixed the same day in the accommodation links), then
   an HTTP reachability check on every candidate before it's persisted. Sources by priority:
   UKClimbing (UK/Ireland), theCrag.com (best international default), national
   federation/alpine-club sites (FEDME, FFCAM/refuges.info, CAI, Alpenverein — often the
   *only* real source for hut/access beta), guidebook publisher pages (Rockfax, Vertebrate,
   Cicerone), camptocamp.org (French/alpine wikis), and credible blog trip reports with real
   route/access detail (never SEO filler). **Done (4 Jul 2026): all 42 venues researched
   in 4 batches — 41 of 42 have real, HTTP-verified links (202 total); "Medina" (listed as
   Portugal/desert granite) has none because no real climbing area matches that
   name/description could be found after a genuine search effort — likely a data issue in
   the source venue list/spreadsheet worth checking, not a research gap.** A small number
   of links sit behind Cloudflare/bot-protection (403/503 to automated checks) on
   well-known sites (UKClimbing, theCrag.com) — kept, since these consistently clear for
   real browsers (same conclusion reached checking the accommodation links). Future
   maintenance: these links aren't re-checked automatically like the stays `web` links are
   (no periodic health-check wired up yet) — worth adding if link rot becomes visible.
   **Destination (4 Jul 2026):** this data maps to the `area_reference` table in the
   Postgres schema (decision #18) — once venues exist as `area` rows the JSON is imported
   and becomes an export, with the DB as the only source of truth (`verified_at` then
   drives the periodic health-check noted above).
7. **"Confidence"** — show climatology spread + seasonal ensemble agreement, not just means.
8. **Digest / daily check** — opt-in daily top pick + cheapest fares pushed to a channel
   (channel TBD, see below).
9. **Bump GitHub Action versions** to Node24 to clear the deprecation warning.
10. **Tests** — golden-master snapshot of the generated HTML/MD plus stdlib-`unittest`
    coverage of `day_score`, `climo_score`, seasonal aggregation, flight ranking, and
    banner logic; run in CI before deploy. Full plan:
    [`operations/testing-plan.md`](../operations/testing-plan.md).

> **Cross-cutting: a push-notification mechanism.** Several items above and in Stage 2
> (#2 price-drop, #8 daily check, the contingency-engine weather/seepage alert) all need the
> same missing piece — a way to reach Michel **off the page**: flight changes, the trip
> daily check, a bad-weather alert. GitHub Pages is static and can't send; the **daily Action
> is the sender** (a final `curl`/Python step). The channel is not chosen yet — options,
> trade-offs and a recommendation (Telegram / ntfy now; web push or OneSignal for the
> productised surface) live in [`../operations/notifications.md`](../operations/notifications.md).
> Decide the channel when the first alerting item actually ships.

## Stage 1 — Real condition intelligence (deepen Phase 2)

Turn the rain-proxy into the vision's **Predictive Condition Algorithm** — the engine side
of [`multi-pitch-site-plan.md`](multi-pitch-site-plan.md) Tier 1.1's per-climb climbability
rating:
- Add per-sector `aspect` + `seepage_class` to the master index.
- Combine Open-Meteo **hourly** (humidity, dew point, wind, temp) with rock/aspect →
  model **friction window**, **drying rate**, **seepage risk**.
- Emit the richer condition record (see [`data/schemas.md`](../data/schemas.md)).
- Feed it into ranking so "dry" means *actually dry*, not *low forecast rain*.

## Stage 2 — The Automated Contingency Engine (complete Phase 4)

- Watch the chosen venue's forecast; on a bad-weather/seepage alert, surface the **top-3
  dry alternatives** within a distance bound, with a plain-language why.
- Wire alerting into the daily job — the shared push mechanism noted under Stage 0
  ([`../operations/notifications.md`](../operations/notifications.md)).

## Stage 3 — Scale curation (industrialise Phase 3)

- Grow `venues.json` into a **verified sector directory** with stable IDs + provenance —
  now concretely the `area` tree + `area_reference` tables in the Postgres schema
  ([`../data/database.md`](../data/database.md), decision #18). Also the data side of
  [`multi-pitch-site-plan.md`](multi-pitch-site-plan.md) Tier 2's conditions-character
  blocks and season grids (structured fields, not prose, so the rating engine can consume
  them too).
- Automated mapping of parsed climbs onto the index; **quarantine unmatched** (never
  auto-surface — Zero-Garbage UGC).
- A curation workflow to promote/demote/merge/verify sectors.

## Stage 4 — The Taxonomy Engine (build Phase 2a)

- NLP/LLM parsing of guidebook prose → the strict data dictionary
  ([`data/taxonomy.md`](../data/taxonomy.md)), validated against enums, with provenance +
  confidence. Prefer Claude models (see `/claude-api`).

> **Concrete build plan:** the free, staged, source-by-source approach to Stages 3–5 (what
> to scrape, how to trigger it, where to store it, how to tag and curate it) is specified in
> [`ingestion-plan.md`](ingestion-plan.md).

## Stage 5 — Full-scale ingestion (build Phase 1)

- **OpenBeta as a first-class, license-clean source.** OpenBeta is CC-licensed open climbing
  data with a public GraphQL API — *meant* to be ingested, unlike ToS-restricted UKC/MP
  scraping. Ingest it into the master index by geo + name match. See
  [`../data/external-models.md`](../data/external-models.md).
- **Schema v2 aligned to OpenBeta** — hierarchical areas + inheritance, `gradeContext`,
  all-systems `grades{}`, composable `ClimbType`, structured `pitches[]`, `SafetyEnum`
  (+`runout`/`terrain`), access/stewardship layer. Enables loss-less import/export.
  **Started (4 Jul 2026):** the Postgres DDL in `db/` already implements the structural
  core (area tree + inherited `gradeContext`, all-systems `route_grade`, junction-table
  disciplines, structured `pitch`, evidence-gated hazards) — see
  [`../data/database.md`](../data/database.md); what remains is the ingestion to fill it.
- **Social condition scrapers** (Meta/X/TikTok geotags, guide whitelists) — respecting
  ToS + privacy; aggregated, non-personal summaries only.
- **Static guidebook/register crawlers** at web scale, writing to a raw-record store.

## Stage 5½ — Admin retrieval agent (chat over the DB)

Added 4 Jul 2026 (decision #19). An **admin page with a chat agent** that retrieves
climbs from the Postgres corpus in natural language — *"find me sandstone near me in
August"* → enum + geo + climate filters → ranked climbs with a plain-language why.

- **SQL-first, not a vector DB:** the example queries decompose entirely into closed-enum
  / PostGIS / climatology filters — a Claude tool-use loop calling a strict,
  enum-validated `search_climbs` tool (parameters generated from the DB lookup tables).
  The model never writes raw SQL.
- **Semantic tier later:** pgvector *inside the same Postgres* for prose/buzz similarity
  ("something adventurous…"), budget-gated with the rest of the semantic index.
- Doubles as the Phase-3 **curation console** front door, and is the internal precursor
  of Stage 6's single question-and-answer flow.
- Depends on the corpus having routes (M2+); full design:
  [`../architecture/retrieval-agent.md`](../architecture/retrieval-agent.md).
- **Started (4 Jul 2026):** step 1 shipped — `agent/` holds the `search_climbs`
  handler + CLI chat harness, verified against dev fixtures (`db/dev/sample_routes.sql`);
  next: `get_conditions`, the admin page, then pgvector.

## Stage 6 — Productise (multi-trip, multi-user)

- Generalise from one hard-coded trip to arbitrary trips/users.
- Embedded **premium vector topos** in the Dual Workspace.
- The "single question-and-answer flow" as the front door.

## Sequencing logic

Deepen what's live before widening (Stage 0→2 sharpen a working product), then scale the
data foundation (Stage 3→5), then productise (Stage 6). Each stage is independently
useful; nothing blocks the daily job from running.

# Roadmap — prototype → platform

The path from today's single-trip dashboard to the full four-layer engine. Staged so each
step is shippable and useful on its own. For the honest starting point see
[`architecture/current-state.md`](../architecture/current-state.md).

## Where we are

A **live single-trip Phase-4 dashboard** on **partial Phase-1 ingestion** and a
**deterministic slice of Phase-2 scoring**. Phase-3 curation is manual; Phase-1 social
scrapers, Phase-2 NLP taxonomy, and the Phase-4 contingency engine are not built.

## Stage 0 — Harden the prototype (near-term, no new layers)

Enhancements to what already runs. None are required for daily operation. Priority order
(carried from `PLAN.md`):

1. **Return-leg flight times** — 2nd SerpApi call per option (≈2× searches) to show
   inbound dep→arr, not just outbound.
2. **Price-drop alerting** — compare today's `flights-latest.json` to yesterday's history;
   below a threshold → open a GitHub issue / email / push.
3. **Lock the date once chosen** — pin the combo in `flights.json`; track that single
   combo's price trend over time.
4. **Overlay live/seasonal forecast on the mini-graph** once in range (currently
   climatology) — show the actual forecast line for the trip window from ~8 July.
5. **Tides for sea-cliff venues** (Fair Head, Gower, Cornwall) — flag non-tidal windows.
   Some approaches to tidal crags are only safe/possible at low tide, so this needs
   actual tide **times**, not just a yes/no flag. **Not started (noted 3 Jul 2026):**
   multi-pitch.com already solves this for its own climb pages — see
   `~/dev/multi-pitch/lambda-node/get-tides/getTides.js`, which calls the RapidAPI
   "tides" endpoint (`tides.p.rapidapi.com`, needs a `TIDES_HOOD_KEY`) per climb
   lat/lon and returns tide extremes/heights, filtered to climbs already flagged
   `tidal == 1` in multi-pitch.com's own data. Our `_climb_flags()` in
   `update_report.py` already surfaces that same `tidal` flag as a hazard chip on
   climb cards (see `TAGT['hazard']`) — the plumbing to know *which* climbs need
   this exists, just not the tide-times lookup or a low-tide-window callout in the
   weather section. When this gets built: reuse the same RapidAPI tides endpoint
   (or an equivalent free source) rather than re-deriving tide tables from scratch,
   and surface it per-venue only when at least one nearby climb is tidal.
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
   route/access detail (never SEO filler). First batch covers the top 5 ranked venues
   (Gredos, Écrins, Aladaglar, Picos de Europa, Tenerife); **remaining ~37 venues are
   queued** for incremental follow-up passes — a venue with no entry yet in
   `extra-climbing.json` means "not researched", not "nothing exists".
7. **"Confidence"** — show climatology spread + seasonal ensemble agreement, not just means.
8. **Email/Slack digest** — daily top pick + cheapest fares to a channel.
9. **Bump GitHub Action versions** to Node24 to clear the deprecation warning.
10. **Tests** — golden-master snapshot of the generated HTML/MD plus stdlib-`unittest`
    coverage of `day_score`, `climo_score`, seasonal aggregation, flight ranking, and
    banner logic; run in CI before deploy. Full plan:
    [`operations/testing-plan.md`](../operations/testing-plan.md).

## Stage 1 — Real condition intelligence (deepen Phase 2)

Turn the rain-proxy into the vision's **Predictive Condition Algorithm**:
- Add per-sector `aspect` + `seepage_class` to the master index.
- Combine Open-Meteo **hourly** (humidity, dew point, wind, temp) with rock/aspect →
  model **friction window**, **drying rate**, **seepage risk**.
- Emit the richer condition record (see [`data/schemas.md`](../data/schemas.md)).
- Feed it into ranking so "dry" means *actually dry*, not *low forecast rain*.

## Stage 2 — The Automated Contingency Engine (complete Phase 4)

- Watch the chosen venue's forecast; on a bad-weather/seepage alert, surface the **top-3
  dry alternatives** within a distance bound, with a plain-language why.
- Wire alerting (issue / email / push) into the daily job.

## Stage 3 — Scale curation (industrialise Phase 3)

- Grow `venues.json` into a **verified sector directory** with stable IDs + provenance.
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
- **Social condition scrapers** (Meta/X/TikTok geotags, guide whitelists) — respecting
  ToS + privacy; aggregated, non-personal summaries only.
- **Static guidebook/register crawlers** at web scale, writing to a raw-record store.

## Stage 6 — Productise (multi-trip, multi-user)

- Generalise from one hard-coded trip to arbitrary trips/users.
- Embedded **premium vector topos** in the Dual Workspace.
- The "single question-and-answer flow" as the front door.

## Sequencing logic

Deepen what's live before widening (Stage 0→2 sharpen a working product), then scale the
data foundation (Stage 3→5), then productise (Stage 6). Each stage is independently
useful; nothing blocks the daily job from running.

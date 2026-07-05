# Ingestion Plan — the free, staged build of Phase 1 → 3

> **Purpose:** the concrete "how do we actually start scraping every climb ever written
> down" plan. Turns the [mission](../vision/mission.md)'s Phase 1 (Scraper) → Phase 2
> (AI Taxonomy) → Phase 3 (Curation) from vision into a buildable, **free-tier**, staged
> pipeline — starting from a short, named list of sources.
> **Status:** 🔜 **Planned** — nothing here is built yet. This is the blueprint the first
> slice implements. Live ingestion today is the three structured pulls in
> [`phase-1-scraper.md`](../phases/phase-1-scraper.md).

## Decisions locked (from the scoping session)

| Question | Decision | Consequence |
|---|---|---|
| **Scope** | Multi-pitch, worldwide | Bounded corpus (~30–150k routes, *not* millions) — keeps repo-as-DB viable. |
| **Sourcing** | Aggressive, *but license-aware* | Max effort on clean/durable sources; social = aggregated signal, never raw PII. |
| **Storage** | ~~Repo-as-database (JSON)~~ → **Postgres in Docker** (decision #18) | Two-tier store (below) still applies; the durable tier's engine is now Postgres. |
| **Budget** | Free / near-free to start | DIY scraping; LLM-tag a curated subset; defer paid infra (semantic search, scraping APIs). |

These extend [`decisions.md`](decisions.md) #1–#13; the ingestion-specific call is logged as
**#14**. The honest tension — *aggressive + social + repo-as-DB + free* pull against each
other — is resolved by the **bounded scope** and the **two-tier store**.

## The two-tier store (how "aggressive + free + repo-as-DB" coexist)

The rule: **the durable corpus is curated and PII-free; the firehose lives outside both
git and the DB.**

| Tier | Contents | Where | Committed? |
|---|---|---|---|
| **Durable** | Curated master index + fully-tagged route records + **aggregated, non-personal** condition/buzz summaries | **Postgres + PostGIS in Docker** (`db/` — decision #18); git versions the DDL + seeds + curated exports | DDL/seeds ✅ · corpus lives in the DB |
| **Ephemeral** | Raw HTML/API captures + the raw social stream | GitHub Actions cache/artifacts (gitignored local cache) | ❌ never |

Phase 2 distils Tier-2 → Tier-1: raw social posts become *"Fair Head — reported dry, 3
mentions, last 48 h"*, and **only that summary** enters the durable tier.
*(Superseded 2026-07-04: this section previously recommended a committed SQLite file;
Postgres replaces it — see [`../data/database.md`](../data/database.md). The DB is on
course to be the **only source of truth** for venue/route knowledge; `venues.json` and
`extra-climbing.json` migrate in and become exports.)*

## Source registry — `sources.json` (config-as-truth)

Every source is a config row, never hard-coded (mirrors [`venues.json`](../../trip-ni-july-2026/venues.json)):

```json
{
  "id": "openbeta",
  "name": "OpenBeta",
  "type": "route-db",
  "method": "graphql",
  "license": "CC (open)",
  "tos": "ingestion-encouraged",
  "regions": ["*"],
  "cadence": "monthly",
  "teaches": "hierarchical areas, cascading gradeContext, all-systems grades, composable disciplines, structured pitches"
}
```

An LLM **discovery agent** (the [`deep-research`] pattern) proposes new rows per region;
Michel approves; the crawl frontier grows mechanically from each area→crag→route tree.

### Starter set — the four route databases

Named, in priority order. Each is a *blueprint* as much as a data source — the schema
lessons feed [`route-schema.md`](../data/route-schema.md) and
[`external-models.md`](../data/external-models.md).

| Source | Method / licence | What it teaches / gives us |
|---|---|---|
| **OpenBeta** | **GraphQL API · CC-licensed** — *built to be ingested* | The cleanest blueprint: hierarchical areas, cascading `gradeContext`, all-systems grade object, composable disciplines, structured pitches. **First source — no ToS risk.** |
| **theCrag** (~1M routes) | API if granted, else polite public scrape · ToS-restricted | Grade context at *any* level + structured tag-sets that cascade down area→crag→route; a 0–100 quality score → **0–3 stars** (adopt for editorial `stars`). |
| **UKClimbing** (~150k) | Polite public scrape · ToS-restricted | Faceted crag search by **rocktype / aspect / type**; first-class **access notes** (feeds an access/stewardship layer). |
| **Mountain Project** | Polite public scrape · ToS-restricted (API deprecated) | Multi-discipline route type; **grade-system auto-detection from leading chars** (`5.`→YDS, `V`→V-scale, `WI`→ice, `M`→mixed…) — adopt as a cheap deterministic pre-classifier. |

> **Sequencing:** OpenBeta is the *only* clean-licence route DB, so it's the **first slice**
> end-to-end. theCrag/UKC/MP are grey-area public-page scraping — rate-limited, cached,
> `robots`-respecting, no login-walled data — added once the clean pipeline works.

### Social sources (signal, not a route DB)

Prefer **official APIs** (durable) over scraping (cat-and-mouse); always aggregate.

| Platform | Access | Primary job |
|---|---|---|
| Reddit (r/climbing, r/tradclimbing…) | Official API | Discovery + conditions |
| YouTube (descriptions/titles) | Data API | Discovery (route beta, topos) |
| Instagram / TikTok (geotag + hashtag) | Scrape (ToS-restricted) | Conditions + discovery |
| Facebook regional climbing groups | Scrape (ToS-restricted) | Live conditions |
| X · UKC forums · Strava segments | Scrape / API | Conditions + access chatter |

## Social has three jobs

The user's ask, made concrete:

1. **Discovery** — surface routes/crags *not yet in the master index* (a mention of an
   unknown line → a `status: draft` candidate for curation, never auto-surfaced).
2. **Enrichment** — attach *new tags/info to existing routes*: a post saying "seeping badly
   after the storm" or "the second pitch is polished now" → proposed flag updates
   (`seepage`, `polished`) with provenance + confidence, pending verification.
3. **"What people are saying"** — a planner UI section per venue: a distilled **buzz card**
   — recent-mention count, a one-line condition read (*"reported dry · 3 mentions · 48 h"*),
   a couple of **paraphrased, non-personal** beta snippets, and links out. Labelled as
   **low-confidence social signal**, clearly separate from the deterministic weather score.

**Data handling (non-negotiable, per [`CONVENTIONS.md`](../CONVENTIONS.md) + GDPR):** extract
*place + condition + timestamp*, **aggregate, discard the person, store no raw PII**. The
product needs condition truth, not surveillance — and the aggregated form is all that ever
touches the public repo.

## Triggering — a GitHub Actions matrix, event-driven where it counts

Extends the existing serverless model ([`overview.md`](../architecture/overview.md)); no new infra.

| Track | Trigger | Cadence | Why |
|---|---|---|---|
| OpenBeta / route DBs | `schedule` + `workflow_dispatch` | monthly / on-demand | Route facts change rarely; full-corpus refresh is expensive. |
| Grey-area page scrape | `workflow_dispatch` backfill | on-demand | Politeness + quota; run in bounded batches. |
| **Social conditions** | **`repository_dispatch`** fired when a trip/venue is *watched* | daily *during an active trip window only* | Ties Phase 1 → Phase 4: scrape "is it dry now" **only for sectors someone cares about this week**. This one rule keeps volume, cost, and repo size sane. |

## AI tagging pipeline (Phase 2) — hybrid, validated, provenanced

Contract (from [`route-schema.md`](../data/route-schema.md)): **free text in → validated
route record out**, with confidence + source span, `status: draft` until human-verified.

- **Mechanical** for fields that copy cleanly across sources: `originalGrade` (+ `gradeSys`
  via MP's leading-char detector), `length`, `pitches`, `geoLocation`, stated `face`/`rock`.
- **LLM (Claude, structured-output / tool-forced JSON matching the enums)** for the fields
  that must be *inferred from prose*: protection `G/PG/PG-13/R/X`, hazard flags
  (`seepage`/`loose`/`tidal`), `incline`, and the generated description prose.
- **Validate-and-repair:** every LLM value is checked against the closed enums in
  [`taxonomy.md`](../data/taxonomy.md); off-dictionary → repair or quarantine, never surface.
- **Model choice / structured outputs:** see the [`/claude-api`] reference. Cost control
  under the free budget: LLM-tag only the **curated subset** (routes that map to a verified
  sector), not the whole scraped frontier.

**Are the current tags good enough?** Yes — `taxonomy.md` + `route-schema.md` are the target
as-is. The only additions (already noted in [`external-models.md`](../data/external-models.md))
are editorial `stars` (from theCrag's 0–100), structured first-ascent, `boltsCount`, and
OpenBeta's hierarchical-area model. Refine, don't rebuild.

## Curation & dedup (Phase 3) — one canonical record from many sources

- **Entity resolution:** the same route appears in OpenBeta *and* UKC *and* MP *and* social.
  Match by **geo proximity + normalised name** into **one canonical record** carrying a
  `provenance[]` array (source, url, span, confidence per field).
- **Allow-list, default-deny:** a scraped/tagged route surfaces *only* if it maps to a
  verified master-index sector; **unmatched → quarantined** `status: draft` (Zero-Garbage UGC).
- **Editorial `stars`** seed from theCrag's quality score, then human taste overrides.

## Retrieval

**PostGIS** `geography` + GIST for geo (the planner already does haversine matching), plus
`pg_trgm` normalised-name lookup for dedup/merge — both live in the `db/` schema now.
Semantic search ("what are people saying about X") needs an embeddings index — **deferred**
(budget-gated; pgvector is the natural fit when it opens); until then, buzz is
keyword/geo-matched.

## The first shippable slice (a vertical, not a layer)

Build one thin end-to-end path before widening — proves Phase 1+2+3 together:

| Milestone | Deliverable |
|---|---|
| **M0** | `sources.json` registry + the OpenBeta GraphQL client (clean-licence, keyless). |
| **M1** | Ingest OpenBeta for **one region** (propose: UK & Ireland) → raw records in the Tier-2 cache. |
| **M2** | Normalise into the **Postgres** corpus (`db/` schema, [`database.md`](../data/database.md)) against [`route-schema.md`](../data/route-schema.md); mechanical fields only. |
| **M3** | LLM-tag the inferred fields for that region's routes; validate against the enums; `status: draft`. |
| **M4** | Auto-map onto the master index (geo+name); quarantine unmatched; surface matched routes in the planner. |

Only after M0–M4 work do we add theCrag/UKC/MP scraping and the social tracks.

## Free-tier constraints & what's deferred

- **Free now:** OpenBeta API, GitHub Actions/cache, **Postgres+PostGIS in local Docker**
  (decision #18), LLM-tagging a bounded subset.
- **Deferred until budget opens:** *managed/hosted* Postgres (the schema ports as-is), a semantic/vector index, a
  managed scraping API (Apify/Bright Data) for hard/social targets, bulk LLM tagging at
  full-corpus scale.
- **Guardrails:** cap LLM calls per run; bounded scrape batches; log what was dropped rather
  than silently truncating (per [`CONVENTIONS.md`](../CONVENTIONS.md) quota discipline).

## ⚠️ Risks to keep visible

- **ToS:** theCrag/UKC/MP and all social platforms restrict scraping — expect blocks; prefer
  APIs; stay on public, non-login-walled pages; rate-limit and cache.
- **GDPR (Michel is UK/EU):** scraping identifiable people = processing personal data.
  Mitigation is the design itself — **aggregate, non-personal, no raw PII in the repo.**

## Open decisions (next grilling round)

1. **Curation at scale** — stays solo (Michel's taste), or opens to trusted contributors /
   AI-assisted pre-scoring that Michel approves?
2. **First region** — UK & Ireland (home turf, best social signal) vs a marquee alpine area?
3. **LLM tagging cost cap** — a hard per-run call budget once we exceed free-tier comfort.

---

*See also: [`phase-1-scraper.md`](../phases/phase-1-scraper.md) (capture),
[`phase-2-ai-taxonomy.md`](../phases/phase-2-ai-taxonomy.md) (tagging),
[`phase-3-curation.md`](../phases/phase-3-curation.md) (the moat),
[`external-models.md`](../data/external-models.md) (source schema analysis).*

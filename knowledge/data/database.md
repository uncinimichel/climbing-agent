# Database — the Postgres schema for the climbing corpus

The taxonomy and route corpus live in **Postgres (+ PostGIS)**, run locally via Docker
(decision [#18](../roadmap/decisions.md)). DDL, seeds and smoke test are in
[`db/`](https://github.com/uncinimichel/climbing-agent/blob/main/db/README.md) at the repo root; this page records the design and its
rationale. The trip dashboard's repo-as-JSON model (decision #2) is unchanged — Postgres
is the store for the **Stage 3–5 corpus**, and will eventually be the only source of
truth for venue/route knowledge (including what's hand-researched today in
`trip-ni-july-2026/extra-climbing.json`).

## Why a relational DB, not an ontology

The question was asked directly (2026-07-04): is the taxonomy an ontology use case
(RDF/OWL, triple store) or a normal SQL database? **SQL.** The taxonomy is a *faceted
classification with closed enums* ([`taxonomy.md`](taxonomy.md)'s explicit design rule),
not a knowledge graph:

- No **open-world inference** — rock behaviour, hazard semantics, grade relations are
  hand-authored curation decisions, not derived facts.
- Facets are **flat** (~14 disciplines, 16 rock types, 8 aspects, boolean hazards). The
  only hierarchy is the OpenBeta-style area tree — a `parent_id` tree + recursive CTE.
- External vocabularies (OpenBeta, theCrag, MP) are adopted by **hand-curated mapping**
  ([`external-models.md`](external-models.md)), not automated ontology alignment.
- The hard queries are **geospatial + filter** — exactly what PostGIS + indexes do.

Revisit only if the platform ever needs machine reasoning across many third-party
schemas — and even then, SQL stays operational with an RDF *export*, not a triple store
as primary. The same SQL-first logic governs retrieval: the planned admin chat agent
queries this schema through enum-validated tools, with pgvector inside this same
Postgres as the later semantic tier — see
[`../architecture/retrieval-agent.md`](../architecture/retrieval-agent.md) (decision #19).

## Design principles

1. **Closed enums → lookup tables.** One table per vocabulary in
   [`taxonomy.md`](taxonomy.md) (which stays the human source of truth — extend there
   first, then in the seeds). Rows carry the taxonomy's metadata (drying/seepage
   behaviour, dry-friction coefficients, severity ordering, what each hazard feeds).
   Off-dictionary values fail as **FK violations** — the DB itself enforces parser rule
   #1 (*repair or reject, never surface*).
2. **Set-valued facets → junction tables** (`route_discipline`, `route_feature`,
   `route_hazard`) — composable disciplines per OpenBeta's `ClimbType`.
3. **Safety-critical hazards require evidence.** A trigger rejects
   `tidal`/`seepage`/`loose` and all objective hazards without an `evidence_span`
   (parser rule #4).
4. **Grades are system-scoped.** Verbatim `original_grade` + `grade_system_code` +
   normalized `data_grade` 1–7; the observed ladder from
   [`grade-conversion.md`](grade-conversion.md) is seeded into `grade_conversion`;
   `route_grade` holds the all-systems object (OpenBeta `GradeType`).
5. **Hierarchical areas with downward inheritance.** `area` is a
   country → region → crag → sector tree; `grade_context`, rock, aspect and timezone
   set on an area cascade to descendants via the `area_resolved` / `route_resolved`
   views (external-models P0 #1–2).
6. **Provenance is first-class.** `provenance(route_id, field, source, span,
   confidence)` implements parser rule #2; `external_ref` holds structured source IDs
   (`ob_uuid`, `mp_id`, …) for dedup; `source` mirrors the ingestion plan's
   `sources.json` registry.
7. **Zero-Garbage UGC gate.** `route.status ∈ publish | draft | quarantined`; every
   route FKs to an `area` sector or stays quarantined (parser rule #6).
8. **Geo via PostGIS** `geography(Point)` + GIST, replacing the previously planned
   SQLite R-tree; `pg_trgm` indexes on names support the normalised-name dedup lookup.

## Table map

| Group | Tables |
|---|---|
| Taxonomy (seeded from `taxonomy.md`) | `grade_system` `rock_type` `protection_grade` `discipline` `feature` `character` `incline` `sun_window` `hazard` `ascent_style` `commitment_grade` + domain `aspect_dir` |
| Grades | `grade_conversion` (dataGrade ladder) · `route_grade` (all-systems object) |
| Hierarchy | `area` (tree) · `area_reference` (curated area links — absorbs `extra-climbing.json`) |
| Core record | `route` (identity, physical, grade, safety, approach/descent, conditions, editorial, prose, media) · `pitch` · `first_ascent` |
| Facets & flags | `route_discipline` · `route_feature` · `route_character` · `route_hazard` (+ evidence trigger) |
| Provenance & interop | `provenance` · `external_ref` · `source` · `route_reference` · `guidebook` · `route_guidebook` |
| Conditions | `route_climatology` (per-month rainyDays/tempH/tempL) |
| Views | `area_resolved` · `route_resolved` (inheritance) |

## Running it

```bash
cd db && docker-compose up -d   # first boot auto-applies sql/ (DDL + seeds)
./smoke.sh                      # end-to-end test, rolls back after itself
```

See [`db/README.md`](https://github.com/uncinimichel/climbing-agent/blob/main/db/README.md) for layout, connection string, and the
migration path (rebuild-from-scratch now; append-only migrations once the corpus is
durable).

## What this supersedes

The ingestion plan previously recommended a **committed SQLite file** as the durable
tier. Postgres replaces that: richer constraints (triggers, arrays, recursive views),
real geo (PostGIS), and no ceiling when ingestion scales. What is *versioned in git*
is now the DDL + seeds (+ curated exports while other files remain sources of truth);
the corpus itself lives in the DB. The ephemeral tier (raw captures, social firehose)
is unchanged — never committed.

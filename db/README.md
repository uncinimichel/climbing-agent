# db/ — the climbing corpus database (Postgres + PostGIS)

Local Postgres for the route corpus and taxonomy — decision **#18** in
[`knowledge/roadmap/decisions.md`](../knowledge/roadmap/decisions.md). Schema design
rationale and table map: [`knowledge/data/database.md`](../knowledge/data/database.md).
The controlled vocabularies it encodes: [`knowledge/data/taxonomy.md`](../knowledge/data/taxonomy.md)
(that file stays the human source of truth — extend enums there first, then in the seeds).

## Run it

```bash
cd db
docker-compose up -d          # postgis/postgis:16-3.4; first boot auto-applies sql/
./smoke.sh                    # end-to-end smoke test (rolls back, leaves no data)
./apply.sh                    # re-apply sql/ after edits (drops + rebuilds the climbing schema)
docker exec -it climbing-db psql -U climbing   # interactive psql
```

Connection: `postgres://climbing:climbing@localhost:5432/climbing` (local dev only).

## Layout

| Path | What |
|---|---|
| `sql/001_extensions.sql` | PostGIS + pg_trgm; drops/recreates the `climbing` schema (re-runnable) |
| `sql/010_taxonomy.sql` | Lookup tables — one per closed enum in `taxonomy.md` |
| `sql/020_core.sql` | `source`, `area` hierarchy, `route`, junctions, provenance, references, climatology |
| `sql/030_views.sql` | `area_resolved` / `route_resolved` — downward inheritance (gradeContext, rock, aspect) |
| `sql/1xx_seed_*.sql` | Enum values, the dataGrade ladder, the source registry |
| `smoke/smoke_test.sql` | Insert the taxonomy.md example route; verify enum rejection, hazard-evidence trigger, inheritance, geo radius query, grade mapping; rollback |

## Design in one paragraph

Closed enums are **lookup tables** (rows carry the taxonomy's metadata: drying behaviour,
friction, severity, what each flag feeds), so off-dictionary values fail as FK violations —
the DB enforces parser rule #1. Set-valued facets (`discipline`, `feature`, hazards) are
junction tables; **safety-critical hazards require an evidence span** (trigger — parser
rule #4). Areas are a `parent_id` tree with `grade_context`/rock/aspect **inherited
downward** via the `*_resolved` views (OpenBeta model). Grades stay **system-scoped**:
verbatim `original_grade` + `grade_system` + normalized `data_grade` 1–7, with
`grade_conversion` seeded from the observed ladder and `route_grade` for the all-systems
object. Field-level `provenance` (source, span, confidence) implements parser rule #2.
Geo is PostGIS `geography(Point)` + GIST (replaces the previously planned SQLite R-tree).

## Migration path

Until real ingestion lands (roadmap Stage 5 / M2), `apply.sh` rebuilds from scratch —
there is no versioned-migration tooling yet on purpose. When the corpus becomes durable,
switch to append-only numbered migrations and stop dropping the schema.

`trip-ni-july-2026/extra-climbing.json` (area-level curated links) maps to
`area_reference` and will be imported once venues exist as `area` rows; the JSON then
becomes a generated export until the DB is the only source of truth.

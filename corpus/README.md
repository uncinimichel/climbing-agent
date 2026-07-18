# db/ — the climbing corpus database (Postgres + PostGIS)

Local Postgres for the route corpus and taxonomy — decision **#18** in
[`knowledge/roadmap/decisions.md`](../knowledge/roadmap/decisions.md). Schema design
rationale and table map: [`knowledge/data/database.md`](../knowledge/data/database.md).
The controlled vocabularies it encodes: [`knowledge/data/taxonomy.md`](../knowledge/data/taxonomy.md)
(that file stays the human source of truth — extend enums there first, then in the seeds).

## Run it — no database, no Docker (decision #39)

**The JSON record under `db/record/` IS the database**: one document per route,
plus taxonomies, grades, the area tree and drawn topos. Git holds its readable
history; the versioned S3 bucket holds the cloud copy + the photos. Postgres
is gone — validation that used to be FK constraints now runs as JSON-Schema
enums generated from the taxonomy files (CI re-lints every change:
`validate-record.yml`).

```bash
git clone https://github.com/uncinimichel/climbing-agent && cd climbing-agent
python3 -m venv agent/.venv && agent/.venv/bin/pip install -r db/tools/requirements.txt
db/sync.sh pull          # photos + latest record from S3 (needs AWS creds; skip = no photos)
db/studio.sh             # → http://localhost:8890
```

Day-to-day: edit in the Studio (writes validate against the taxonomy schema
and land as pretty-printed JSON), then `db/sync.sh push` + `git commit db/record`
— that IS the save. `db/tools/lint_record.py` is the integrity gate (pre-push
and in CI). Queries beyond the Studio: DuckDB reads the record directly
(`SELECT ... FROM read_json_auto('db/record/routes/*.json')`).

### The Postgres escape hatch (legacy, dormant)

`db/sql/` (the full schema) and `tools/ingest_corpus.py` are kept ON PURPOSE:
the day the corpus outgrows JSON (a second concurrent curator, ~100k routes,
transactional bulk rewrites — see decision #39's breaking points), a Postgres
rebuilds from the record in minutes: run any postgres+postgis container,
apply `sql/`, `pip install psycopg[binary]`, run `ingest_corpus.py`. The
final pg_dumps from the retirement live in `db/backups/`.

## The Curation Studio — turn drafts into curated routes ✏️

```bash
../agent/.venv/bin/python tools/curate.py      # → http://localhost:8890 (localhost-only)
```

**Postgres-first (decision #34):** this app is how the corpus gets edited. The queue
serves `draft` routes one at a time with evidence alongside (source links, AI tag
receipt, OSM pin, climatology); you verify facts, fix tags, fill the gaps (stars,
season, sun window…), write the **intro / approach / pitch-by-pitch** prose, and
**Publish** (`⌘⏎`) — which atomically flips `status → publish` + `tagged_by → human`.
A CHECK constraint (`route_publish_needs_human_tags`, `sql/025_curation.sql`) makes a
non-human-tagged publish row impossible — governance #32 lives in the database. Not
verifiable from a desk? Flag it 🥾 *needs field check* with a curator note. The Grid
view bulk-edits one column across selected rows (never bulk-publishes).

**Taxonomy tab (#35):** vocabularies (discipline/feature/character/hazard/rock/
sun-window/protection) are managed here too — add a value with its one-line meaning
(the AI tagger reads it), edit inline, delete only when unused. Writes regenerate
`sql/105_taxonomy_extensions.sql` + `knowledge/data/taxonomy-values.json` automatically.
Grades are per-system validated (pick the scale first; publish blocks on mismatch);
parking is a structured `lat, lon` field.

**Export after every session:** the ⇩ button (or `python3 tools/build_corpus.py`) writes
the whole DB to `db/corpus.json` + the served copy under `knowledge/data/` — commit that
diff; it is the backup `ingest_corpus.py` restores from, and the audit trail of who
curated what.

**Full-fidelity backups (`./backup.sh [cloud]` → `db/backups/*.sql.gz`, committed):**
corpus.json does NOT carry the topo layer (media/topo/topo_line — the drawn lines);
a pg_dump has literally everything at ~200KB compressed. Run after real curation
sessions and commit. `infra/down.sh` refuses to destroy the cloud DB without taking
one first, so cloud-side edits can never die with the cluster.

## Layout

| Path | What |
|---|---|
| `sql/001_extensions.sql` | PostGIS + pg_trgm; drops/recreates the `climbing` schema (re-runnable) |
| `sql/010_taxonomy.sql` | Lookup tables — one per closed enum in `taxonomy.md` |
| `sql/020_core.sql` | `source`, `area` hierarchy, `route`, junctions, provenance, references, climatology |
| `sql/025_curation.sql` | Curation & tag provenance: `tagged_by`/`tag_prov`/`curation_notes`/`needs_field_check` + publish⇒human CHECK (#32/#34) |
| `sql/030_views.sql` | `area_resolved` / `route_resolved` — downward inheritance (gradeContext, rock, aspect) |
| `sql/1xx_seed_*.sql` | Enum values, the dataGrade ladder, the source registry |
| `smoke/smoke_test.sql` | Insert the taxonomy.md example route; verify enum rejection, hazard-evidence trigger, inheritance, geo radius query, grade mapping; rollback |
| `tools/curate.py` + `tools/curate_ui.html` | **The Curation Studio** (localhost:8890) — see above |
| `tools/ingest_corpus.py` | corpus.json + multi-pitch seeds → Postgres (restore path; never overwrites human rows) |
| `tools/build_corpus.py` | Postgres → `db/corpus.json` export (the committed backup) |
| `tools/crawl_worker.py` + clients | UKC/theCrag crawler → draft routes (resumable frontier) |
| `tools/ai_tag.py` | Claude infers features/character/protection from prose → `enrichment-cache.json`, lands as `taggedBy: llm` |

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

**⚠️ `crawl_frontier` changes this the moment the crawler is running for real.**
`sql/040_crawl.sql`'s `crawl_frontier` table (the crawler's durable work index —
`db/tools/crawl_worker.py`) accumulates state across days of unattended runs. Once it
holds real progress, **do not run `apply.sh`** — it drops the whole `climbing` schema,
discarding hours/days of crawl state along with everything else. At that point, switch
to additive migrations (new numbered `sql/0NN_*.sql` files applied individually, never
via the drop-and-rebuild loop) as this section already anticipated.

`trip-ni-july-2026/extra-climbing.json` (area-level curated links) maps to
`area_reference` and will be imported once venues exist as `area` rows; the JSON then
becomes a generated export until the DB is the only source of truth.

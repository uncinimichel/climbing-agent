# corpus/ — the climbing corpus (JSON record)

**The JSON record under `corpus/record/` IS the database** (decisions **#39** and
**#41** — Postgres removed entirely, one way to read the data). One self-contained
JSON document per route, plus `taxonomies.json`, `grades.json`, `areas.json` (the
area tree) and `topos.json` (drawn lines). Git holds readable history of the
compiled artifact; the versioned S3 bucket holds the working record + the photos.

The controlled vocabularies are authored in
[`knowledge/data/taxonomy.md`](../knowledge/data/taxonomy.md) (the human source of
truth — extend enums there, then in `record/taxonomies.json`). There is **no
Postgres, no Docker, no schema to apply**: the constraints that used to be FK/CHECK
live in [`tools/store.py`](tools/store.py), which validates every write against
**JSON Schemas generated from the taxonomy files** (an off-vocabulary tag fails like
the old FK violation), keeps publish⇒human as an if/then conditional, requires
evidence on safety-critical hazards, and lints referential integrity.

## Run it

```bash
git clone https://github.com/uncinimichel/climbing-agent && cd climbing-agent
python3 -m venv agent/.venv && agent/.venv/bin/pip install -r corpus/tools/requirements.txt
corpus/sync.sh pull        # photos + latest record from S3 (needs AWS creds; skip = no photos)
corpus/studio.sh           # → http://localhost:8890
```

Day-to-day: edit in the Studio (writes validate against the taxonomy schema and land
as pretty-printed JSON), then `corpus/sync.sh push` — S3 versioning is the record's
history. `tools/lint_record.py` is the integrity gate (run it before publishing).
Ad-hoc queries beyond the Studio: DuckDB reads the record directly, e.g.
`SELECT ... FROM read_json_auto('corpus/record/**/*.json')`; the retrieval agent
([`agent/search.py`](../agent/search.py)) filters the same record in memory.

## The Curation Studio — turn drafts into curated routes ✏️

```bash
agent/.venv/bin/python corpus/tools/curate.py    # → http://localhost:8890 (localhost-only)
                                                 # same app serves the cloud Studio Lambda (#40)
```

This app is how the corpus gets edited. The queue serves `draft` routes one at a time
with evidence alongside (source links, AI-tag receipt, OSM pin, climatology); you
verify facts, fix tags, fill the gaps (stars, season, sun window…), write the
**intro / approach / pitch-by-pitch** prose, and **Publish** (`⌘⏎`) — which atomically
flips `status → publish` + `tagged_by → human`. `store.py`'s schema makes a
non-human-tagged publish impossible (governance #32, now an if/then JSON-Schema rule,
not a DB CHECK). Not verifiable from a desk? Flag it 🥾 *needs field check* with a
note. The Grid view bulk-edits one column across selected rows (never bulk-publishes).

**Taxonomy tab (#35):** vocabularies (discipline/feature/character/hazard/rock/
sun-window/protection) are managed here — add a value with its one-line meaning (the AI
tagger reads it), edit inline, delete only when unused. Writes update
`record/taxonomies.json` (via `store.save_taxonomies()`, which regenerates the write
schema) and the served `knowledge/data/taxonomy-values.json`. Grades are per-system
validated; parking is a structured `lat, lon` field.

**Publish the artifact (`corpus/publish.sh`):** lints the record, compiles the
published subset into `corpus/corpus.json` (+ the `knowledge/data/` copy) and
`manifest.json` via `tools/build_corpus.py`, and pushes record + manifest to S3.
`corpus.json` is the committed, human-readable snapshot the Corpus Inspector and
website read.

## Ingestion — scrape → LLM-tag → draft

New climbing enters through the **[`ingest/`](../ingest/)** module (its own README),
not this directory: a resumable crawl frontier walks each source area→crag→route,
maps + LLM-tags the results, and lands them as `status: draft` in an S3-keyed holding
pen (`record/_ingest/…`, which `store.py` ignores) for the Studio to curate. The
per-source scraper clients it drives — `tools/openbeta_client.py`, `thecrag_client.py`,
`ukc_client.py`, `browser_fetch.py` — still live here and are imported by `ingest/`.

## Layout

| Path | What |
|---|---|
| `record/` | **the database** — route docs at `country/region/crag/route.json` + taxonomies/grades/areas/topos |
| `tools/store.py` | the in-memory JSON store: loads the record, generates the write schema from the taxonomy, validates + persists atomically (local + S3) |
| `tools/curate.py` + `curate_ui.html` | **the Curation Studio** (localhost:8890 and the cloud Lambda) |
| `tools/lint_record.py` | referential-integrity gate — run before publish |
| `tools/build_corpus.py` | record → `corpus.json` + `manifest.json` (the committed artifact) |
| `tools/topo_api.py` · `images.py` | topo lines + photo handling for the Studio |
| `tools/{openbeta,thecrag,ukc}_client.py` · `browser_fetch.py` | source scrapers, driven by `../ingest/` |
| `sync.sh` · `studio.sh` · `publish.sh` | pull/push S3 · run the Studio · compile+publish the artifact |

## Design in one paragraph

Closed enums are **taxonomy rows** carrying each value's metadata (drying behaviour,
friction, severity, what a flag feeds); `store.py` turns them into JSON-Schema `enum`s,
so an off-dictionary value fails validation the way an FK used to. Set-valued facets
(`tags.disciplines/features/character`, `hazards`) are arrays; **safety-critical hazards
require an evidence span** (checked in `validate()`). Areas are a `parent_id` tree with
`grade_context`/rock/aspect **inherited downward** (computed once in
`store._resolve_areas`, the old `*_resolved` views). Grades stay **system-scoped**:
verbatim `original_grade` + `grade_system_code` + normalized `data_grade` 1–7. Field-level
`provenance`/`external_refs` record source + span + confidence. Geo is plain `lat/lon` with
in-memory haversine (the planner and `search.py` both match that way) — no PostGIS.

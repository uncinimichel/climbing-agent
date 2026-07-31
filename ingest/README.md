# `ingest/` — scrape the world's trad multipitch, LLM-tag it, feed the Studio

This is the home of **Phase 1 (Scrape) → Phase 2 (AI tag) → Phase 3 (Curate)** from
[`knowledge/roadmap/ingestion-plan.md`](../knowledge/roadmap/ingestion-plan.md). The
mission: mechanically discover multi-pitch climbing worldwide, tag it with an LLM, and
land it as `status: draft` for human curation in the Studio. **No Postgres** — the JSON
record under `corpus/record/` is the database (decision #39); this module writes through
[`corpus/tools/store.py`](../corpus/tools/store.py).

## The pattern: a crawl frontier

*"How do we mechanically keep track of area → climbing?"* — one durable queue, one row
per node, walked **breadth-first from area → crag → route**. Every row carries its own
fetch/tag status, so the crawler can be started, stopped, or killed at any point and
resume with nothing lost. That's the whole idea: a work queue with per-node status is a
resumable crawler. It lives in [`frontier.py`](frontier.py), backed by
`corpus/record/crawl-frontier.json`, and it is **source-agnostic**.

```
python ingest/frontier.py --status              # where every source stands
```

## Two source families, one spine

Sources are config rows in [`sources.json`](sources.json) (never hard-coded), and split
into two families that feed the **same** map → tag → draft pipeline:

| Family | Sources | What it does |
|---|---|---|
| **catalog** | OpenBeta (live) · theCrag · UKC · Mountain Project | walk a structured area→crag→route tree |
| **discovery** | SerpAPI-social | find climbs *not yet catalogued* — trad lines posted to Instagram/Reddit/YouTube, queried per region/crag over a recent window → draft candidates |

```
  seed ─► frontier ─► fetch (per-source) ─► map (mechanical) ─► tag (LLM) ─► draft ─► Studio
          (queue)     sources/<id>.py       map.py             tag.py       store.py  curate.py
```

- **fetch** — `sources/<id>.py`, the only source-specific code. Area rows discover
  children (enqueued back into the frontier) and routes.
- **map** — [`map.py`](map.py): the mechanical fields that copy cleanly (name, grade,
  length, pitches, discipline) + the **multi-pitch trad/alpine filter**. Raw captures go
  to `ingest/.cache/` (gitignored) — **never** inside `corpus/record/` (that's what
  crashed the store loader with UKC's scratch files).
- **tag** — [`tag.py`](tag.py): one Claude call infers the prose-only fields
  (protection, hazards+evidence, character, feature, incline), validated against the
  taxonomy enums read from `corpus/record/taxonomies.json`. Off-vocabulary → repair or
  flag for review, never surfaced.
- **draft** — `store.save_route()` validates against the taxonomy schema and writes a
  `status: draft`, `tagged_by: source|llm` record the Studio queue picks up.

## Run

```
python ingest/worker.py --source openbeta --dry-run     # fetch + map + tag, validate, print — writes nothing
python ingest/worker.py --source openbeta               # …and land drafts in the record
python ingest/worker.py --source openbeta --seed "Yosemite" --country USA   # enqueue a start area by name
```

`--dry-run` is the safe default while we settle the landing policy (see below): it proves
the whole vertical against the live API without mutating the curated corpus.

## Open design decision (needs Michel)

Routes must reference an area that exists in `corpus/record/areas.json`, but **areas have
no `draft`/`status` gate — only routes do.** So ingesting a fresh region means either (a)
injecting its unverified area subtree straight into the curated tree (product-visible in
the planner), or (b) a draft-area holding pen. Until decided, the worker runs `--dry-run`
and does not write areas. This is the one thing standing between the verified pipeline and
committing real drafts.

## Status

- ✅ `frontier.py` — JSON-native, verified (enqueue/dedup/claim/complete/fail/resume).
- ✅ `sources.json`, this README, store-loader hardening.
- ✅ `sources/openbeta.py` + `map.py` + `tag.py` + `worker.py` + `drafts.py` — the vertical, verified live (Yosemite → validated drafts; `--tag` inference confirmed).
- ✅ `sources/thecrag.py` + `sources/ukc.py` — verified live (Fair Head: theCrag route + UKC 460 routes → 102 multipitch-trad kept).
- 🔜 SerpAPI-social discovery source; a "force re-survey" flag (re-crawl a done URL).
- 🎨 `map-mockup.html` — design mockup of the **ingestion survey map**: a real terrain map (Leaflet + OpenTopoMap, with satellite/streets/dark layers), mouse-wheel zoom. Draw a region → crawl+tag → amber (ingested) → curate crags → green, route pins on zoom, hand-add guidebook finds; deduped by the unique key. Open in a browser (needs internet for map tiles): `open ingest/map-mockup.html`. Not an Artifact — the shareable sandbox blocks external map tiles.

Replaces the retired Postgres crawler (`corpus/tools/crawl_worker.py`,
`route_mapping.py`, `llm_tag.py`, `seed_openbeta_frontier.py`) — those get removed with
the rest of Postgres.

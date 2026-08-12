# ingest — bbox scrape CLI

Scrape every crag + route inside a lat/lng bounding box from one or more
sources, into one shared schema. A CLI today; each verb is designed to become
a REST endpoint on a future ingest web API. Designed 2026-08-11 (grilled
decision session); supersedes the frontier-worker module from PR #1, whose
proven source adapters were harvested into `sources/`.

```
python -m ingest start  --bbox 55.20,-6.20,55.25,-6.10 --source ukc,thecrag \
                        [--max-pages N] [--max-crags N] [--root URL] [--follow]
python -m ingest status <run-id>
python -m ingest result <run-id> [--source X]   # combined JSON to stdout
python -m ingest resume <run-id> [--follow]
python -m ingest list
```

Run with `agent/.venv/bin/python` from the repo root (needs bs4 + playwright).

Live-verified 2026-08-11: ukc Fair Head bbox → 5 crags / 1,032 routes (~45 s);
openbeta Smith Rock bbox → 106 crags discovered, capped runs + resume with
raised caps; thecrag NI walk → bbox pruning + leaf point-check (see below).

## Chatter + link (separate output type, same run machinery)

```
python -m ingest chatter --crag "Fair Head" [--crag ...] [--from-run <scrape-run-id>] \
                         [--window w2] [--num 20] [--force]
python -m ingest link <chatter-run-id> [--against <scrape-run-id>,<scrape-run-id>]
```

`chatter` runs the July-2026 winning SerpAPI query per seed crag and writes
schema-validated mention docs (title/url/site/snippet/ISO date — all verbatim
mechanical fields, see `chatter.py`) to `parsed/chatter.json`, raw responses
kept. The key is shared with the flight monitor: quota is checked first and a
reserve is refused past (`--force` to override). `link` then mechanically
matches docs against every crag name in the corpus record + the given scrape
runs (word-boundary text match), and classifies each seed: `in-corpus` /
`scraped-only` / `not-ingested` — the last list is the "go scrape a bbox
around this" queue. Which crag an ambiguous post REALLY means is judgment →
the LLM phase, like entity merge.

## The contract

- **Output = crag/route inventory only.** Chatter/mention sources (SerpAPI
  etc.) are a different tool. Same **schema** per source, not same entities —
  `parsed/ukc.json` and `parsed/thecrag.json` sit side by side; cross-source
  entity merging is the phase-2 LLM job's responsibility, never this module's.
- **Grades are native + system tag** (`{"value": "E1 5b", "system":
  "uk_adjectival_tech"}`) — verbatim, lossless, zero conversion tables.
- **Jobs, not calls.** `start` detaches a worker (`--follow` to block); all
  state lives in the run directory, saved after every item, so a killed run
  resumes with at most one fetch lost. The scrape is fully mechanical — no
  LLM anywhere; caps are simple testing knobs and capped output says so
  (`capped` field — never a silent truncation).
- **Raw stays private.** Every fetched payload is stored verbatim under
  `runs/<id>/raw/` (git-ignored). theCrag/UKC scraping is with Michel's
  explicit permission conditional on raw never reaching the public site;
  syncing raw/ to the private store is a separate explicit step.

## Run directory (`runs/<run-id>/`)

```
manifest.json        params + per-source status  (the future API's run object)
state.json           per-source frontier (pending items / done keys) — resume contract
raw/<source>/*.json  verbatim payloads, one per fetched item
parsed/<source>.json shared-schema inventory + counts + capped
log.txt              worker log
```

## Sources (`sources/`)

Adapter contract (see `sources/__init__.py`): `plan(bbox) -> frontier`,
`fetch(item) -> payload`, `parse(item, payload, bbox) -> {crags, next}`.

| source   | discovery (verified live 2026-08-11)                          | notes |
|----------|---------------------------------------------------------------|-------|
| openbeta | `cragsNear` GraphQL (center + covering radius, trim to box)   | keyless; API answers slowly (~45s) some days — adapter posts with 90s timeout + retries |
| ukc      | their own map API `api.ukclimbing.com/.../crag_search/?location=lat,lng&distance=km` — browser *navigation* clears Cloudflare (plain HTTP and page-JS fetch both fail) | richest prose; crag pages via `corpus/tools/ukc_client.py` |
| thecrag  | area-tree walk with bbox pruning — every area page embeds its own `bbox: [[..],[..]]`, subtrees that miss the query box are dropped unfetched | no open geo endpoint (endpoint guessing gets Cloudflare-blocked — don't). Walk root: `--root URL`, else Nominatim country -> `ROOTS` table. NB URL slugs lie about hierarchy (Fair Head = `/ireland/fair-head` but breadcrumb UK > Northern Ireland) — trust children lists, not URL prefixes |

## Known limits (v1, deliberate)

- Recall on tree/geo sources depends on the source's own coordinate quality;
  UKC/OpenBeta circle queries are trimmed to the box mechanically.
- theCrag walk cost scales with the root: a country root spends one fetch per
  child area to learn its bbox before pruning. Pass the tightest root you know.
- Some theCrag areas are login-gated ("Login to join in", e.g. Marconi's Cove
  NI) — anonymous scraping sees an empty page; those areas yield nothing.
- No merging, no LLM tagging, no promotion into the corpus record here —
  phase 2 consumes `parsed/` + `raw/` from the run directory.

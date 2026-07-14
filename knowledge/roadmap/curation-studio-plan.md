# Curation Studio — the fast UI for reviewing the corpus

> **Purpose:** the [governance rule (#32)](../data/governance.md) says only curated rows
> (`status:publish + taggedBy:human`) may feed suggestions/ranking — which makes **curation
> throughput** the bottleneck: 50 draft routes today, 176 crawled Fair Head routes already
> in Postgres behind them, hundreds more as the crawler scales. The Corpus Inspector is
> read-only; this is the plan for the tool that *writes*.
> **Status:** ✅ **Built** (2026-07-13, decision [#34](decisions.md)) — **Postgres-first**,
> per Michel ("no merge, let's do Postgres-first"). Run it:
> `agent/.venv/bin/python db/tools/curate.py` → **http://localhost:8890** (needs
> `colima start` + the climbing-db container). The mockup that seeded the design stays at
> `prototypes/curation-studio.html` (local-only).

## Requirements (Michel, 2026-07-13)

- **Localhost web admin** — same pattern as the #33 trips admin: a FastAPI page on this
  Mac that reads and writes `db/corpus.json` directly. No auth, no deploy, instant saves.
- **Queue-first, grid-second** — an inbox that clears one draft at a time with keyboard
  shortcuts, plus a spreadsheet view for bulk column edits (e.g. set `bestSeason` for a
  whole crag). Same data, two views.
- **AI first, human after** — everything arrives prefilled (scrape + LLM tags); the human
  verifies, fixes what's wrong, fills the gaps. Publishing accepts the remaining
  suggestions; per-tag receipts make accepting a one-line read, not a re-read of the prose.
- **All the evidence on screen** — source pages + scraped prose, AI tag receipts, a map
  pin (coords are the known failure mode), photos/topo where a source has them.
- **Field check is a first-class state** — most climbs can be verified from books, guides
  and blogs; some need a human to physically go, take photos, maybe climb it. The curator
  decides that per-route: flag 🥾 *needs field check* + a curator note that travels with
  the row (e.g. "abseil in and photograph pitch 2"). A flagged row stays uncurated until
  someone goes.

## What "curating a route" concretely is

From diffing the 8 curated vs 50 draft rows:

1. **Verify scraped facts** — grade, length, pitches, incline, coords (the map pin).
2. **Review AI tags** — features / character / protection are `taggedBy: llm` on every
   draft; accept, drop, or add per chip.
3. **Fill the 6 missing fields** — `stars`, `bestSeason`, `sunWindow`, `elevation`,
   `protectionStyle`, `belays` (drafts never have them).
4. **Decide the row's fate** — `publish` (flips `taggedBy → human`) · keep `draft` ·
   flag 🥾 field check · `quarantined` (wrong/duplicate; kept so the seeder never
   re-imports it).

Target: **~15–30 s per route** when the sources agree; the queue defers anything slow.

## Build plan — as shipped (Postgres-first, #34)

| # | Piece | Status |
|---|---|---|
| M1 | `db/tools/curate.py` — FastAPI on **Postgres** (localhost:8890): `GET /api/queue`, `PATCH /api/route/{id}` (autosave), `PUT …/pitches`, `POST …/publish` / `status/quarantined` / `fieldcheck`, `POST /api/export` (regenerates corpus.json) | ✅ |
| M2 | Queue UI (`curate_ui.html`): facts grid (missing = amber), tag chips per family (click to drop, dropdown to add), stars/season/sunWindow/belays widgets, **intro + approach + structured pitch-by-pitch editors**, curator note, evidence rail (source links, AI receipt, OSM map pin, climatology). Keyboard: `⌘⏎` publish · `⌘F` field check · `⌘→/←` navigate | ✅ |
| M3 | Grid view: full table, multi-select, bulk-set one column (never bulk-publish) | ✅ |
| M4 | Receipts (ai_tag v2): per-tag justifying sentence stored as `evidence`; until re-run, the receipt shows the cached tag set + model + date | 🔜 |
| M5 | Schema: `db/sql/025_curation.sql` — `tagged_by`/`tag_prov`/`curation_notes`/`needs_field_check`/`curated_at` + **DB CHECK: publish ⇒ human-tagged** (#32 at the database) | ✅ |
| M6 | Postgres-first plumbing: `ingest_corpus.py` (corpus.json → PG restore/seed, human rows never overwritten; prose joined from the local multi-pitch site source, pitchInfo parsed to `pitch` rows) + `build_corpus.py` rewritten as pure PG → corpus.json exporter. Round-trip verified idempotent | ✅ |

**Taxonomy is editable in the studio too (#35):** the third tab manages every
vocabulary — add a value (its one-line meaning is required because the AI tagger reads
it), edit meanings inline, delete only when no route uses it. Writes hit Postgres, then
auto-regenerate `105_taxonomy_extensions.sql` + `knowledge/data/taxonomy-values.json`,
and `ai_tag.py` picks the new values up live. Grades are validated per-system (pick the
scale — shown with its full name and region, suggested from the route's country +
discipline, e.g. UK trad → BAS "VS 4c · HVS 5a · E1 5b" — and the value must match it;
publish is blocked otherwise). Routes carry **multiple named parking pins**
(`route_parking`, 028): the rail shows a live OSM map — click to drop a pin, drag to
adjust, label each ("main car park", "layby", "high-tide option").

**⚠ Operational note:** `db/apply.sh` drops the whole schema. The restore path is
`./apply.sh && agent/.venv/bin/python db/tools/ingest_corpus.py` — corpus.json IS the
backup, so **export (the ⇩ button) after every curation session and commit the diff**.

**Not building:** auth (single editor, localhost), photo hosting (link out to source
pages; local snapshots live in the gitignored `db/.raw_cache/`), mobile (the sheet/grid
answer for away-from-desk is "flag it 🥾 and note it").

## What a curated multi-pitch trad entry contains — cross-platform survey (2026-07-13)

Surveyed live: multi-pitch.com (Sammy Higgins, Aristotles — the reference standard),
UKC logbook (Cemetery Gates), Mountain Project (High Exposure), theCrag (Centurion),
and Rockfax's "How to Write a MiniGUIDE". Convergent findings:

- **The pitch atom is universal:** number + per-pitch grade + per-pitch length + prose
  ending with **belay location/quality** (Rockfax canonical: `1) 6a+, 20m. Climb the
  slabby wall…`). The Studio's structured pitch editor matches this exactly.
- **"Curated" visibly means accountable editorship:** named authors/moderators (UKC's
  "checked by volunteers X and Y"), verification states, a correction channel — not just
  good prose. Our equivalents: `taggedBy:human`, `curatedAt`, `curationNotes`, git diffs.
- **Crag-level facts should be inherited, not repeated** (access, tides, drying, sector
  layout) — UKC/Rockfax do this; multi-pitch.com currently flattens it into each route.
  Our area tree + `route_resolved` inheritance already models the right shape.

**The superset checklist** (ordered; ✅ = multi-pitch.com already has it): identity+stats ✅ ·
**stars ❌** · intro/character prose ✅ · pitch-by-pitch ✅ (best-in-class topo) · descent ✅
**+ escapes ❌** · approach w/ parking GPS ✅ · protection notes ✅ (**structured rack ❌,
G/PG13/R/X seriousness ❌**) · conditions/seasonality ⚠ (charts yes, editorial "seeps after
rain, sun from 2pm" statement ❌) · **access notes + verified date ❌** · **FA/history ❌** ·
community/verification signals ❌ · character tags ❌. The bold gaps are what curation in
the Studio should add beyond copying the site — stars, rack, seriousness, character tags
and descent/escape notes all have DB columns already; FA has a `first_ascent` table;
access has `area.access_notes`.

## Open questions

- Does the 🥾 flag deserve its own queue view ("field trips to plan") grouped by area, so
  a Belfast weekend can clear all of Fair Head's flags at once? (Cheap: it's a filter.)
- Should publishing require the map pin to have been *looked at* (one hover) — the
  cheapest guard against the gazetteer-coords failure mode?

See also: [data governance](../data/governance.md) · [source of truth](../data/source-of-truth.md) ·
[Data map](../data-dependencies.md) · decisions [#27/#32/#33/#34](decisions.md).

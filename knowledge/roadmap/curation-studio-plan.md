# Curation Studio — the fast UI for reviewing the corpus

> **Purpose:** the [governance rule (#32)](../data/governance.md) says only curated rows
> (`status:publish + taggedBy:human`) may feed suggestions/ranking — which makes **curation
> throughput** the bottleneck: 50 draft routes today, 176 crawled Fair Head routes already
> in Postgres behind them, hundreds more as the crawler scales. The Corpus Inspector is
> read-only; this is the plan for the tool that *writes*.
> **Status:** 🔜 Mockup built — `prototypes/curation-studio.html` (local-only, like all
> prototypes — open it in a browser; it's keyboard-clickable). Requirements confirmed with
> Michel 2026-07-13.

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

## Build plan

| # | Piece | Detail |
|---|---|---|
| M1 | `db/tools/curate.py` | FastAPI, localhost only. `GET /queue` (drafts, filterable by crag/country), `PATCH /route/{id}` (field edits, autosaved), `POST /route/{id}/publish\|quarantine\|fieldcheck`. Writes `db/corpus.json` + the served `knowledge/data/corpus.json` atomically; git diff is the audit trail. |
| M2 | Queue UI | The mockup's left card + evidence rail, served by M1. Keyboard: `⏎` publish · `e` edit · `f` field check · `x` quarantine · `s`/`j`/`k` navigate. |
| M3 | Grid UI | Same API, table view; multi-select + bulk PATCH of one column (never bulk-publish — status flips stay per-route). |
| M4 | Receipts (ai_tag v2) | `ai_tag.py` additionally stores, per tag, the prose sentence that justified it (`evidence`). Re-tagging the existing 50 is one cached re-run. Until then the receipt shows tag + model + date only. |
| M5 | Schema additions | `status: quarantined` (already designed in #27), `curation: {notes, needsFieldCheck, curatedAt}` on routes. `build_corpus.py` preserves these fields across rebuilds (like it already protects human tags). |
| M6 | Postgres sync | Out of scope here — publishing writes corpus.json; the corpus→Postgres seed is the existing #27 pending step. |

**Not building:** auth (single editor, localhost), photo hosting (link out to source
pages; local snapshots live in the gitignored `db/.raw_cache/`), mobile (the sheet/grid
answer for away-from-desk is "flag it 🥾 and note it").

## Open questions

- Does the 🥾 flag deserve its own queue view ("field trips to plan") grouped by area, so
  a Belfast weekend can clear all of Fair Head's flags at once? (Cheap: it's a filter.)
- Should publishing require the map pin to have been *looked at* (one hover) — the
  cheapest guard against the gazetteer-coords failure mode?

See also: [data governance](../data/governance.md) · [source of truth](../data/source-of-truth.md) ·
[Data map](../data-dependencies.md) · decisions [#27/#32/#33](decisions.md).

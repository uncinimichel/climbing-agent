# Phase 3 — The Curated Filter (Human Taste)

> **Purpose:** the quality moat. AI and scrapers produce volume; curation produces
> *worth*. Every recommendation passes through a verified master index of classic
> sectors, so the engine only ever surfaces climbs that matter.
> **Status:** ⚠️ Partial — curation is real but **manual**; automated mapping is planned.

## Vision

- **Zero-Garbage UGC.** The platform actively **rejects** the messy, unverified
  user-generated content of legacy sites. No star-spam, no unvetted trip reports leaking
  into recommendations.
- **The Standard of Taste.** A carefully managed **master index** — a verified directory
  of classic sectors. Automated data flows (Phase 1→2) are mapped *exclusively* onto
  entries in this index. If a scraped climb doesn't map to a curated sector, it doesn't
  surface. Full stop.

This is the deliberate inversion of aggregator logic: **more data is not the goal;
better-filtered data is.** The master index is the competitive advantage.

## What exists today ⚠️

The "master index" is **hand-curated config**, not an automated pipeline:

- **`venues.json`** — 9 candidate venues, each with name, country, `priority`, lat/lon,
  rock, style, rationale, and per-traveller travel. This *is* the curated allow-list: the
  engine ranks only these.
- **`climbing-trips.csv`** — a ~40-venue shortlist with per-month weather columns and
  travel/logistics notes; the research pool venues are promoted from.
- **`dolomites-trip.csv`** — scoped routes for the backup venue.

Curation today = Michel's judgement, encoded by editing these files. That's genuine
"human taste" — just not yet *scaled*.

## What's missing ⛔ (planned)

- A **verified sector directory** larger than a single trip's shortlist, with stable IDs.
- **Automated mapping**: scraped/parsed climbs (Phase 2) join onto master-index sectors
  by geo + name match, with anything unmatched quarantined rather than surfaced.
- A **curation workflow/UI** to promote, demote, merge, and verify sectors — turning the
  editorial act into a repeatable process instead of a JSON edit.
- **Provenance & verification state** per sector (who vetted it, when, source).

## Design principles

1. **Allow-list, not block-list.** Nothing surfaces unless it maps to a *verified* entry.
   Default-deny is what keeps garbage out.
2. **Config over code.** The index is data (`venues.json` today), edited independently of
   the engine. Adding/removing a venue is a config change.
3. **Traceable taste.** Every entry should carry *why* it's included (the `why` field
   today) — curation decisions are explained, not silent.
4. **Priority is editorial.** `priority` encodes human preference (NI first for logistics)
   and is the tie-breaker when weather scores are equal.

## Interfaces

- **Input:** Phase-2 validated records (climbs, conditions) seeking a home in the index.
- **Output:** the curated, ranked venue/sector set handed to Phase-4 for rendering.
- **Human-in-the-loop:** the curation edits themselves (today: PRs editing `venues.json`).

## When building here

- Grow the index in `venues.json` / a future sector directory — keep `lat`/`lon`,
  `priority`, `rock`, `style`, and a `why`. See [`data/schemas.md`](../data/schemas.md).
- When you add automated mapping, **quarantine unmatched climbs** — never auto-surface
  them. Surfacing unvetted content violates the core principle.
- Record notable curation policy calls in [`roadmap/decisions.md`](../roadmap/decisions.md).

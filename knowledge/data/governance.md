# Data governance — curated vs everything else

> **Purpose:** make it possible to tell **at a glance** which climb/venue data a human has
> verified and which is machine-scraped or AI-inferred — and enforce one hard rule:
> **suggestions and ranking read curated, human-tagged data only.**
> **Status:** ✅ Decided — [#32](../roadmap/decisions.md). Provenance fields live in
> `corpus.json` today; the trip-pipeline enforcement is pending (see the scoreboard below).

## The one rule

> Any feature that **recommends** — the agent's route suggestions, the dashboard's venue
> ranking, "best of" lists — may only use rows where **`status: publish`** AND
> **`taggedBy: human`**. Everything else exists to be *reviewed*, not to be *served*.

Live **environmental** data (weather, flights, stays) is exempt: it can't be human-curated
by nature. It may feed scoring as *conditions*, but must always be provenance-labelled in
the UI (the [#31](../roadmap/decisions.md) weather chips are the precedent) — and it must
never be treated as a **climb fact**.

## The trust tiers

Every area/route in [`corpus.json`](corpus.json) carries three provenance fields:
`status` (publish/draft), `source` (where the row came from), `taggedBy` (who tagged it).
That makes the tiers a **query, not a judgment call**:

| Tier | Filter | What it means | May feed suggestions/ranking? |
|---|---|---|---|
| **Curated** | `status:publish` + `taggedBy:human` | A human verified the facts *and* the tags | ✅ **Yes — the only tier that may** |
| **Seeded** | `status:draft`, `source:multi-pitch.com` / `sheet-gazetteer` | Scraped/imported, unreviewed | ❌ Review queue only |
| **AI-tagged** | `taggedBy:llm` (+ `tagProv: {model, date}`) | Tags inferred from prose by Claude (`db/tools/ai_tag.py`) | ❌ Never counts as curated, even on a publish row |
| **External live** | Open-Meteo · OSM · flight APIs | Environmental conditions, refetched daily | ⚠️ As *conditions* only, provenance-labelled |

Current corpus counts (`counts` block in `corpus.json`, 2026-07-13): **23/182 areas** and
**8/226 routes** are curated; 50 seeded routes are `taggedBy: llm`, the 168 crawled Fair
Head routes are `taggedBy: source`. Since decision [#34](../roadmap/decisions.md) the rule
is also a **database constraint**: `route_publish_needs_human_tags` — Postgres physically
refuses a publish row that isn't human-tagged.

## Promotion: how draft becomes curated

Use the **Curation Studio** (`agent/.venv/bin/python db/tools/curate.py` →
localhost:8890 — see the [plan/manual](../roadmap/curation-studio-plan.md)):

1. The queue serves drafts one at a time with the evidence alongside (sources, AI
   receipt, map pin, prose).
2. Verify the facts, accept/fix the tags, fill the gaps (stars, season, sun window,
   protection style, belays), and write/polish the **intro, approach and pitch-by-pitch**
   prose — the curated product is the prose, not just the fields.
3. **Publish** — the Studio flips `status → publish` and `taggedBy → human` atomically
   (Postgres constraint `route_publish_needs_human_tags` makes any other combination
   impossible). Not verifiable from the desk? Flag 🥾 **needs field check** with a note.
4. **⇩ Export** writes `db/corpus.json` from Postgres — commit the diff; that's the audit
   trail and the backup.

`ingest_corpus.py` protects the other direction automatically: a re-ingest **never
overwrites** a `taggedBy: human` row.

## Enforcement scoreboard (today)

| Consumer | Reads | Curated-only? |
|---|---|---|
| Agent search (`agent/search.py`) | Postgres | ✅ Hard-wired `WHERE r.status = 'publish'` |
| **Postgres itself** | — | ✅ CHECK constraint: a publish row must be `tagged_by = 'human'` (#34) |
| Curation Studio (`db/tools/curate.py`) | Postgres (writes) | ✅ The promotion tool — publish flips `taggedBy → human` atomically |
| corpus.json exporter (`db/tools/build_corpus.py`) | Postgres | ✅ Carries `status`/`source`/`taggedBy`/`tagProv`/`curationNotes` on every row |
| Corpus Inspector | corpus.json snapshot | ⚠️ Shows publish/draft; should also badge `taggedBy: llm` tags |
| **Dashboard ranking** (`engine/scoring.py`) | sheet + venues.json + **raw multi-pitch.com** | ❌ **Violation** — the *Coverage* sub-score counts uncurated multi-pitch.com routes (`scoring.py`, `routes_s`), and the tidal flag comes from the same feed |
| Trip pipeline (`update_report.py`) | old five sources, not corpus.json | ❌ Pre-#27 wiring — the pending refactor |

**Pending (trip-planner process, out of this doc's lane):** when `update_report.py` /
`scoring.py` switch to `corpus.json` (#27's 🔜 step), the Coverage sub-score and tidal
flag must filter to curated rows — or be explicitly relabelled in the UI as
"uncurated coverage signal" if we decide to keep them as a soft hint.

## Where each judgment lives (quick reference)

- **Human judgments** — Postgres publish rows, `venues.json`, the sheet's judgment columns
  (volume/difficulty/cost). All curated by definition; the sheet becomes a derived export
  under #27.
- **Machine facts** — multi-pitch.com scrape (`db/mp-climbs.json`), GAZETTEER coords.
  Draft until promoted.
- **Machine inferences** — `db/enrichment-cache.json` (LLM tags, keyed by route, with
  `_prov`). Merged into corpus as `taggedBy: llm`.
- **Environmental** — `climo-cache.json`, `venue-env.json`, flights/stays caches. Never
  climb facts; provenance-labelled per #31.

See also: [source-of-truth](source-of-truth.md) (why one corpus), the
[Data map](../data-dependencies.md) (visual wiring), [decisions #27/#31/#32](../roadmap/decisions.md).

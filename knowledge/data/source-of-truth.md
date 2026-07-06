# Where the source of truth lives — and the plan to make it *one* place

> **Purpose:** kill the recurring "wait, where do I add a climb?" confusion. Names every
> place climb/venue truth lives **today**, then proposes collapsing them into **one authored
> corpus** that is the seed/export for the Postgres DB — reconciling decisions
> [#15](../roadmap/decisions.md), [#18](../roadmap/decisions.md) and
> [#25](../roadmap/decisions.md).
> **Status:** ⚠️ **Decided — [#27](../roadmap/decisions.md), option 1.** The one authored
> `db/corpus.json` + its builder land now (seeded from multi-pitch); rewiring the trip
> pipeline to *read* it, and Postgres ingestion, are follow-ups. This **supersedes #15**
> (sheet-as-master → derived export).

## The problem, stated plainly

"Climb/venue truth" is currently spread across **five** places, and three of them
independently answer *"where is this crag?"*. Nothing links World A (the corpus DB) to
World B (the trip dashboard) — see [`../architecture/data-flow.md`](../architecture/data-flow.md).

## Today — the five sources (✅ = real)

| # | Source | Grain | Owns (authoritative for) | Authored |
|---|---|---|---|---|
| 1 | ✅ `db/dev/sample_routes.sql` | route | The only route **rows** in Postgres (+ hand-typed `route_climatology`) | hand SQL, dev fixtures |
| 2 | ✅ `trip-ni-july-2026/venues.json` | venue/crag | **Curated** coords · per-person travel/airport · priority · rock · "why" | hand JSON |
| 3 | ✅ `engine/sheet_venues.py` `GAZETTEER` | venue/crag | Coords + airports for **~30 sheet areas not in `venues.json`** | hand Python dict |
| 4 | ✅ `climbing-trips.csv` (Google Sheet) | venue/crag | The **master candidate list** + judgment columns (volume, difficulty, cost, min-trip, monthly weather) — **no coords** | Google Sheet, exported each CI run |
| 5 | ✅ `multi-pitch.com/data/data.json` | route | **Live** external route DB (S3-backed): grades, pitches, geoLocation, hazard flags. **The schema our DB copies** | external, read live |

**What's already decided about these:**
- **[#15](../roadmap/decisions.md)** — the **sheet (4) is the venue master list**; `venues.json` (2)
  is the curated overlay; `GAZETTEER` (3)/geocoder fill coords for sheet rows without a
  curated entry. So *"venues.json vs the sheet"* = **curated detail vs broad master list**, not
  two rivals.
- **[#11](../roadmap/decisions.md)** — we adopted **multi-pitch.com's data model (5)** as the
  tagging target; the DB `route` schema ([`route-schema.md`](route-schema.md)) mirrors it.
- **[#18](../roadmap/decisions.md)** — **Postgres is the corpus DB and *eventually the only
  source of truth***; `venues.json`/`extra-climbing.json` migrate in and become **exports**.
- **[#25](../roadmap/decisions.md)** — **`tag-spec.json` is the single source of truth for the
  taxonomy** (families, colours, tooltips); *"a venue value is a rollup of its climbs."*

### Why it *feels* like chaos
Coordinates + travel for a crag can live in **(2) or (3) or a geocode** — there is no single
authoritative answer to "where is this crag and how do we get there." `GAZETTEER` (3) exists
**only** because the sheet has no coords and `venues.json` only covers curated entries. That
split is the wart.

## Target — one authored corpus, shaped as the DB seed

One file, everything in it, no coordinate fallbacks. It is **not a rival to Postgres (#18)** —
it is the **human-authored seed/export** the DB loads from. Same schema, two homes over time:
**JSON now → Postgres when scale demands it.** This is the natural *now-form* of #18, and it
collapses sources 1–3 into one place.

```jsonc
// corpus.json  — the authored source of truth (loads into Postgres; is the export shape)
{
  "schemaVersion": "1.0",
  // Taxonomy DEFINITIONS are NOT duplicated here — they stay in tag-spec.json (#25).
  // Entities carry taxonomy VALUES (tags); the dictionary is referenced once.
  "taxonomyRef": "knowledge/data/tag-spec.json",

  "areas": [                                   // crag/region/sector tree (shared facts)
    { "id": "gb-assynt-stoer", "kind": "crag", "parent": "gb-assynt",
      "name": "Old Man of Stoer", "lat": 58.258, "lon": -5.361,
      "rock": "sandstone", "aspect": "SE", "gradeContext": "GB",
      "status": "publish", "dataGrade": 5 }    // curated flag = status + confidence (#18)
  ],

  "routes": [                                  // climbs hang off an area; inherit its facts
    { "id": 5, "area": "gb-assynt-stoer", "name": "Original Route",
      "status": "publish", "dataGrade": 5,     // status:draft = uncurated/auto-imported
      "originalGrade": "VS 5a", "gradeSystem": "BAS", "tradGrade": "VS", "techGrade": "5a",
      "length": 67, "pitches": 5, "incline": "Vertical", "protection": "PG",
      "disciplines": ["trad","multi-pitch"], "features": ["face","crack"],   // VALUES, inline
      "character": ["sustained","exposed"], "hazards": ["tidal","abseil"],
      "climatology": [ { "month": 7, "tempHigh": 16, "tempLow": 11, "rainyDays": 13 } ] }
  ]
}
```

### Four rules this encodes

1. **Curated vs uncurated is a *field*, not a *file*.** Reuse the DB's existing model (#18):
   `status` ∈ `publish | draft | quarantined` + `dataGrade` 1–7. *Curated list* = a filter
   (`status=publish`), *uncurated* = `status=draft` (a sheet row or scrape not yet verified).
   Never a second file. This is exactly the Phase-3 "allow-list, default-deny" of
   [`../roadmap/ingestion-plan.md`](../roadmap/ingestion-plan.md).

2. **Taxonomy: values inline, definitions referenced.** Each entity carries its *tags*
   (`disciplines`, `features`, `hazards`…). The *dictionary* of allowed values + their meaning
   (which rock seeps, which hazards are safety-critical, the grade ladder) stays in
   `tag-spec.json`/[`taxonomy.md`](taxonomy.md) — the single authority per **#25**. Embedding
   the dictionary in every climb would duplicate it thousands of times and let it drift.
   *This is what "put the taxonomy in the JSON" should mean.*

3. **Areas vs routes are distinct grains; a venue is a rollup.** An `area` carries shared
   facts (coords, rock, aspect, gradeContext) that routes **inherit** — so you don't repeat
   "granite, faces SE" on every line. A venue-card value is a **rollup of its routes** (#25).
   Matches the DB's `area`→`route` inheritance ([`database.md`](database.md)).

4. **A trip is a *derived selection*, not a copy.** The corpus holds stable **facts**; a trip
   is a short list of references + this-trip overlay. This finally splits the two things
   `venues.json` conflates today (crag facts **vs** who-flies-where-and-priority):

   ```jsonc
   // trip-ni-july-2026/trip.json — "other lists that make up trips"
   { "trip": "~24 July 2026 — Michel & Dan", "window": { "start": "2026-07-22", "end": "2026-07-27" },
     "venues": [
       { "ref": "ni-fairhead", "priority": 1,
         "travel": { "michel": { "mode": "fly", "to": "BFS" }, "dan": { "mode": "local" } } }
     ] }
   ```

### What collapses

| Was | Becomes |
|---|---|
| `sample_routes.sql` route rows | `corpus.json` `routes[]` (loaded into PG) |
| `venues.json` crag facts (coords/rock/aspect) | `corpus.json` `areas[]` |
| `venues.json` priority + travel | `trip.json` overlay |
| `GAZETTEER` (~30 areas) | `corpus.json` `areas[]` with `status: "draft"` — **deleted from code** |
| geocoder fallback | one-off authoring aid when *adding* an area; never a runtime source |

**`GAZETTEER` dies** because every area — curated or not — is now a row with coords. No
fallbacks; one file answers "where is this crag."

## How this maps to the roadmap (all the world's climbs)

The world's corpus is 30–150k routes ([`ingestion-plan.md`](../roadmap/ingestion-plan.md) —
*not* millions, bounded to multi-pitch), which outgrows a hand-edited file. That's fine and
already planned:

- **Now:** `corpus.json` is small and hand-authored — the curated seed.
- **Later (Stage 5 / M2):** ingestion writes `status: draft` routes straight into Postgres;
  Michel promotes to `publish`. The JSON becomes a **generated export** of the curated slice.
- The schema **never changes** — that's why shaping `corpus.json` like the `route`/`area`
  tables now (multi-pitch field names, #11) makes it a drop-in seed, not a dead end.
- **Bonus:** a shared corpus is what finally **connects World A and World B** — dashboard and
  agent read one source instead of five.

## Adding data, under the target model

- **New climb** → add a `routes[]` entry to `corpus.json` (`status: draft` until you've
  checked it). Reload into PG.
- **New crag** → add an `areas[]` entry (coords live here now — no GAZETTEER).
- **Plan a trip** → add refs + travel to a `trip.json`; never copy crag facts.
- **New vocabulary** → extend [`taxonomy.md`](taxonomy.md) + `tag-spec.json` first (#25), then
  use the value — off-dictionary values are rejected by design (#18 FK/enums).

## Decided — [#27](../roadmap/decisions.md)

**Option 1: `corpus.json` is the master; the sheet becomes a derived export.** This reverses
**#15** (which made the sheet the master) and is logged as **#27**. It's the only option that
delivers "one massive JSON, no fallbacks", and it's the shape **#18** wants anyway.

### What landed now vs next
- ✅ **`db/corpus.json`** — the one authored file, built by **`db/tools/build_corpus.py`**,
  seeded from multi-pitch.com (`status: draft`) + `venues.json` crags + the curated DB routes
  (`status: publish`). Re-run the builder to refresh.
- ✅ Docs + the [data-dependency map](../data-dependencies.html) (linked from the homepage).
- 🔜 **Trip pipeline reads `corpus.json`** — `update_report.py`/`sheet_venues.py` switch to it
  and **`GAZETTEER` is deleted**; `climbing-trips.csv` becomes a generated export. *(Owned by
  the trip-planner process.)*
- 🔜 **Postgres ingestion** (Stage 5 / M2) — `corpus.json` becomes a generated export of the
  curated slice; the DB is the store at scale (#18).

---
*See also: [`route-schema.md`](route-schema.md) (the field-level schema this mirrors) ·
[`database.md`](database.md) (the Postgres home) · [`external-models.md`](external-models.md)
(source schemas) · [`../roadmap/ingestion-plan.md`](../roadmap/ingestion-plan.md) (scale path) ·
decisions [#15/#18/#25](../roadmap/decisions.md).*

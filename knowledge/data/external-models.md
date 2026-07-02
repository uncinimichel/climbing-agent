# External Models — what the world's climbing databases do, and what we should steal

A review of how the major worldwide climbing platforms structure their taxonomy and data,
and a prioritised list of extensions for **our** model ([`route-schema.md`](route-schema.md),
[`taxonomy.md`](taxonomy.md)). The goal: adopt the proven ideas without importing the
"garbage UGC" our Phase-3 curation exists to reject.

> **Method:** studied the public schemas/docs of UKClimbing, theCrag, Mountain Project, and
> **OpenBeta** (whose full GraphQL schema is open source). Sources at the bottom.

## The platforms at a glance

| Platform | Scale | Model / access | Standout idea to steal |
|---|---|---|---|
| **OpenBeta** | ~200k climbs | **Open data (CC) + GraphQL API**; documented schema | A clean, hierarchical, multi-system schema we can *align to and ingest from* |
| **theCrag** | ~1M+ routes | Collaborative; public API | **Grade context** + **structured tag-sets** that *cascade down the hierarchy* |
| **UKClimbing (UKC)** | 150k routes / 14k crags | Moderated UGC | Faceted crag search by **rocktype / aspect / type**; **access notes** |
| **Mountain Project** | ~250k routes | Moderated UGC (US-centric) | **Multi-discipline route type**; grade-system **auto-detection from leading chars** |

## What each does well

### OpenBeta — the reference schema (open source)
Its GraphQL model is the cleanest blueprint available:
- **Hierarchical areas.** Every `Area` has `children[]`, `ancestors[]`, and `pathTokens[]`
  (ancestor names root→leaf). Country → region → crag → sector → route is one tree, not a
  flat list.
- **`gradeContext` inheritance.** A short country/region code (e.g. `US`, `GB`) set on an
  area and **inherited by its child climbs** — so a French `6a` and a UK `6a` are never
  confused. Grades are contextual, not global.
- **Multi-system grade object** (`GradeType`): `yds`, `french`, `uiaa`, `ewbank`, `font`,
  `vscale`, `wi` (water-ice), `brazilianCrux` — *all* conversions stored, keyed by system.
- **Composable discipline** (`ClimbType` — booleans, not an enum): `trad`, `sport`,
  `bouldering`, `deepwatersolo`, `alpine`, `snow`, `ice`, `mixed`, `aid`, `tr`. A route can
  be several at once.
- **Structured pitches** (`Pitch`): per-pitch `pitchNumber`, `grades`, `type`, `length`,
  `boltsCount`, `description` — not one prose blob.
- **Richer safety enum** (`SafetyEnum`): `PG`, `PG13`, `R`, `X`, **plus `runout` and
  `terrain`** and `UNSPECIFIED`.
- **Split content**: `description` / `location` (approach) / `protection` (gear & hazards).
- **`boltsCount`**, **`length` in metres** (`-1` = unknown), `leftRightIndex` (order along
  the crag).
- **Provenance**: `metadata.mp_id` cross-references the Mountain Project source ID.
- **Stewardship**: `Area.organizations[]` links **Local Climbing Organizations** / advocacy
  bodies (Access Fund, AAC) — the access/ethics layer.

### theCrag — the most expressive metadata model
- **Grade context** settable at *any* area level and per route (OpenBeta's idea, generalised).
- **Structured tag-sets**: tags grouped into sets (pick one-or-more per set), with an
  **`Inherits`** flag so a tag on a crag **cascades down** to its routes. Infinitely
  extensible without new columns — style, terrain features, conditions, hazards, ethics.
- **Ascent-type vocabulary** (for how a climb was done): `onsight`, `flash`, `redpoint`,
  `pinkpoint`, `lead`, `second`, `toprope`, `solo`, `aid`, `firstascent`, `firstfreeascent`…
  — **defined** in [`taxonomy.md` § Ascent style](taxonomy.md) (e.g. *onsight* = first try,
  clean, no prior beta).
- **Quality score**: a 1–100 route-quality number displayed as **0–3 stars**, blending
  *publisher* stars with *ascent-quality* ratings.

### UKClimbing — faceted discovery + access
- Crag search **facets**: `Type`, `Rocktype`, `Faces` (aspect), star rating.
- First-class **access notes**, guidebooks, rock type, aspect, `length`, star rating (`*`,
  `**`, `***`).

### Mountain Project — pragmatic parsing
- **Route Type** is a comma-separated multi-discipline string (`"Trad, Sport"`, `"Sport, TR"`).
- **Grade-system inference from leading characters**: `5.`→YDS, `V`→V-scale, `WI/AI`→ice,
  `M\d`→mixed, `A\d/C\d`→aid, `f`→French. A cheap, reliable parser heuristic.
- `Avg Stars` as a 0–4 float; `FA` free-text incl. `FFA`; trailing gear/`Fixed Hardware` notes.

## Gap analysis — us vs. them

Our model (from multi-pitch.com, see [`route-schema.md`](route-schema.md)) is strong on
*curated per-route depth* (topo, weather climatology, per-traveller logistics) but is:

| Gap | Us today | Best-in-class |
|---|---|---|
| **Area hierarchy** | flat `venues[]` | nested tree + inheritance (OpenBeta/theCrag) |
| **Grade context** | per-route `gradeSys` | inherited `gradeContext` on the area |
| **Grade storage** | one system + `dataGrade` | all systems stored (OpenBeta `GradeType`) |
| **Discipline** | `style` (trad/sport/multi-pitch) | full composable set incl. ice/mixed/aid/DWS/snow/tr |
| **Pitches** | prose `pitchInfo` | structured `Pitch[]` objects |
| **Protection detail** | `protection` grade only | + `boltsCount`, rack/gear notes, `runout`/`terrain` |
| **Quality** | `why` prose | numeric editorial **stars** (0–3) |
| **First ascent** | prose only | structured `fa {climber, year}` + `ffa` |
| **Access/ethics** | none | access notes, seasonal closures, local orgs |
| **Provenance / dedup** | `references[]` links | structured external IDs (`mp_id`, ukc_id, thecrag_id, ob_uuid) |

## Proposed extensions (prioritised)

### P0 — structural, unlocks everything else
1. **Adopt a hierarchical area model** (`region → crag → sector → route`) with `ancestors[]`
   / `pathTokens[]`, replacing flat venues. Properties (grade context, rock, aspect, access)
   **inherit downward**. This is the single biggest upgrade — mirror OpenBeta.
2. **`gradeContext` on areas, inherited by routes.** Store the context; stop guessing per route.
3. **Multi-system `grades{}` object** alongside `dataGrade`: `{yds, french, uiaa, ewbank,
   british, font, vscale, wi}`. Keep `dataGrade` as the sortable proxy; add the object for
   display in the user's preferred system.

### P1 — richer route records
4. **Composable `discipline` set** — extend `style` to the full vocab (see the extended enum
   added to [`taxonomy.md`](taxonomy.md)): `trad, sport, multi-pitch, bouldering, alpine,
   ice, mixed, aid, snow, deepwatersolo, tr, via-ferrata`.
5. **Structured `pitches[]`** — `{number, grade, type, length_m, boltsCount, description}`,
   generated from the prose `pitchInfo` (keep the prose for display).
6. **Protection detail** — add `boltsCount`, a `rack`/`gear_notes` string, and extend the
   protection enum with `runout` and `terrain`.
7. **Editorial `stars` (0–3)** — a *curated* quality rating (Phase-3 taste, **not** UGC
   votes). This is our differentiator done right: publisher stars only.
8. **Structured first ascent** — `fa {climber, year}` and `ffa {climber, year}`, parsed
   best-effort from prose (OpenBeta notes FA data is notoriously unstructured — capture what
   we can, leave the rest in `intro`).

### P2 — discovery, access & interop
9. **Access & stewardship** — `access {status, seasonalClosures[], parking, ethics,
   localOrg}`. Seasonal bird-nesting bans and tidal windows are safety/legal-relevant and tie
   into the condition engine.
10. **Structured external IDs** — `sources {ob_uuid, mp_id, ukc_id, thecrag_id}` for dedup,
    linking, and provenance (extends our `references[]`).
11. **Structured tag-sets with inheritance** (theCrag-style) — for open-ended metadata
    (features: crack/arête/chimney/slab; conditions; ethics) without schema churn.
12. **Parser heuristic** — detect `gradeContext`/system from leading characters
    (`5.`→YDS, `V`→V, `WI`→ice, `M`→mixed, `A/C`→aid, `f`→French). Add to the Phase-2 rules.

## Strategic: OpenBeta as a data source, not just a model

The biggest find. **OpenBeta is CC-licensed open climbing data with a public GraphQL API.**
Unlike scraping UKC/MP (ToS-restricted, moderated UGC), OpenBeta is *meant* to be ingested.
Two consequences:

- **Phase-1 ingestion** should treat OpenBeta as a first-class, license-clean source — far
  safer than scraping — feeding the master index by geo + name match.
- **Align our schema to OpenBeta's** (hierarchy, `gradeContext`, `GradeType`, `ClimbType`,
  `SafetyEnum`) so import/export is loss-less and we can contribute back.

Both belong on the roadmap — see [`../roadmap/roadmap.md`](../roadmap/roadmap.md) and the
decision log.

## Sources

- [OpenBeta — open climbing data](https://github.com/OpenBeta/climbing-data) ·
  [GraphQL API + schema](https://github.com/OpenBeta/openbeta-graphql) ·
  [openbeta.io/about](https://openbeta.io/about)
- [theCrag — structured tagging](https://www.thecrag.com/en/article/tagging) ·
  [grade context](https://www.thecrag.com/en/article/gradesonthecrag) ·
  [stars & quality](https://www.thecrag.com/en/article/stars) ·
  [logging ascents](https://www.thecrag.com/en/article/loggingascents)
- [UKClimbing — logbook & crag database](https://www.ukclimbing.com/logbook/help)
- [Mountain Project — features overview](https://www.mountainproject.com/help/22/overview-of-site-name-features)

*Retrieved 2026-07-02. See also [`references.md`](references.md) for the grade-system
authorities.*

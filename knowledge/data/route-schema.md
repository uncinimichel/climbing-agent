# Route Schema — the tagging target

**The canonical record for one multi-pitch route.** When Phase 1/2 finds a climb on the
web, *this* is the shape we tag it into and the set of facts we need to describe it.

> **Provenance:** learned from the mature **multi-pitch.com** project
> (`/dev/multi-pitch`) — a battle-tested data model behind ~40 fully-described routes.
> This is the real "compendium of terms" that guidebook-quality descriptions are built
> from. Controlled vocabularies live in [`taxonomy.md`](taxonomy.md); the normalized
> difficulty ladder in [`grade-conversion.md`](grade-conversion.md).

## Why this matters for the engine

The vision's **Taxonomy Engine** (Phase 2) takes messy guidebook/UKC/MountainProject
prose and must emit a clean, complete route record. This schema *is* the output contract.
Every field is either a **closed enum** (validate hard), a **number**, a **boolean flag**,
or **prose** (generated to the style rules below). A found climb is "fully tagged" when
these fields are populated with provenance.

## Field reference

### Identity & location
| Field | Type | Notes |
|---|---|---|
| `id` | int | Stable unique id. |
| `routeName` | string | The route (e.g. "Original Route"). |
| `cliff` | string | The crag / cliff / sector (e.g. "Old Man of Stoer"). |
| `country` | enum-ish | Normalize spelling (the source data had `'Spain '`, `'Jodan'` typos — clean these). |
| `county` | string | Region within country. |
| `geoLocation` | `"lat,lon"` | The geo join key (weather, nearby-climbs). |
| `timeZone` | IANA tz | e.g. `Europe/London` — for local forecast alignment. |
| `status` | `publish`\|`draft` | Curation gate — only `publish` surfaces (Zero-Garbage UGC). |

### Physical character
| Field | Type | Notes |
|---|---|---|
| `length` | int (m) | Total route length. |
| `pitches` | int | Number of pitches. |
| `rock` | enum | See [`taxonomy.md` § Rock type](taxonomy.md). Drives seepage/drying. |
| `incline` | enum | Steepness: `Slab` \| `Slab & Vertical` \| `Vertical` \| `… & Overhanging`. |
| `face` | enum | Aspect the route faces: `N NE E SE S SW W NW`. Drives sun/shade & drying. |

### Difficulty (grade — always keep the system!)
| Field | Type | Notes |
|---|---|---|
| `gradeSys` | enum | Which system: `BAS` (British Adjectival), `UIAA`, `YDS`, `ALP` (Alpine), `FS` (French Sport), `N` (Norwegian). |
| `originalGrade` | string | The raw grade verbatim (e.g. `"VS 5a"`, `"TD (f6a+)"`). Never lose this. |
| `tradGrade` | string | Adjectival part for BAS (`VD S HS VS HVS E1…`). |
| `techGrade` | string | Technical part for BAS (`4a 4b 4c 5a 5b 5c…`). |
| `dataGrade` | int 1–7 | **Normalized cross-system difficulty** for sorting/comparison. See [`grade-conversion.md`](grade-conversion.md). |

### Approach & logistics
| Field | Type | Notes |
|---|---|---|
| `approachTime` | int (min) | Walk-in time. |
| `approachDifficulty` | int 1–3 | 1 = easy walk, 3 = serious (scramble/swim/exposed). |

### Route character & hazard flags
Boolean-ish (`1` = present, `null`/absent = not). These are the tags that most change how a
route *feels and is planned* — and several feed the condition/tide logic directly.

| Flag | Meaning | Engine relevance |
|---|---|---|
| `tidal` | Access/base is tide-dependent (sea cliffs) | ⟶ needs a tide window (backlog: tides). |
| `seepage` | Route holds water / weeps after rain | ⟶ Predictive Condition Algorithm. |
| `abseil` | Requires an abseil (approach or descent) | Gear/planning. |
| `traverse` | Significant traverse (rope-management / commitment) | Planning. |
| `boat` | Reached by boat/swim | Logistics. |
| `tidal`+`boat` | Sea-stack style access | e.g. Old Man of Stoer. |
| `polished` | Rock polished (holds slick) | Difficulty-in-practice. |
| `loose` | Loose/friable rock | Safety. |
| `grassLedges` | Vegetated ledges (wet/awkward belays) | Conditions. |

### Prose content (generated to the style guide below)
| Field | Type | Notes |
|---|---|---|
| `intro` | HTML prose | The hook: setting, quality, history, geology, notable ascents. |
| `approach` | HTML prose | Contains `<strong>Approach</strong>:` and `<strong>Descent</strong>:` sections. |
| `pitchInfo` | HTML prose | Pitch-by-pitch: each `Pitch N – <length>m <grade>` then the moves. |

### Media
| Field | Type | Notes |
|---|---|---|
| `tileImage` | obj | Inspirational crag tile (600×300, ~100 KB jpg) + attribution. |
| `topo` | obj | Photo-topo `{url, alt, dataFile}` — `dataFile` 2–5 = how many responsive sizes exist. |
| `mapImg` | obj | Location map. |

### External references
| Field | Type | Notes |
|---|---|---|
| `references` | list | Prefixed links (see style rules): `{url, text}` with `Video:`/`Info:`/`Tides:`… prefix. |
| `guideBooks` | list | `{isbn, title, pg, description, rrp, imgURL, link}` — provenance to print guides. |

### Climate (per-route monthly climatology)
| Field | Type | Notes |
|---|---|---|
| `weatherData` | obj | `rainyDays[12]`, `tempH[12]`, `tempL[12]` — one value per month (Jan→Dec). A compact per-route climatology, computed once. |

### Meta
| Field | Type | Notes |
|---|---|---|
| `lastUpdate` | ISO date | Freshness of the record. |

## Describing the route — content style rules

Learned from multi-pitch.com's content rules. When the Taxonomy Engine *writes* the prose
fields, follow these so generated descriptions read like the curated site:

1. **Voice:** never "I" or "we" — say **"the climber"**.
2. **Plain language:** avoid unqualified mountain jargon, or qualify it. Not *"follow the
   col to the dihedral before the arête"* → *"follow the gully between the rocks until you
   see the corner before the exposed edge on the left."*
3. **Informal is fine.**
4. **Facts earn their place:** include geology, first/notable ascent, and history — these
   are what make a description worth reading.
5. **Pitch format:** `Pitch N – <length>m <grade>` then the moves, one block per pitch.
6. **Reference-link prefixes** (for scannability): `Video:`, `Travel:`, `Article:`,
   `Info:`, `Tides:`. e.g. `Video: Chris Bonington Climbs the Old Man of Hoy`.
7. **Approach block** always splits into `Approach:` and `Descent:`.

## Minimal vs full tagging

A found climb is **usable** once it has: `routeName`, `cliff`, `geoLocation`,
`originalGrade`+`gradeSys`, `length`, `pitches`, `rock`, and a mapped `dataGrade`. Everything
else (flags, prose, media, references) enriches it toward guidebook quality.

## Rules for the parser (Phase 2)

1. **Keep `originalGrade` verbatim** and always store `gradeSys` — never a bare number.
2. **Map to `dataGrade`** via [`grade-conversion.md`](grade-conversion.md) for cross-venue
   sorting.
3. **Validate enums** (`rock`, `incline`, `face`, `gradeSys`) against [`taxonomy.md`](taxonomy.md);
   repair or quarantine off-dictionary values.
4. **Hazard flags are safety-critical** — only set `loose`/`tidal`/`seepage` from explicit
   source evidence; carry the source span.
5. **Prose to the style rules above**, with provenance + confidence.
6. **`status: draft`** anything not yet human-verified — only `publish` surfaces.

## Proposed extensions (from the world's climbing databases)

This schema is the *curated depth* baseline. A review of UKClimbing, theCrag, Mountain
Project, and **OpenBeta** yielded concrete upgrades — a hierarchical area model with
inheritance, a `gradeContext`, an all-systems `grades{}` object, composable disciplines,
structured `pitches[]`, `boltsCount`/rack, editorial `stars`, structured first-ascent, and
an access/stewardship layer. Full analysis and priorities in
[`external-models.md`](external-models.md).

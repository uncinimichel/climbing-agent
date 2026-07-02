# The Strict Data Dictionary

The controlled vocabulary Phase 2's Taxonomy Engine must map raw text onto. The rule:
**every field is a closed enum** — the LLM parser proposes a value, and anything not in
these tables is rejected or repaired, never surfaced. This is what turns chaotic
guidebook prose into queryable structured data.

> Status: this dictionary is **specified** here. Automated population (NLP parsing) is
> *planned*; today the values are supplied by hand in `venues.json` / `data.json`.
>
> **Grounded in real data:** these vocabularies are validated against the
> **multi-pitch.com** dataset (`/dev/multi-pitch`, ~40 fully-tagged routes). The full
> per-route record they populate is in [`route-schema.md`](route-schema.md); the
> normalized difficulty ladder is in [`grade-conversion.md`](grade-conversion.md).

## Rock type

| Value | Notes (drying / seepage behaviour) |
|---|---|
| `granite` | Dries fast; low seepage; good friction when cool. Poorly-cemented grades shed grains ("ball-bearings"). |
| `limestone` | **Seeps for days**; overhangs stay wet; slick when humid. Lower hand friction (~0.64) than sandstone. |
| `dolerite` | Fair Head — grippy, dries reasonably; sea-cliff exposure. |
| `rhyolite` | Welsh mountain rock; lichenous, slow to dry high up. |
| `sandstone` | **Fragile when wet — do not climb wet** (holds break). Porosity >20%; water kills inter-grain friction and cracks propagate fast when humid. Highest dry friction (~0.74). |
| `gabbro` | Extremely grippy (Skye); rough. |
| `quartzite` | Hard, can be polished; variable drying. |
| `volcanic` | Lake District; broken, mountain drainage. |
| `dolomite` | Alpine; afternoon convection risk. |

Extend deliberately — a new rock type is a curation decision, not a free-text field.
Rock-friction/seepage figures are sourced in [`references.md`](references.md) (friction
science; wet-sandstone hazard).

## Climbing style

| Value | Meaning |
|---|---|
| `trad` | Leader-placed removable protection. |
| `sport` | Pre-placed bolts. |
| `multi-pitch` | Multiple rope-lengths with belay stances (the platform's focus). |
| `single-pitch` | One rope-length. |
| `alpine` | Mountain approach, altitude, mixed commitment. |
| `big-wall` | Multi-day / very long (e.g. Paklenica's Anica Kuk up to 350 m). |
| `slab` / `face` / `crack` / `ridge` | Feature type, optional secondary tag. |

Styles combine (e.g. `trad` + `multi-pitch` + `alpine`).

## Protection quality (safety grade)

The single most important safety metadata to isolate. The `G/PG/PG-13/R/X` suffixes were
introduced by **Jim Erickson in 1980**, borrowed from the US **movie-rating** system (see
[`references.md`](references.md)).

| Grade | Meaning |
|---|---|
| `G` | Solid, plentiful protection. |
| `PG` | Good protection, generally safe. |
| `PG-13` | Mostly good; some runouts or marginal placements. |
| `R` | **Serious** — runout; a fall risks injury. |
| `X` | **Extreme** — ground-fall / death potential; essentially unprotected. |

Parser guidance: map prose ("bold", "serious", "spaced gear", "committing", "no gear for
10 m") to the grade **with a rationale and the source span**, then validate against this
enum. **Seed a prior from the grade itself** — for UK trad, the adjectival↔technical gap
signals protection (well-protected single move vs. serious/sustained); see the "typical
pairing" rule in [`grade-conversion.md`](grade-conversion.md).

## Difficulty (grade systems)

Grades are **system-scoped** — never compare across systems without conversion. Store the
raw grade *and* the system code, then map to the normalized `dataGrade` 1–7 ladder for
sorting. Full mapping + system definitions: [`grade-conversion.md`](grade-conversion.md).

| `gradeSys` | System | Region | Example |
|---|---|---|---|
| `BAS` | British Adjectival (adjective + technical) | UK/Ireland | `VS 4c`, `HVS 5b`, `E1 5b` |
| `UIAA` | UIAA | Alps/Germany | `IV−`, `V+`, `VI+` |
| `YDS` | Yosemite Decimal | US | `5.7`, `5.10a` |
| `ALP` | Alpine (commitment: PD/AD/D/TD/ED) | Alps | `Difficile`, `TD (f6a+)` |
| `FS` | French Sport | Europe/sport | `f4c`, `f6a+` |
| `N` | Norwegian | Norway | `N6−` |

## Incline / steepness

The overall angle of the route. Values compose left→right as the route steepens.

| Value | Meaning |
|---|---|
| `Slab` | Less than vertical; balance/friction climbing. |
| `Slab & Vertical` | Mixed slabby and vertical sections. |
| `Vertical` | Wall-steep. |
| `Vertical & Overhanging` / `… & Overhanging` | Includes steeper-than-vertical ground. |

## Aspect / face (for the condition model)

`N` `NE` `E` `SE` `S` `SW` `W` `NW` — the compass direction the route faces (`face` field).
Governs sun/shade, temperature, and drying. Example: Paklenica's Anica Kuk faces **north**
→ stays shaded/cool in a hot July; S-facing dries fastest but bakes.

## Route character & hazard flags

Boolean tags (`1` = present, absent/`null` = not). Safety-critical ones (`loose`, `tidal`,
`seepage`) may only be set from **explicit source evidence**. Several feed downstream logic.

| Flag | Meaning | Feeds |
|---|---|---|
| `tidal` | Access/base tide-dependent (sea cliffs) | tide-window logic (planned) |
| `seepage` | Weeps / holds water after rain | Predictive Condition Algorithm |
| `abseil` | Requires an abseil (approach/descent) | gear & planning |
| `traverse` | Significant traverse | rope management / commitment |
| `boat` | Reached by boat or swim | logistics |
| `polished` | Slick, polished rock | difficulty-in-practice |
| `loose` | Loose / friable rock | safety |
| `grassLedges` | Vegetated ledges (wet/awkward) | conditions |

## Approach

| Field | Type | Meaning |
|---|---|---|
| `approachTime` | int (min) | Walk-in time. |
| `approachDifficulty` | 1–3 | 1 = easy walk · 2 = moderate · 3 = serious (scramble/swim/exposed). |

## Record shape

This file defines the **controlled vocabularies** (the enums above). The **full route
record** those values populate — identity, physical, grade, approach, flags, prose,
media, references, per-route climatology — is specified in
[`route-schema.md`](route-schema.md), grounded in the multi-pitch.com data model. A
condensed illustration of the tagged output:

```json
{
  "sector_id": "old-man-of-stoer",       // FK into the Phase-3 master index
  "routeName": "Original Route",
  "cliff": "Old Man of Stoer",
  "style": ["trad", "multi-pitch"],
  "rock": "sandstone",
  "protection": "PG",
  "gradeSys": "BAS", "originalGrade": "VS 5a", "dataGrade": 5,
  "incline": "Vertical", "face": "SE",
  "length": 67, "pitches": 5,
  "tidal": 1, "abseil": 1, "traverse": 1,
  "approachTime": 50, "approachDifficulty": 3,
  "source": { "url": "…", "span": "sea stack, Tyrolean traverse", "confidence": 0.82 }
}
```

## Rules for the parser

1. **Closed enums only.** Off-dictionary value → repair or reject; never surface.
2. **Keep provenance.** Store source URL, extracted span, and confidence.
3. **Grade is system-scoped.** Store `gradeSys` + verbatim `originalGrade`, then map to
   `dataGrade` via [`grade-conversion.md`](grade-conversion.md) — never a bare number.
4. **Safety flags need evidence.** Only set `loose`/`tidal`/`seepage` from explicit source
   text, with the span.
5. **Prose to the style rules** in [`route-schema.md`](route-schema.md) ("the climber",
   qualify jargon, pitch-by-pitch, prefixed reference links).
6. **Join by `sector_id`.** Every climb maps to a verified Phase-3 sector, or it's
   quarantined (Zero-Garbage UGC). Leave unverified records `status: draft`.

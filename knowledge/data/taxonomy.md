# The Strict Data Dictionary

The controlled vocabulary Phase 2's Taxonomy Engine must map raw text onto. The rule:
**every field is a closed enum** — the LLM parser proposes a value, and anything not in
these tables is rejected or repaired, never surfaced. This is what turns chaotic
guidebook prose into queryable structured data.

> Status: since decision #35 the **values live in Postgres and are managed in the
> Curation Studio's Taxonomy page** (localhost:8890 → Taxonomy): add a value with its
> one-line meaning there and it immediately reaches the studio's tag dropdowns AND the
> AI tagger (`ai_tag.py` reads the live set). Every change auto-regenerates
> [`taxonomy-values.json`](taxonomy-values.json) (the served live list, with usage
> counts) and `db/sql/105_taxonomy_extensions.sql` (so a DB rebuild replays it).
> **This document stays the semantic source of truth** — what each family means, the
> tagging rules, the science; its value tables are documentation and may lag the live
> set by a few entries.
>
> **Grounded in real data:** these vocabularies are validated against the
> **multi-pitch.com** dataset (`/dev/multi-pitch`, ~40 fully-tagged routes) and a
> 2026-07-13 cross-platform survey (Rockfax symbols, UKC, theCrag, Mountain Project,
> OpenBeta — see `roadmap/curation-studio-plan.md`). The full per-route record they
> populate is in [`route-schema.md`](route-schema.md); the normalized difficulty
> ladder is in [`grade-conversion.md`](grade-conversion.md).

## Tag quick-reference (the canonical set)

**This file is the single source of truth for tags** — every other doc references these,
none redefine them. The complete controlled vocabulary, in one scannable block for the
Phase-3 curated list. Each value is a closed enum; detail + rationale follow below.
These vocabularies are mirrored as **Postgres lookup tables** (`db/sql/`, seeded in
`100_seed_taxonomy.sql` — see [`database.md`](database.md)); extend an enum here first,
then in the seed, so the two never drift.

| Facet | Type | Values |
|---|---|---|
| `discipline` | set | `trad` `sport` `multi-pitch` `single-pitch` `alpine` `big-wall` `bouldering` `ice` `mixed` `snow` `aid` `deepwatersolo` `tr` `via-ferrata` |
| `feature` | set (opt.) | `slab` `face` `crack` `ridge` `arête` `chimney` `corner` `groove` `roof` `offwidth` `flake` `tufa` `pockets` `pillar` |
| `character` | set (opt.) | `sustained` `pumpy` `powerful` `technical` `fingery` `crimpy` `reachy` `delicate` `exposed` `fluttery` |
| `rock` | one | `granite` `limestone` `dolerite` `rhyolite` `sandstone` `gritstone` `gabbro` `quartzite` `volcanic` `dolomite` `slate` `gneiss` `schist` `basalt` `conglomerate` `andesite` |
| `protection` | one | `G` `PG` `PG-13` `R` `X` `runout` `terrain` `UNSPECIFIED` |
| `protectionStyle` | one | `gear` `bolted` `mixed` `none` — how the route protects overall |
| `belays` | one | `gear` `bolted` `mixed` — belay/anchor type (key multi-pitch fact) |
| `gradeSys` | one | `BAS` `UIAA` `YDS` `ALP` `FS` `N` `EW` `SX` `BRZ` `V` `Font` `WI` `AI` `M` `D` `SCO` `A`/`C` `VF` `S` |
| `commitmentGrade` | one | `I`–`VII` (NCCS) · `F`/`PD`/`AD`/`D`/`TD`/`ED` (alpine) |
| `incline` | compose | `Slab` → `Vertical` → `Overhanging` |
| `face` (aspect) | one | `N` `NE` `E` `SE` `S` `SW` `W` `NW` |
| `hazard` (route) | flags | `tidal` `seepage` `abseil` `traverse` `boat` `polished` `loose` `grassLedges` |
| `hazard` (objective) | flags | `rockfall` `avalanche` `serac` `crevasse` `altitude` `stormExposed` `cornice` |
| `conditions` | fields | `elevation_m` · `sunWindow` (`morning`/`afternoon`/`all-day`/`shade`) · `bestSeason[]` · `windExposed` |
| `approach` | fields | `approachTime` (min) · `approachDifficulty` (1–3) |
| `ascentStyle` | one | `onsight` `flash` `redpoint` `pinkpoint` `headpoint` `groundup` `second` `toprope` `solo` `aid` (+modifiers `clean`/`dog`) |

## Rock type

| Value | Notes (drying / seepage behaviour) |
|---|---|
| `granite` | Dries fast; low seepage; good friction when cool. Poorly-cemented grades shed grains ("ball-bearings"). |
| `limestone` | **Seeps for days**; overhangs stay wet; slick when humid. Lower hand friction (~0.64) than sandstone. |
| `dolerite` | Fair Head — grippy, dries reasonably; sea-cliff exposure. |
| `rhyolite` | Welsh mountain rock; lichenous, slow to dry high up. |
| `sandstone` | **Fragile when wet — do not climb wet** (holds break). Porosity >20%; water kills inter-grain friction and cracks propagate fast when humid. Highest dry friction (~0.74). |
| `gritstone` | Coarse UK sandstone (Peak/Yorkshire) — superb friction, rounded breaks; dries fast but greasy in humidity, brutal in heat. Same avoid-when-wet ethic as soft sandstone. |
| `gabbro` | Extremely grippy (Skye); rough. |
| `quartzite` | Hard, can be polished; variable drying. |
| `volcanic` | Lake District; broken, mountain drainage. |
| `dolomite` | Alpine; afternoon convection risk. |
| `slate` | Non-porous — drains instantly, but **slick when wet**; positive edges; quarried faces (Llanberis). |
| `gneiss` | Banded metamorphic (Alps, Norway); generally solid, good friction. |
| `schist` | Layered; can be friable and ledgy; holds moisture in breaks. |
| `basalt` | Columnar jointing → parallel crack systems; moderate drying. |
| `conglomerate` | Cobbles in matrix (Montserrat, Meteora, Riglos) — pockety climbing; protection often spaced between cobbles. |
| `andesite` | Volcanic; blocky, variable quality. |
| `chalk` | Soft marine limestone (Dover, Beachy Head sea cliffs) — friable, specialist/serious trad; **never climb wet**; protection unreliable. Added 2026-07-13 (corpus ingest). |

Extend deliberately — a new rock type is a curation decision, not a free-text field.
Rock-friction/seepage figures are sourced in [`references.md`](references.md) (friction
science; wet-sandstone hazard). The 2026-07-04 extension (gritstone, slate, gneiss,
schist, basalt, conglomerate, andesite) matches the faceted rocktype vocabulary the
UKClimbing crag database searches on — these are the missing types our venue list
already brushes against (UK grit/slate; Montserrat-style conglomerate).

## Route character (how it climbs)

**New facet (2026-07-04), set-valued.** The guidebook shorthand for *what kind of hard*
a route is — adopted from the Rockfax database symbols (sustained/fingery/fluttery/
powerful/technical) and theCrag's Rockfax-style route tags (crimpy, pumpy, reachy).
This is the facet that answers "pumpy jug-haul or delicate slab?", which grade and
feature alone cannot.

| Value | Meaning |
|---|---|
| `sustained` | Lots of hard moves with little respite (Rockfax "s"). |
| `pumpy` | Steep endurance climbing — the pump, not a single move, is the crux. |
| `powerful` | Demands strength on steep ground (Rockfax "p"). |
| `technical` | Intricate movement; body position over pulling. |
| `fingery` | Significant small holds on the hard sections (Rockfax "f"). |
| `crimpy` | Specifically small-edge crimping. |
| `reachy` | Move spans favour reach; height-dependent. |
| `delicate` | Balance/friction climbing; precision under little security. |
| `exposed` | Big-air positions beyond what the protection grade captures. |
| `fluttery` | Bold — big fall potential and scary run-outs (Rockfax "h"). Pair with `protection` R/X. |

Parser guidance: these may be set from explicit prose ("a pumpy tour de force",
"thin technical wall") — map adjectives, keep the span. Don't infer from grade.

## Climbing style / discipline

**Composable, not exclusive** — a route carries a *set* of these (following OpenBeta's
`ClimbType`, where a route can be e.g. sport *and* top-rope). Store as an array.

| Value | Meaning |
|---|---|
| `trad` | Leader-placed removable protection. See also `protectionStyle`/`belays` below — a route can be gear-protected with bolted belays (common in the Alps). |
| `sport` | Pre-placed bolts. |
| `multi-pitch` | Multiple rope-lengths with belay stances (the platform's focus). |
| `single-pitch` | One rope-length. |
| `alpine` | Mountain approach, altitude, mixed commitment. |
| `big-wall` | Multi-day / very long (e.g. Paklenica's Anica Kuk up to 350 m). |
| `bouldering` | Ropeless, low, over pads. |
| `ice` | Frozen falls/ice (WI grades). |
| `mixed` | Rock + ice (M grades). |
| `snow` | Snow climbing. |
| `aid` | Weighting gear to progress (A/C grades). |
| `deepwatersolo` | Ropeless over water (DWS). |
| `tr` | Top-rope. |
| `via-ferrata` | Protected cabled route. |
| `slab` / `face` / `crack` / `ridge` / `arête` / `chimney` / `corner` / `groove` / `roof` / `offwidth` / `flake` / `tufa` / `pockets` / `pillar` | Feature type, optional secondary tag. Extended 2026-07-04: `corner` (dihedral/open book), `groove`, `roof`, `offwidth` (wide crack), `flake`, `tufa` + `pockets` (the two defining limestone features), `pillar`. |

Styles combine (e.g. `trad` + `multi-pitch` + `alpine`). The extended disciplines
(`bouldering`…`via-ferrata`) are adopted from external models —
see [`external-models.md`](external-models.md).

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
| `runout` | A stretch with no protection below you (from OpenBeta's `SafetyEnum`). |
| `terrain` | Danger from the terrain itself (loose ground, ledges) rather than fall distance. |
| `UNSPECIFIED` | Protection not yet assessed — the honest default, don't guess. |

The `runout` / `terrain` / `UNSPECIFIED` values are adopted from OpenBeta — see
[`external-models.md`](external-models.md).

**Protection style & belays (added 2026-07-04).** Orthogonal to the safety grade:
*what kind* of protection, not how good it is. Two one-of fields:

| Field | Values | Meaning |
|---|---|---|
| `protectionStyle` | `gear` · `bolted` · `mixed` · `none` | Leader protection overall: trad gear, bolts, a mix (bolts + gear sections), or effectively unprotectable. |
| `belays` | `gear` · `bolted` · `mixed` | Anchor type at stances — a first-order multi-pitch planning fact (bolted-belay trad routes retreat far more easily; drives the `escapable` judgement and rope/rack choice). |

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
| `N` | Norwegian/Scandinavian | Norway/Sweden/Finland | `N6−` |
| `EW` | Ewbank | Australia/NZ/South Africa | `18`, `24` |
| `SX` | Saxon (Dresden) | Saxon Switzerland/Bohemia | `VIIb`, `VIIIa` |
| `BRZ` | Brazilian (overall + technical) | Brazil | `VIsup`, `7b` |

**Discipline-specific systems** (needed now that `style` includes ice/mixed/aid/bouldering —
map the leading characters, à la Mountain Project):

| `gradeSys` | Discipline | Example |
|---|---|---|
| `V` | Bouldering (Hueco/V-scale) | `V0`, `V7` |
| `Font` | Bouldering (Fontainebleau) | `6a+`, `7c` |
| `WI` | Water ice | `WI3`, `WI5` |
| `AI` | Alpine ice | `AI3` |
| `M` | Mixed (rock + ice) | `M6`, `M8` |
| `D` | Drytooling | `D8` |
| `SCO` | Scottish Winter (overall Roman + technical Arabic) | `VI,7` |
| `A` / `C` | Aid / clean aid | `A2`, `C3` |
| `VF` | Via ferrata (Hüsler/Schall) | `K3`, `C` |
| `S` | Deep-water solo seriousness (objective risk: tide, depth, fall) | `S0`–`S3` |

Systems added 2026-07-04 (`EW`, `SX`, `BRZ`, `D`, `SCO`, `VF`, `S`) close the gaps
against the full grade-system landscape: Ewbank is OpenBeta-native (interop),
`via-ferrata` and `deepwatersolo` disciplines previously had no grade system at all,
and Scottish Winter matters the moment UK winter venues enter the corpus. The
`dataGrade` ladder does **not** yet map these — extend
[`grade-conversion.md`](grade-conversion.md) deliberately when routes in these systems
are first ingested (log it in the decision log). Not adopted (yet, deliberately):
Polish Kurtyka, Russian/Alaskan alpine, Canadian ice, Japanese Dankyū — no venue on
our lists needs them; add on first contact, not speculatively.

## Commitment grade (overall seriousness / size of day)

Distinct from technical difficulty — **how big and committing the outing is** (time, length,
remoteness, escapability). Essential for multi-pitch/big-wall planning and easy to forget.

| System | Values | Meaning |
|---|---|---|
| **NCCS** (Roman "grade") | `I`–`VII` | Overall time: `I`/`II` a few hrs · `III` most of a morning · `IV` a full day · `V` long/possible bivvy · `VI` multi-day · `VII` remote multi-day big-wall. |
| **Alpine (IFAS)** | `F` `PD` `AD` `D` `TD` `ED` (+`ABO`) | Overall alpine commitment — already carried via `gradeSys: ALP`. |

Store as `commitmentGrade` (e.g. `"III"`). Also track **`escapable`** (can you retreat
mid-route?) — a serious multi-pitch attribute.

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
| `tidal` | Access/base tide-dependent (sea cliffs) | tide-window logic (**live 5 Jul 2026** — see below) |
| `seepage` | Weeps / holds water after rain | Predictive Condition Algorithm |
| `abseil` | Requires an abseil (approach/descent) | gear & planning |
| `traverse` | Significant traverse | rope management / commitment |
| `boat` | Reached by boat or swim | logistics |
| `polished` | Slick, polished rock | difficulty-in-practice |
| `loose` | Loose / friable rock | safety |
| `grassLedges` | Vegetated ledges (wet/awkward) | conditions |

**`tidal` also exists at crag level** (the only flag that does, so far): a venue/crag whose
approach or base needs a tide window carries `tidal: true` in `venues.json` / the planner's
`GAZETTEER`. The crag flag is either set explicitly or derived from route evidence — one or
more `tidal` routes within 10 km of the crag (tight radius: the flag is safety-critical, so
a tidal route 50 km away says nothing about this crag). It drives the tide-times fetch
(Open-Meteo Marine hourly sea level → per-day high/low water) shown in the planner's
weather tiles, tags and static venue pages. Route-level `tidal` keeps meaning exactly what
it always did: *this route* needs the tide.

**Objective mountain hazards** (safety-critical for the alpine venues — Dolomites, Tyrol,
Picos — that are our backups; set only from explicit evidence):

| Flag | Meaning |
|---|---|
| `rockfall` | Rockfall-prone (loose gullies, thaw, parties above). |
| `avalanche` | Avalanche terrain (snow slopes, couloirs). |
| `serac` / `crevasse` | Glacier hazards on the approach/route. |
| `altitude` | High enough for thin air / altitude effects. |
| `stormExposed` | Exposed to lightning / no quick escape in a storm. |
| `cornice` | Corniced ridge/summit. |

## Conditions & orientation (route-level)

Beyond `face`/aspect — the fields that decide *when* a route is in condition:

| Field | Type | Meaning |
|---|---|---|
| `elevation_m` | int | Altitude of the route — drives temperature, snow line, season. |
| `sunWindow` | enum | When sun hits: `morning` · `afternoon` · `all-day` · `shade`. A N-face in shade climbs cool in a heatwave; a sunny face is a winter pick. |
| `bestSeason` | months[] | Months the route is typically in condition (e.g. sea-cliffs avoid bird-ban spring; alpine = summer). |
| `windExposed` | bool | Exposed to wind (dries fast but cold/serious). |

## Approach

| Field | Type | Meaning |
|---|---|---|
| `approachTime` | int (min) | Walk-in time. |
| `approachDifficulty` | 1–3 | 1 = easy walk · 2 = moderate · 3 = serious (scramble/swim/exposed). |

## Ascent style (how a route was climbed)

Distinct from the intrinsic-route enums above: this describes **an ascent event**, not the
rock. We use it now to record the **style of a first ascent (`fa`/`ffa`)**, and it's the
vocabulary a future ticks/logbook feature would need. Values follow theCrag/OpenBeta (see
[`external-models.md`](external-models.md)). The distinctions turn on two axes: **prior
knowledge** (did you know the moves?) and **prior practice** (did you rehearse it?).

| Value | Meaning |
|---|---|
| `onsight` | Lead **first try, clean** (no falls/rests), with **no prior beta** and never having seen it climbed. The purest style. |
| `flash` | Lead **first try, clean**, but **with prior beta** (told the sequence / watched someone). |
| `redpoint` | Lead **clean after rehearsing** it over previous attempts (placing gear / clipping as you go). |
| `pinkpoint` | A redpoint with gear/quickdraws **pre-placed**; older term, now usually folded into `redpoint`. |
| `headpoint` | Trad: clean lead **after top-rope practice** — common for bold, hard-to-protect routes (E-grades). |
| `groundup` | Attempted **from the ground up**, no top-rope rehearsal (may take several ground-up tries). |
| `second` / `follow` | Climbed **after the leader**, protected by a rope from above. |
| `toprope` (`tr`) | Climbed on a rope **anchored above** the climber. |
| `solo` / `free-solo` | Climbed **with no rope** (free-solo = ropeless free climbing). |
| `aid` | **Weighting gear** to make upward progress (not free climbing). |
| `clean` | Modifier: **no falls and no resting on gear** — required for onsight/flash/redpoint. |
| `dog` / `hangdog` | Modifier: **worked the route resting on gear** between moves (not a clean ascent). |

**First-ascent terms:** `firstascent` (`FA`) = the first person to climb the line;
`firstfreeascent` (`FFA`) = the first to climb it **free** (no aid), used when the line was
originally aided. Store these with the ascent style, e.g. `fa: { climber, year, style: "groundup" }`.

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

# Area Character Tags — the Key

The "Area character" pills on each venue card in the [live dashboard](../../index.html)
are the fastest read on what a venue offers. This page is the key the dashboard's
**?** links to: what every tag means, what values it can take, and where it comes
from. It is the reader-facing face of the [Strict Data Dictionary](taxonomy.md) —
the enums here are a friendly summary of the controlled vocabulary defined there.

> **Terminology is checked against source.** Field names and hazard wording follow
> **multi-pitch.com** (our primary route data), cross-checked against the
> **UKClimbing** crag database facets and our own [`taxonomy.md`](taxonomy.md).
> Where a pill rewords a source flag for readability, the source term is noted.

## Two tiers

Every tag is one of two kinds of fact, and that split is the top of the hierarchy:

- **Tier 1 · Trip fit — dynamic.** About *this* trip: your dates, your origin, your
  window. Recomputed every run. The test: *it would never tag a single climb.*
- **Tier 2 · Area taxonomy — static.** Guidebook facts about the place — rock,
  aspect, grade, scale, hazards. True whenever you go, and the **same vocabulary
  that will tag each individual climb** once climb-level tagging lands (a venue
  value is just a rollup of its climbs). See [`route-schema.md`](route-schema.md).

Tags always render in a **fixed order** — Trip fit, then Character, then Scale &
grade, then Hazards — so a pill keeps its place whether a card has three tags or
sixteen. A family with no data for a venue simply doesn't draw.

Each family has one colour: **violet** = Trip fit · **grey** = Character ·
**green** = Scale & grade · **amber** = Hazards.

---

## Tier 1 · Trip fit — dynamic (violet)

Is this venue a good use of *this* trip? None of these would ever describe a single climb.

{{TAGTABLE:trip}}

---

## Tier 2 · Area taxonomy — static

The guidebook facts about the crag. A venue value is an aggregate of its climbs
(range / max / median / union); at climb level each field carries its own value.

### Character — grey

The physical crag — true regardless of which climb you pick.

{{TAGTABLE:character}}

### Scale & grade — green

How much, how hard, how big — coarse from your sheet, precise from the index.
`vol`/`diff` are the sheet's coarse estimate of `routes`/`grade`.

{{TAGTABLE:scale}}

### Hazards — amber

Safety & access flags — never inferred, only set when a climb says so. Pill text
mirrors the source flag (e.g. *Suffers Seepage* → "Seepage after rain").

{{TAGTABLE:hazard}}

---

## Notes

- **Two collisions were removed (2026-07-05).** `height` used to mean both a sheet
  wall-height estimate *and* the tallest indexed route; `grade` meant both the grade
  range *and* a pitch count. They are now `wallheight`/`tallest` and `grade`/`pitches`
  — distinct kinds, distinct colours.
- **`vol` and `diff` moved from Trip fit to Scale & grade** — a venue's volume and
  difficulty spread are static facts about the area, not about your trip.
- **The `auto` "from your sheet" pill was dropped** — it stated provenance, not a
  venue trait, and already repeats in the venue's summary line.
- **Single source of truth:** `knowledge/data/tag-spec.json`. The dashboard's tag
  colours, tooltips, legend and order are generated from it (`update_report.py`),
  and the tables on this page are generated from it too (the `{{TAGTABLE:…}}`
  placeholders, filled by `build_knowledge.py`). It lives here, not under the trip
  folder, because it is static taxonomy — trip-independent. Edit the spec, not the code.
- The full per-climb record these tags summarize is in
  [`route-schema.md`](route-schema.md); the controlled vocabularies are in
  [`taxonomy.md`](taxonomy.md); grade systems in [`grade-conversion.md`](grade-conversion.md).

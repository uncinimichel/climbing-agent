# Curator's Handbook — first draft (field audit)

> Status: **partly settled** — Michel red-penned 4 of the 6 open questions on
> 2026-07-28 (recorded in ["Resolved"](#resolved-michel-2026-07-28) below;
> questions 3 and 6 still open). Where a resolution contradicts the audit's
> lean, **the resolution wins** and the affected section is annotated. Companion
> to [taxonomy.md](data/taxonomy.md) (which defines the tag vocabularies).

The trigger was `wind exposed: yes/no` — a field that reads like it's asking
"is it windy," which of course depends on the day and the direction. It turned
out the field is *right* and the **label** is wrong. That gap — a defensible
field wearing nonsense words — is the pattern this audit hunts for.

---

## The one rule

Every field belongs in exactly one bucket. Get the bucket wrong and the field
feels like AI slop even when the data is fine.

| Bucket | What it is | Whose job |
|---|---|---|
| **A · Fact** | A physical thing you can observe standing at the crag (aspect, rock, tidal, how many pitches). Doesn't change with the weather. | The curator records it. |
| **B · Derived** | Something the engine computes from facts + live weather (wind exposure on a given day, drying speed, "is it in condition this weekend"). | The engine. **A human should never toggle it.** |
| **C · Judgment** | A climber's opinion (quality, "why climb it", character). | The curator, but flagged as opinion. |

**Corollary:** *if the engine can compute a field from other fields, it is not a
curator field.* Asking a human to hand-set a derived thing is a category error —
it's laborious, it goes stale, and it can silently disagree with the live
ranking. Most of the "silly" fields below are Bucket B masquerading as a toggle.

---

## Exhibit A — `wind_exposed`

**Verdict: right field, wrong label. Keep the data, rewrite the words.**

It is *not* asking "is it windy." It's a **Bucket A fact**: does this crag have
no hillside behind it to shelter it — a sea cliff, a summit tor, a standalone
buttress — so wind reaches it from *any* direction? The engine (`engine/weather.py`)
then does the real work: it holds a compass bearing for each aspect and computes
**wind-vs-face exposure against the forecast wind direction** — a leeward wall is
part-sheltered by its own hill, a windward one gets hammered — and scales drying
speed off it. So the direction-dependence you (rightly) expected *is* handled;
the boolean is just the one static fact the model can't infer.

- **Label now:** `wind exposed: yes / no`
- **Label should be:** something like **"Open to the wind?"** with the hint
  *"a sea cliff, summit, or standalone buttress with no hillside behind it —
  the ranking works out the rest from aspect + forecast direction."*

The lesson generalises: several fields below are real inputs with labels that
make them look dumber than they are.

---

## Field-by-field

Only the fields worth a comment are listed. Anything not here (name, grade,
length, pitches, lat/lon, intro prose, images, guidebooks, references) is
fine as-is.

### Category errors — Bucket B asked as a human toggle

| Field | Now | Problem | Fix |
|---|---|---|---|
| **best months** | 12 clickable months | The engine already scores conditions from aspect + climate + live weather. Hand-toggling 12 months is laborious, goes stale, and can contradict the live ranking. | ✅ **Resolved: derive + override.** Show derived **read-only** ("typically Apr–Sep"), optional human *override* for local knowledge the data misses. Don't ask it blank. |
| **sun window** | enum (human) | Largely a function of **aspect** (a NE face gets morning sun, a SW face evening). You already store aspect. | ✅ **Resolved: derive + override.** Default from aspect; human overrides only where topography shadows it (deep gorge, north-facing in a south-facing cove). |
| **approach diff 1–5** | bare number | An **unanchored scale**. What is a 3? Nobody can tag consistently and no reader can decode it. | Replace with a described enum: *flat path · uphill walk · steep/rough · scramble · technical approach*. Anchored words beat a naked number. |

### Labels or scope that mislead

| Field | Now | Problem | Fix |
|---|---|---|---|
| **protection** | Erickson `G/PG/PG-13/R/X` | That's the **US seriousness scale**. In British trad, seriousness is already baked into the **E-grade** (E1 5a vs HVS 5a *is* the danger signal). Asking both risks double-counting or confusing curators on UK routes. | ⚖️ **Resolved (overrides the audit): keep everywhere.** Michel's call — show the seriousness field on all routes regardless of grade system; curators may leave it blank on E-graded routes where it's redundant. Don't hide by grade system. |
| **commitment** | alpine grade `I–VII` | Meaningful for alpine/big-wall; **noise on a single-pitch roadside VS**, which is most of the corpus. | Show only when discipline is alpine/big-wall/multi-pitch. |
| **abseils** | number | Only relevant if the descent *is* abseils. | Show only when `descent method = abseil`. |
| **rope** | free text | Unclear what it wants — length? number? Overlaps with **rack** ("60m ropes"). | Decide: fold into rack, or make it structured (single/half/twin + length). |
| **escapable** | yes/no + good hint | Actually fine — a real Bucket A fact, well-worded ("can you bail mid-route without topping out?"). Keep. | — |

### The bigger editorial problem — the form asks everything of everything

The info-ring row shows **~18 fields for every climb**, regardless of what it
is. A single-pitch roadside VS gets asked for *commitment grade*, *abseils*,
*escapable*, *descent method* — all noise; a curator either leaves them blank
(and the row looks unfinished) or guesses. The audit's lean was to make fields
appear conditionally on discipline and pitch count.

⚖️ **Resolved (overrides the audit): keep always-on.** Michel's call — every
field shows on every climb; irrelevant ones are simply left blank rather than
hidden. A uniform card beats conditional logic here. (If the blank-row-looks-
unfinished problem bites later, revisit — but don't build conditional
visibility now.)

### Naming collision

`character` tags include **"exposed"** (the climber's sense — airy, committing)
while a separate field is **"wind exposed"**. Two unrelated meanings of one word
on the same card. Rename one (e.g. wind → "open to the wind", per Exhibit A).

---

## Gaps — facts the engine needs that you *can't* enter

The ranking engine reads these, but **none are editable in the Studio**:

- `tidal` — can you even reach the base at high water? (binary, changes the day)
- `coastal` / `drying` — how fast the rock comes back into nick after rain
- `seepage` — does it stay wet after dry weather?
- `cliff_height_m` — used in exposure/commitment

Right now the ranking depends on facts a curator has no way to set.

⚖️ **Resolved: make them editable per-route.** Michel's call — surface
`tidal`, `coastal`/`drying`, `seepage` and `cliff_height_m` as **per-route**
fields in the Studio (not a crag-level panel, despite most being crag-wide
facts). Simpler mental model; the cost is re-entering the same fact across a
crag's routes. New Studio work to add these inputs to the card.

---

## What "well-curated" looks like (the C-bucket standard)

The prose is the product. A good entry:

1. **Intro** answers *why climb it* — the line, the crux, the character — in a
   climber's voice, not a spec sheet. (Ground the voice in the guidebook/UKC
   prose you already have rights to; that's the house style, not invented copy.)
2. **Facts** are the ones that apply, filled honestly; blanks left blank, not
   fudged to look complete.
3. **Hazards** carry evidence — a safety-critical hazard *requires* a source
   span (the schema enforces this). No decorative danger tags.
4. **Judgment is marked as judgment** — stars and character are opinion; the
   entry shouldn't launder them as fact.

---

## Resolved (Michel, 2026-07-28)

1. **best months / sun window** → ✅ **derive with override** (read-only default
   from aspect/climate; human overrides for local knowledge).
2. **protection vs the E-grade** → ⚖️ **keep everywhere** — show on all routes;
   leave blank where redundant. (Overrides the audit's hide-on-British lean.)
4. **conditional fields** → ⚖️ **keep always-on** — uniform card, blanks over
   hiding. (Overrides the audit's hide-by-discipline lean.)
5. **tidal / coastal / drying / seepage / cliff-height** → ✅ **per-route**,
   made editable in the Studio.

## Still open

3. **approach difficulty** — the described-enum is now **live** with the
   straw-man words (*flat path · uphill walk · steep/rough · scramble ·
   technical*); legacy 1–5 ghost-mapped. **Only the words are still open** —
   confirm them, or hand me replacements and I'll swap the one line.
6. Any field here you'd **cut entirely** as never-useful?

### Resulting Studio work (from the resolutions above)

- ✅ **`wind_exposed` relabel** (Exhibit A) — now "Open to the wind?" with the
  full hint. (`curate_ui.html`.)
- ✅ **Derive sun-window from aspect** — `sun_window` is suggested from the
  crag's aspect (the vocabulary's own meanings fix the map: E→morning, S→all-day,
  W→afternoon, N→shade), shown read-only with a one-click *use* + free override.
  No schema change; the curator accepts or overrides. (`curate_ui.html`.)
- ✅ **Per-route conditions inputs** — `tidal`, `coastal`, `seepage` (yes/no),
  `drying` (fast/medium/slow), `cliff_height_m` (m) added to the card under a new
  **conditions** group; whitelisted + typed in the PATCH path; validated in the
  JSON Schema (off-enum/wrong-type → readable 422). (`curate_ui.html`, `curate.py`,
  `store.py`.) *Note:* these are captured on the route record now; wiring the
  **ranking engine to consume per-route values** (it reads venue-level today) is a
  separate follow-on.
- ✅ **Derive best-months** — done. Routes already carry a per-route monthly
  `climatology` array (temp_high, rainy_days); best-season is derived client-side
  using the **engine's own felt-temp curve verbatim** (COLD 12 · heat 18/24/28 ·
  rain 12/40 · ASPECT_ADJ, from `engine/weather.py`), so the suggestion matches
  the ranking rather than inventing a heuristic. Derived months show **dashed**;
  one-click *use* copies them into `best_season`, and any manual month overrides.
  Routes without climatology fall back to the hand-set toggle. Cross-checked
  against a Python port of the curve (identical output). *Caveat:* the JS curve is
  a copy of the engine's — if the engine's constants change, update both.
- **No change** to protection or field-visibility — explicitly kept as-is.
- ⚠️ **`approach diff`** — implemented with the audit's **provisional** words
  (`flat path · uphill walk · steep/rough · scramble · technical`) as the
  `approach_style` enum, replacing the naked 1–5. The legacy number is
  ghost-mapped (1→flat path … 5→technical) so the 58 routes that had it keep
  their data, shown as an accept/override suggestion. **Question 3 is still open
  on the *words*** — they live in one place (`APPROACH_VALS`) and are a one-line
  change once you confirm or rewrite them.

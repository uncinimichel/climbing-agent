# multi-pitch.com ⇄ climbing DB — field mapping

The spec for merging the two projects: every multi-pitch `climbData` field, its home
in the Postgres schema, and the taxonomy/schema work needed before a lossless
round-trip (ingest MP → Postgres, then `export_mp.py` Postgres → MP JSON).

Verified against all 52 climb files in `multi-pitch/website/data/climbs/` on
2026-07-15. **Result: every MP field has a DB home except `guideBooks[].type`**
(one new column needed), plus two taxonomy values and one widened CHECK.

## 1 · Field map — `climbs/<id>.json` → schema

### Identity & location

| MP field | DB home | Status |
|---|---|---|
| `id` | `external_ref` (`source_id='multipitch'`, `external_id`) | ✅ already in use |
| `routeName` | `route.name` | ✅ |
| `country` | `area` (kind `country`).name | ✅ |
| `county` | `area` (kind `region`).name | ✅ clean values first (see §4) |
| `cliff` | `area` (kind `crag`).name | ✅ |
| `geoLocation` (`"lat,lon"` string) | `route.geom` (Point 4326) | ✅ parse/format on the way through |
| `timeZone` | `route.timezone` | ✅ (51/52 files have it) |
| `status` (`draft`/`publish`) | `route.status` | ✅ identical vocabulary |
| `lastUpdate` | `route.last_update` | ⚠ export must reproduce MP's cache-bust rule: minor edit = old date + 1 s, major edit = now |

### Grades

| MP field | DB home | Status |
|---|---|---|
| `gradeSys` | `route.grade_system_code` | ✅ all 6 observed (ALP, BAS, FS, N, UIAA, YDS) are seeded |
| `originalGrade` | `route.original_grade` | ⚠ ids 15, 19 store a JSON number (5.8/5.7 YDS) — cast to string |
| `tradGrade` | `route.trad_grade` | ✅ |
| `techGrade` | `route.tech_grade` | ✅ |
| `dataGrade` | `route.data_grade` | ✅ observed 1–7 matches the CHECK; NULL on drafts is fine |

### Physical character

| MP field | DB home | Status |
|---|---|---|
| `length` | `route.length_m` | ✅ |
| `pitches` | `route.pitches_count` | ✅ |
| `face` | `route.aspect` | ✅ all 8 observed values in `aspect_dir` |
| `rock` | `route.rock_code` | ⚠ lowercase on ingest; 3 fixes in §3/§4 |
| `incline` | `route.incline_code` | ⚠ one taxonomy addition + one typo (§3/§4) |

### Hazards (MP booleans → `route_hazard` rows)

`abseil, traverse, boat, tidal, polished, loose, seepage, grassLegdes` →
codes of the same name (`grassLegdes`→`grassLedges`). Mapping already exists in
`enrich_from_multipitch.py`. Two notes:

- MP stores these as a mix of `true`/`1`/`"true"`/`null` — ingest must truthy-coerce.
- `tidal`, `seepage`, `loose` are safety-critical (evidence required by trigger).
  MP flags are human-curated, so ingest with
  `evidence_span = 'multi-pitch.com curated flag'`, `source_url` = the climb's URL.

### Approach & prose

| MP field | DB home | Status |
|---|---|---|
| `approachTime` | `route.approach_time_min` | ✅ |
| `approachDifficulty` | `route.approach_difficulty` | ✅ observed 1–3 = CHECK range |
| `intro` | `route.intro_html` | ✅ full HTML (current `mp-climbs.json` snapshot strips it — re-ingest) |
| `approach` | `route.approach_html` | ✅ full HTML |
| `pitchInfo` | `route.pitch_info_html` | ✅ verbatim HTML is the round-trip source of truth. Its `pitch-title`/`length`/`pitchGrade` spans are parseable into `pitch` rows later, but structured pitches are derived, not authoritative, until MP renders from them |

### Nested objects

| MP field | DB home | Status |
|---|---|---|
| `guideBooks[]` `.isbn .title .rrp .imgURL .link` | `guidebook` (`isbn, title, rrp, img_url, link`) | ✅ |
| `guideBooks[]` `.description .pg` | `route_guidebook` (`description, page`) | ✅ |
| `guideBooks[]` `.type` (`'guidebook'` \| `'PDF'`) | **nowhere** | ❌ the one true gap — add `guidebook.kind` (§3) |
| `references[]` (`text`, `url`) | `route_reference` | ⚠ prefix CHECK too strict (§3) |
| `weatherData` (`rainyDays/tempH/tempL` ×12) | `route_climatology` (12 rows) | ✅ |
| `mapImg` (`url, alt`, rarely `geo`) | `route.map_img` jsonb | ✅ opaque — nothing lost (id 28's extra `geo` key rides along) |
| `topo` (`url, alt, attributionText, atributionURL, dataFile`) | `route.topo` jsonb | ✅ opaque; preserve the `atributionURL` typo key so the site keeps working, or fix site + data together |
| `tileImage` (in `data.json` only) | `route.tile_image` jsonb | ✅ ingest from `data.json` |

### `data.json`

Every per-climb key in `data.json` (the 18-key summary) is a projection of
`route` + `area` columns — matches the `allClimbData: true` set in MP's
`cms-mapping.js`. `export_mp.py` regenerates it entirely; top-level
`lastUpdate` = export time.

### DB fields MP has no source for (stay NULL, curated later in the Studio)

`protection_code/style, belays, commitment_code, escapable, rack, rope,
bolts_count, descent_*, elevation_m, sun_window_code, wind_exposed,
best_season, stars, left_right_index`, discipline/feature/character tags,
structured `pitch` rows, `first_ascent`. These are the Studio's value-add on
top of the MP record — `export_mp.py` simply omits what MP's schema doesn't
render (until the site grows fields for them).

## 2 · Taxonomy additions (do in the Curation Studio → auto-exports 105 + taxonomy-values.json)

1. **rock**: add `phonolite` — used by id 15 (Durance). Notes: sound volcanic,
   fine-grained; behaves like fine rhyolite.
2. **incline**: add `Slab, Vertical & Overhanging` (full-range composite;
   sort_order 4, shifting `Vertical & Overhanging`→5, `Overhanging`→6).
   ⚠ `incline` is not yet a Studio-managed family (`TAXONOMY` dict in
   `curate.py`) — either add it there or seed via SQL.

No hazard, grade-system, aspect, or status additions needed — MP's observed
values are fully covered.

## 3 · Schema tweaks (new migration)

1. `guidebook` **add** `kind text NOT NULL DEFAULT 'guidebook' CHECK (kind IN ('guidebook','pdf'))`
   — homes MP's `guideBooks[].type`.
2. `route_reference.prefix` — MP references are mostly unprefixed free text
   (NULL prefix already passes the CHECK ✅) but observed prefixes include
   `Access Info` and `Accommodation` (sic: "Accomerdation"). Widen the CHECK to
   `('Video','Travel','Article','Info','Tides','Access','Accommodation')`;
   ingest parses `text` up to the first `:` when it matches, else prefix NULL.

## 4 · MP source cleanups (fix in multi-pitch repo before the final ingest)

| id | route | fix |
|---|---|---|
| 10 | Wreakers Slab | `rock: "Shale & Sandstone"` — single-valued `rock_code`: set `sandstone`, note the shale bands in prose/curation_notes |
| 15 | Durance | `originalGrade: 5.8` → `"5.8"` |
| 19 | Joy | `originalGrade: 5.7` → `"5.7"` |
| 21 | Gweilo via Topcat | `incline: "Slsb, Vertical & Overhanging"` → `"Slab, Vertical & Overhanging"` |
| 38 | Pinnacle Slab | `rock: "Qurtzite"` → `"Quartzite"` |
| 39 | Donkey Serenades | `rock: "Qurtzite"` → `"Quartzite"` |
| 45 | Australia West Face | delete stray duplicate `rockType` key |
| 51 | Rincón de Placa | `county: " Alicante"` — strip leading space |
| 53 | Aristotles | `county: " Alicante"`-style leading space — strip |
| 999 | Route Name | template/placeholder record — exclude from ingest (like `template.json`) |

Also normalise hazard flags stored as `"true"`/`1` to real booleans while
editing (ingest coerces anyway, but the files may as well be clean).

## 5 · Merge sequence

1. Apply §3 migration + §2 taxonomy additions.
2. Fix §4 records in the multi-pitch repo (one commit).
3. One **lossless** re-ingest (successor to `enrich_from_multipitch.py` /
   `mp-climbs.json`, which is stripped-HTML and skips guidebooks/references/
   images): full climb JSON + `data.json` `tileImage` → Postgres.
4. Write `export_mp.py`: Postgres → `website/data/climbs/<id>.json` + `data.json`,
   byte-stable against a freshly-ingested DB (round-trip test: ingest → export →
   `git diff` clean apart from the known normalisations).
5. From then on: edit in the Curation Studio, export, review diff, commit.
   god-mode becomes read-only legacy (or a field-capture tool whose JSON is
   imported as a draft).

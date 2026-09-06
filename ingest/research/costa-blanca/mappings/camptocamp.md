# api.camptocamp.org → crawl schema

**Verdict:** build-adapter, priority 3 — and the cheapest of the seven, because
**the adapter already exists** (`ingest/sources/camptocamp.py`). It needs a query
fix, not a new module.

**Licence:** collaborative guidebook documents (areas, waypoints, routes,
climbing sites, coordinates) are **CC BY-SA 3.0** — copy and modify with
attribution and share-alike, commercial use included. Personal documents
(outings, personal images, profiles) are **BY-NC-ND — skip them.**
**Robots:** no `Disallow` on the API host; the site publishes its own sitemap.
**Contact:** topo-fr@camptocamp.org (topo content), dev@camptocamp.org (API).

**Scale:** 65 rock/mountain routes across ~14 crags and summits in the Costa
Blanca bbox, plus 13 `climbing_outdoor` waypoints. **11 routes on Puig Campana.**
Small, but it carries alpine grades, equipment/exposure ratings and FA history
that neither UKC nor theCrag hold.

## The bug this fixes

An earlier Costa Blanca bbox run through this adapter found **nothing**, which
was read as "the source has no Spanish data". That was wrong. `plan()` queries

```
/waypoints?wtyp=climbing_outdoor&bbox=…
```

but **Puig Campana is `wtyp=summit`, not `climbing_outdoor`** — so the query
could never see it. The Costa Blanca's multi-pitch mountains are all summits
here; only the roadside sport venues (Sella, Toix, Guadalest…) are
`climbing_outdoor`.

**Fix:** query `wtyp=climbing_outdoor,summit`, and add a routes-first query that
does not depend on waypoint type at all:

```
/routes?act=rock_climbing,mountain_climbing&bbox=minx,miny,maxx,maxy&limit=100&offset=N
```

The routes endpoint returns `{total, documents[]}` and paginates on `offset`.
Verify against the tight Puig Campana box, which should return 24 routes (10 on
Puig Campana, the rest on Ponoig / Divino / Aran de Batistot).

Coordinates are EPSG:3857 web-mercator both ways — the existing adapter already
converts, keep that.

## Crag mapping — one crag per main waypoint

Group route documents by `main_waypoint_id` (list items carry `title_prefix`,
the crag or summit name).

| schema field | source | notes |
|---|---|---|
| `source` | `"camptocamp"` | |
| `source_id` | waypoint id | e.g. `359834` |
| `name` | `title_prefix` / waypoint `locales[].title` | "Puig Campana" |
| `lat` / `lon` | `geometry.geom` Point, mercator → WGS84 | |
| `url` | `https://www.camptocamp.org/waypoints/<id>` | |
| `country` | `"ES"` | from the `areas` chain |
| `region` | `areas[]` names | |
| `rock_type` | `rock_types[]` → taxonomy code | `calcaire`/`limestone` → `limestone` |
| `aspect` | `orientations[]` | already compass codes (`S`, `SW`) — a crag attribute, correct level |
| `description` | waypoint `locales[].description` + `.access` | fr/es/it; keep all locales verbatim |

## Route mapping

| schema field | source | notes |
|---|---|---|
| `source_id` | route id | |
| `name` | `locales[].title` | |
| `grade.value` | `rock_free_rating` | e.g. `"6b"` |
| `grade.system` | `"french"` | |
| `length_m` | `height_diff_difficulties` | metres of climbing |
| `pitches` | detail `route_length` / pitch count | `>= 2` derives `multi-pitch` |
| `stars` | `quality` | community rating |
| `bolts_count` | `None` | not a field |
| `protection` | `equipment_rating` (P1–P4) → `protection_grade` code | P1 ≈ `R`/runout, P4 ≈ `G`; map conservatively, `None` when unsure |
| `disciplines` | `act` + `climbing_outdoor_type` | `rock_climbing`→`sport`/`trad`, `mountain_climbing`→`alpine`; `aid` when `aid_rating` set |
| `fa` | `locales[].route_history` | |
| `url` | `https://www.camptocamp.org/routes/<id>` | |
| `description` | `description` + `summary` + `gear` + `remarks` (markdown) | verbatim |

**Ratings that have no schema field** — `global_rating` (D, TD+, ED−),
`exposition_rock_rating` (E1–E4), `engagement_rating` (I–VI),
`rock_required_rating`, `aid_rating` (A0–A5) — are exactly the alpine judgement
this source is worth having for. Prepend them to `description` as labelled lines
so the phase-2 LLM sees them; do not force them into `grade`.

## Images

`associations.images[{document_id, filename}]` are topo sketches on
`media.camptocamp.org`. Collaborative images are BY-SA, **personal images are
BY-NC-ND**. Record ids and filenames; check the per-image licence before any
download. **Skip `recent_outings` entirely** — outings are BY-NC-ND.

# multilargo.com → crawl schema

**Verdict:** build-adapter, priority 1. **Licence:** CC BY-SA 4.0 (terms §3).
**Robots:** content paths allowed, and `ClaudeBot`/`Claude-Web` are named in an
explicitly *allowed* block. **Contact:** info@multilargo.com.
**Scale:** 4,786 routes / 176 zones nationally; ~590 routes across ~18 zones
inside the Costa Blanca bbox; **49 routes on Puig Campana — the best single
source for it anywhere.** Multi-pitch only; no single-pitch sport crags.

The one caution in the terms is §4, "no *scraping masivo* or automated use that
degrades the platform". Keep `DELAY_S = 1.5`, crawl by province root rather than
the national sitemap, and cache payloads.

## Page model

| page | URL | holds |
|---|---|---|
| province index | `/escalada/alicante` | 20 zones + a 642-row route table (grade, length, pitches, sector, zone) |
| zone | `/zona/<slug>` | GPS, access prose, sector list, full route list |
| sector | `/sector/<zona>-<sector>` | rock type, approach time, croquis numbering |
| route | `/via/<slug>` | the ficha: per-pitch breakdown, FA, gear, descent, aspect |

All server-rendered Next.js — the route list, coordinates and prose are in the
HTML. Never touch `/api/` or `/croquis/` (robots-disallowed, and unnecessary).

**GPS is not in any index page.** Coordinates appear only on zone/sector/route
pages, as a Google Maps link (`?api=1&query=LAT,LON`), an OSM link
(`?mlat=LAT&mlon=LON`) and an OSM iframe `marker=LAT,LON`. So the zone page is
the bbox-pruning point: one fetch per zone, ~25 for the whole Costa Blanca if
you root at `/escalada/alicante` (+ `/valencia`, `/murcia`).

## Crag mapping — one crag per zone

`schema.crag(...)` from `/zona/<slug>`:

| schema field | source | notes |
|---|---|---|
| `source` | `"multilargo"` | |
| `source_id` | zone slug | e.g. `puig-campana` |
| `name` | `h1` | "Puig Campana" |
| `lat` / `lon` | Google Maps `query=LAT,LON` link | fall back to OSM iframe `marker=` |
| `url` | `https://multilargo.com/zona/<slug>` | |
| `country` | `"ES"` | constant for this source |
| `region` | province text beside `h1` | "Alicante" |
| `rock_type` | sector page "Caliza (…)" → `limestone` | taxonomy code; `None` if unmapped |
| `aspect` | `None` at zone level | aspect is per-route here ("Sol y sombra") |
| `description` | climate line + "Cómo llegar" + "Localización y accesos" (BASE / APROXIMACIÓN / DESCENSO) + intro | verbatim prose, phase-2 LLM input |

Zones map to crags, sectors to nothing structural — carry the sector name on the
route so the later merge can group. Per the sectors-are-independent ruling, a
second pass may promote each `/sector/` page to its own crag record; v1 does not.

## Route mapping — from the zone route list, enriched by `/via/`

Zone page rows are `<li class="card-link">` with a name span, a
`span.font-mono` grade badge, `"<n> m"`, `"<n> L"`, and a trailing
`a[href^="/sector/"]`.

| schema field | source | notes |
|---|---|---|
| `source_id` | via slug | from `a[href^="/via/"]` |
| `name` | first span | "Espolón Central" |
| `grade.value` | `span.font-mono`, **verbatim** | `"V"`, `"V+/A0"`, `"6a+/A0"` |
| `grade.system` | `"spanish_hybrid"` | Roman ≤ V+, French ≥ 6a, aid suffix `/A0`–`/A5`. Never convert — schema stores native |
| `length_m` | `"<n> m"` | int |
| `pitches` | `"<n> L"` | int; `>= 2` auto-appends `multi-pitch` in `schema.route()` |
| `stars` | `None` | the quality vote is a community field, usually "—" |
| `bolts_count` | `None` | not stated |
| `protection` | ficha "Protección" / "Compromiso" | map onto `protection_grade` codes; `None` if unmapped |
| `disciplines` | ficha "Material" / grade aid suffix | `trad` when gear-led, `sport` when bolted, `aid` when `/A0+`; `multi-pitch` is derived |
| `fa` | ficha "1ª ascensión" | |
| `url` | `https://multilargo.com/via/<slug>` | |
| `description` | "Descripción" prose + "Largos (desglose)" + "Descenso" + "Sol y sombra" | verbatim |

### `/via/` ficha fields worth keeping

`Grado (guía)`, `Libre`, `Longitud`, `Largos`, `Nº en croquis`, `1ª ascensión`,
`Compromiso`, `Material`, `Protección`, `Cuerda`; the per-pitch list
(`{n, grade, length_m, note, belay}`); the descent block (walking vs *n*
rappels); and "Sol y sombra" ("Sur · solana" → aspect `S`).

**Aspect belongs on the crag, not the route** (2026-09-05 ruling). Where
multilargo states a per-route facing, fold it into the crag record when the
whole zone agrees, and leave it in the route description otherwise.

## Croquis / topo images

`Croquis de referencia` is an **external link with a credit** (guiascumbre.com,
Diputación PDF fichas). Terms §6 says third-party croquis are linked with credit,
never rehosted. **Store the URL and the credit string; do not download the
image.**

## Attribution obligation

CC BY-SA 4.0 requires attribution and share-alike. Store the source URL per route
and per crag, and carry the credit line ("multilargo.com, CC BY-SA 4.0") into
anything published. The initial Alicante data is itself credited to the
Diputación de Alicante guide *Senderos de la Roca*.

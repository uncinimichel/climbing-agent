# enlavertical.com → crawl schema

**Verdict:** build-adapter, priority 2 — **but see the licence caveat below.**
**Robots:** the `view` pages we need are allowed; a long list of JSON/XML helper
endpoints is disallowed. **Contact:** contacto@enlavertical.com.
**Scale:** 107 escuelas / 325 sectors / 3,830 routes across the País Valencià;
~30–35 escuelas and ~500–600 routes inside the Costa Blanca bbox; **25 routes on
Puig Campana**, with per-pitch Spanish reseñas.

> **Licence caveat — ask before publishing.** The site has *no* terms page, no
> aviso legal and no stated licence (`/pages/aviso_legal` and `/pages/condiciones`
> both 404). Content is user-contributed under no declared rights. Robots permits
> the crawl, but reuse rights are unclear. Crawl into the private store if you
> like; **email contacto@enlavertical.com before any of it reaches the public
> site**, and keep the per-record "Reseñado por" contributor credit so the ask
> can name them.

Site is old (jQuery 1, Disqus, a Flash notice) — **decode every response as
`iso-8859-1`**, keep `DELAY_S = 1.5`, and never fetch Disqus.

## Page model

| page | URL | holds |
|---|---|---|
| province | `/provincias/view/1030` | unpaginated table, 107 rows → `/escuelas/view/<id>` |
| escuela | `/escuelas/view/<id>` | GPS, access, water, sleeping, sector table |
| sector | `/sectors/view/<id>` | **own GPS**, approach, rock, the route table |
| vía | `/vias/view/<id>` | per-pitch lines, equipment, FA, descent, ascents |

Province ids come from the `<select>` on any escuela page (País Valencià =
`1030`, Spain root = `/pais/view/73`). All pages are server-rendered; only maps,
Disqus and the pie charts are JS.

**Robots-disallowed — do not call:** `/escuelas/sectoresjson`,
`/escuelas/gradosviassector`, `/escuelas/subzonasxml`, `/sectors/listadoxml`,
`/*/listado*`, `/users/*`. Everything needed is in the `view` HTML.

Coordinates are in an inline script on both escuela and sector pages:
`var lat_cent=38.578…; var lon_cent=-0.208…;`. Prune the bbox at the escuela
page — one fetch per escuela, no coordinates on the index.

## Crag mapping — one crag per **sector**

Sectors carry their own GPS, their own rock type and their own approach, so a
sector is an independent place, matching the sectors-are-independent ruling and
UKC's granularity. The escuela becomes the grouping header, carried as `region`
context, not as a parent record with inheritance.

| schema field | source | notes |
|---|---|---|
| `source` | `"enlavertical"` | |
| `source_id` | sector id | e.g. `41` |
| `name` | sector name from the escuela's "Sectores (N)" table | prefix with the escuela when ambiguous |
| `lat` / `lon` | `lat_cent` / `lon_cent` on the sector page | escuela coords as fallback |
| `url` | `https://www.enlavertical.com/sectors/view/<id>` | |
| `country` | `"ES"` | |
| `region` | escuela name + province | "Puig Campana, Alicante" |
| `rock_type` | "Tipo de roca" → `{caliza: limestone}` | taxonomy code, `None` if unmapped |
| `aspect` | sector "Orientación" where stated | Spanish → compass (`Sur`→`S`, `Oeste`→`W`) |
| `description` | "Aproximación" + approach time + escuela intro + "Cómo llegar" + "Dónde dormir" + "Agua" | verbatim |

## Route mapping

The sector "Vías" table (`Nombre | Grado | Escalada | Orientación | Nº largos`)
already gives the full route list — the `/vias/view/` fetch is an enrichment
step, gate it behind a depth flag.

| schema field | source | notes |
|---|---|---|
| `source_id` | vía id | from `a[href^="/vias/view/"]` |
| `name` | Nombre | |
| `grade.value` | Grado, **verbatim** | `"V+"`, `"6c+/A2"` |
| `grade.system` | `"spanish_hybrid"` | Roman ≤ V+, French ≥ 6a; keep `/A0`–`/A2` in the value |
| `length_m` | "Longitud" on the vía page | sector table has no length |
| `pitches` | "Nº largos" | |
| `stars` | `None` | ascent "Apreciación" is per-user opinion, not a rating |
| `bolts_count` | `None` | |
| `protection` | "Equipamiento" | map onto `protection_grade` codes; `None` if unmapped |
| `disciplines` | "Escalada": `clásica`→`trad`, `deportiva`→`sport` | `multi-pitch` derived from pitches |
| `fa` | "Aperturista" | |
| `url` | `https://www.enlavertical.com/vias/view/<id>` | |
| `description` | lead paragraph + pitch lines + "Descenso" + "Material necesario" + "Enlaces externos" | verbatim |

Pitch lines parse with `r'L(\d+):\s*(\d+)m\s*\(([^)]+)\)'` — `L3: 45m (IV)` —
each followed by its own prose. That per-pitch Spanish reseña is the thing UKC
and theCrag do not have for these routes.

## Images

Thumbnails are `/img/imagecache/400x400_100_crop_<n>.jpg`, full size
`/img/uploads/<year>/<name>___<n>.jpg`. Given the unclear licence, **record the
URLs and do not download** until the rights question is answered.

## Attribution

Store `Reseñado por` (contributor username + `/users/view/<id>`) and the date on
every crag and route. Puig Campana content is mostly by user *Pau*
(`/users/view/12`), with *merli*, *hbarra* and *bayaedu*. Those names are who the
permission email is really addressed to.

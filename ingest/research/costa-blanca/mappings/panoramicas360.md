# panoramicas360.net → crawl schema

> **Built and running:** `ingest/sources/panoramicas360.py`. **49 routes** in the
> bbox, one crag record per post as designed (the keyed step folds them into one
> crag directory). The KML is fetched once in `plan()` and is the only source of
> coordinates, exactly as described below.

**Verdict:** build-adapter, priority 4. **Author:** Antonio García-Saúco Iglesias
("Pels"), Alicante, blogging since 2009; copyright holder of all text and photos.
**Contact:** enlacumbre@panoramicas360.net (plus a `/permisos/` page — read it
before publishing anything).
**Scale:** 110 long-route reseñas across 21 Alicante crags; ~65 routes on ~14
crags inside the bbox; **8 routes on Puig Campana**, written pitch by pitch.

This is one person's careful work, not a database. It is the highest-quality
prose of the seven and the most sensitive to attribution — treat the credit line
as mandatory, not optional.

## Three enumeration paths, all server-side

**(A) WordPress REST — the clean one, no auth:**

```
/wp-json/wp/v2/categories?per_page=100&page=1..2          # 194 categories
/wp-json/wp/v2/posts?categories[terms][]=33&categories[terms][]=23
    &categories[operator]=AND&per_page=100&page=N
    &_fields=id,link,title,date,categories                # X-WP-Total: 110
```

`33` = *vías largas*, `23` = *Alicante*. Per-crag children of 23:
`puig-campana` 121, `cabeco-dor` 122, `sierra-toix` 119, `penon-de-ifach` 120,
`penon-divino` 174, `sierra-helada` 135, `rincon-de-bonanza` 133, `sella` 128,
`morro-falqui` 127, `mascarat` 4928, `sierra-de-bernia` 124, `els-castellets`
134, `penya-roc` 157, `cabreras` 156. Brackets must go unescaped (`curl -g`).

**(B) Curated index** `/croquis-escalada/` — static HTML, `h2` per province,
`h3` per crag, `<a>` per route post. This is the cleanest crag→routes grouping.

**(C) Google My Maps KML — the only source of coordinates:**

```
https://www.google.com/maps/d/kml?mid=1q5DEp0THN39RhfET46WpcnumBpE&forcekml=1
```

439 placemarks in folders (Escalada, Alpinismo, Senderismo, Vía Ferrata…), each
with `<name>` (usually `Route (len m, grade)`), `<coordinates>` and a description
link back to the post URL. Fetch it once in `plan()` and stash it as its own
`{'kind': 'kml'}` item so the runner persists it.

> **The structured block is HTML-only.** `section.route-properties` is rendered
> by the theme from hidden custom fields — REST `content.rendered` does **not**
> contain it, and `meta`/`acf` are empty. So enumerate via REST, but **parse the
> page HTML**.

## Crag mapping — one crag per Alicante sub-category

| schema field | source | notes |
|---|---|---|
| `source` | `"panoramicas360"` | |
| `source_id` | category id | e.g. `121` |
| `name` | category name / `h3` on `/croquis-escalada/` | "Puig Campana" |
| `lat` / `lon` | **median of that crag's KML placemarks** | no per-crag coordinate exists |
| `url` | category archive link | |
| `country` / `region` | `"ES"` / `"Alicante"` | |
| `rock_type` | `None` | rarely stated as a field |
| `aspect` | only if every route agrees | otherwise leave to the crag record |
| `description` | "Aproximación" + "Acceso en coche" prose from member posts | verbatim |

Posts with no placemark inherit the crag centroid; a crag with no placemarks at
all is pruned rather than guessed.

## Route mapping — one route per post

From `section.route-properties` (`.route-properties__txt` → `.route-properties__value`):

| schema field | source | notes |
|---|---|---|
| `source_id` | WP post id | |
| `name` | `h1`/`og:title` stripped of the "Escalada en el X. Vía " prefix | or `r'(.+?)\s*\((\d+)\s*m,\s*([^)]+)\)'` |
| `grade.value` | "Dificultad", **verbatim** | `"V (un paso 6a+)"`, `"6b ó V+/A0"`, `"6c+/Ae"` |
| `grade.system` | `None`, or `"french"` when purely numeric | the author mixes Spanish Roman and French freely — do **not** normalise |
| `length_m` | "Longitud" | |
| `pitches` | "Nº largos" | derives `multi-pitch` |
| `stars` | `None` | |
| `bolts_count` | `None` | |
| `protection` | "Vía": `Limpia` / `Semiequipada` / `Equipada` | map onto `protection_grade` codes; `None` if unmapped |
| `disciplines` | same "Vía" field | `Limpia`→`trad`, `Equipada`→`sport`, `Semiequipada`→both |
| `fa` | `None` | rarely given |
| `url` | post link | |
| `description` | body sections + date + croquis URLs + Wikiloc link | see below |

`description` should concatenate the article's `h2`/`h3` sections —
*Aproximación*, *Acceso en coche*, *La escalada*, *Equipamiento*, *Descenso*,
*Conclusión* — plus "Actividad realizada el <date>", `Duración` and `Desnivel`,
then append the croquis image URLs (`img[src*=croquis|rese|topo]`) and any
`a[href*="wikiloc.com/rutas-escalada"]` as labelled `topo:` / `gps_track:` lines
for the phase-2 LLM.

## Rights

All rights reserved to the author. **Do not download or rehost images.** Record
URLs only, keep `source_url` and the byline on every record, and read
`/permisos/` before anything from here reaches the public site. A short email to
enlacumbre@panoramicas360.net is the right move given how much of the Puig
Campana detail comes from this one blog.

# mountainproject.com → crawl schema

**Verdict:** build-adapter, priority 6 — **for the sport crags only.**
**Owner:** onX Maps, Inc. **Permission:** already held (project decision — raw
data stays in the private store and never on the public site). Keep the email
trail; the onX TOU otherwise prohibits scrapers outright.
**Crawl-delay: 60 s** per robots.txt. Do not lower it without written agreement.

**Scale:** 383 Costa Blanca routes across 34 sub-areas — 16 trad, 369 sport.
**But only 1 route on Puig Campana**, 1 on Ponoig, 1 on Bernia, 8 on Peñón
d'Ifach, 2 on Mascarat.

## The point of this source, and its limit

MP is **deep on sport crags and empty on the multi-pitch mountains**: Sierra de
Toix 48, Bellús 45, Sella 44, Xaló 19, Vall de Guadar 17. That is genuinely
useful for the roadside days of a trip, and useless for Puig Campana. Build it
for the sport crags; do not expect it to carry the trip's main objectives.

**Do not touch** (robots-disallowed): `/ajax*`, the area map
(`/map/<id>` → `/ajax/public/area`), search suggestions, and the old `/data` API.
The sitemap index (1,345 children) has no geographic key — useless for a regional
plan. Everything needed is in the server-rendered area and route HTML.

## Enumeration — an area-tree walk

```
/area/106111770/spain
  → /area/107892167/valencia          (9 sub-areas, 780 climbs)
    → /area/106282611/costa-blanca    (34 sub-areas, 383 climbs)
```

On an area page: child areas are `div.lef-nav-row > a[href^=/area/]`, each with a
count suffix `trad / sport / toprope / boulder / ice / aid / mixed / alpine /
total` — skip children whose total is 0. Routes are rows of
`table#left-nav-route-table`.

**Bbox pruning:** MP areas carry a point, not a bbox. Prune only leaf-ish areas
(those with a route table and no children) on their own GPS; always expand the
parents. The tree is shallow and small, so this is cheap.

## Crag mapping — one crag per leaf area

| schema field | source | notes |
|---|---|---|
| `source` | `"mountainproject"` | |
| `source_id` | area id | e.g. `121988277` |
| `name` | area `h1` | |
| `lat` / `lon` | `table.description-details` → `r'GPS:\s*(-?[\d.]+),\s*(-?[\d.]+)'` | |
| `url` | `https://www.mountainproject.com/area/<id>/<slug>` | |
| `country` / `region` | `"ES"` / breadcrumb `div.mb-half a[href*=/area/]` | |
| `rock_type` | `None` unless the description states it | |
| `aspect` | `None` unless stated | |
| `description` | the `h2` *Description* div + *Getting There* div | verbatim; elevation from description-details |

## Route mapping

From the route table, enriched by the route page (gate that behind
`--max-routes` — at 60 s per fetch, 383 routes is over six hours).

| schema field | source | notes |
|---|---|---|
| `source_id` | route id | |
| `name` | `a[href^=/route/]` | |
| `grade.value` | `span.rateFrench` | store French as the grade |
| `grade.system` | `"french"` | keep `.rateYDS`, `.rateUIAA`, `.rateBritish`, `.rateEwbanks`, `.rateZA` in `description` as labelled lines — they are MP's own conversions, not source data |
| `length_m` | route page `Type:` row, e.g. "1500 ft (455 m)" | take the metric value |
| `pitches` | same row, "10 pitches" | derives `multi-pitch` |
| `stars` | `td.route-score` → count `img[src*=starBlue]` (+0.5 for Half); route page `#route-star-avg` "Avg: 3.8 from 8 votes" | |
| `bolts_count` | `None` | |
| `protection` | the `h2` *Protection* div → `protection_grade` code where it maps | `None` otherwise; keep the prose in `description` |
| `disciplines` | `span.route-type` classes: `Rock Trad`→`trad`, `Rock Sport`→`sport`, `TR`→`tr`, `Alpine`→`alpine` | `multi-pitch` derived |
| `fa` | route page `FA:` row | |
| `url` | `https://www.mountainproject.com/route/<id>/<slug>` | |
| `description` | *Description* + *Location* + *Protection* divs | verbatim |

The route page also carries a schema.org `ld+json` `LocalBusiness` block with
`geo.latitude`/`geo.longitude` and an image — a cleaner coordinate than the area
point when you need per-route position. NCCS commitment grade ("Grade III")
appears on the route page; keep it in `description`.

## Storage rule

Per the standing agreement covering theCrag, UKC and Mountain Project: **raw
scraped content stays in the private store and never reaches the public site.**
Only merged, curated judgement crosses that line.

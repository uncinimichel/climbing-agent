# multi-pitch.com → crawl schema

**Verdict:** build-adapter, priority 7 — small, trivial, and **first-party.**
This is Michel and Dan's own site (source at `github.com/dankni/multi-pitch`),
licensed **CC BY-SA 4.0**, own topo images CC BY 4.0.
**Contact:** multi-pitch@outlook.com.
**Scale:** 51 published climbs across 19 countries; **6 routes on 5 crags inside
the Costa Blanca bbox** — Puig Campana (Espolón Central, Aristotles), Peñón de
Ifach (Diedro UBSA, Vía Pany), Penya Roc (Dos Hermanos), El Castellet (Rincón de
Placa).

Its real value is not volume. It is a **self-consistency check**: these are
routes we have already curated by hand, so running them back through the crawl
and merge pipeline tests whether the pipeline reproduces our own judgement.

## Enumeration — one JSON file

```
GET https://www.multi-pitch.com/data/data.json
```

```json
{"lastUpdate": …,
 "climbs": [{"id", "routeName", "cliff", "country", "county",
             "status": "publish|draft", "originalGrade", "tradGrade",
             "techGrade", "gradeSys", "dataGrade", "length", "pitches",
             "geoLocation": "lat,lon", "approachTime", "approachDifficulty",
             "abseil", "tidal", "loose", "polished", "seepage", "traverse",
             "boat", "tileImage": {"url", "alt", "attribution"}}]}
```

Skip `status == "draft"`. Filter `geoLocation` by bbox client-side — there is no
server-side region query. Route page URL is
`/climbs/<slug(routeName)>-on-<slug(cliff)>/`; the slug keeps accented letters
(`espolón-central-on-puig-campana`), so percent-encode at fetch time with
`urllib.parse.quote(safe='/')` and fall back to matching against `sitemap.xml`
if a slug 404s.

Route HTML is fully server-rendered — grade, coordinates, pitch text and the
topo `<img>` are all in the raw HTML. `/js/main.js` only does filtering and the
Open-Meteo widget. Ignore the extended weather JSON on S3; we have our own.

## Crag mapping — one crag per cliff

| schema field | source | notes |
|---|---|---|
| `source` | `"multipitch"` | |
| `source_id` | slug of `cliff` | |
| `name` | `h1#articleTitle` text before `" - "` | "Puig Campana" |
| `lat` / `lon` | `ld+json` `@type: Place` → `.geo`; or average the cliff's routes | |
| `url` | the route page (no crag page exists) | |
| `country` / `region` | `country` / `county` | |
| `rock_type` | the second text node after the info rings, e.g. "Limestone" → `limestone` | |
| `aspect` | the first of those text nodes, e.g. "S" | already a compass code — a crag attribute, correct level |
| `description` | first `section` (overview) + `section#approachDescent` | verbatim |

## Route mapping

| schema field | source | notes |
|---|---|---|
| `source_id` | `climb.id` | |
| `name` | `h1#articleTitle` after `" - "` | |
| `grade.value` | `#grade` (`"HS 4c"`) **and** `originalGrade` (`"IV+"`) | store both; they are different systems, not a conversion |
| `grade.system` | `gradeSys`: `BAS`→`uk_adjectival_tech`, `UIAA`→`uiaa`, `FS`→`french`, `ALP`→`alpine`, `YDS`→`yds`, `N`→`norwegian` | |
| `length_m` | `#length` / `climb.length` | |
| `pitches` | `#pitches` | derives `multi-pitch` |
| `stars` | `None` | curated, not voted |
| `protection` | `None` unless the prose states it | |
| `disciplines` | `trad` (the site's whole premise) + `multi-pitch` | |
| `fa` | `None` | not a field |
| `url` | the climb page | |
| `description` | overview + approach/descent + `section#pitchesSection` | verbatim |

Pitches parse with `r'Pitch (\d+)(?: & (\d+))? ?– ?~?(\d+)m (\S+)'`.
`section#approachDescent` carries parking coordinates as bare pairs
(`-?\d+\.\d+,\s*-?\d+\.\d+`) — pull them out as a parking list, since they are
exactly the field ClimbingAway was flagged for having and most sources lack.
Flags (`abseil`, `tidal`, `loose`, `polished`, `seepage`, `traverse`, `boat`)
map onto hazard/feature taxonomy codes where they fit, and into `description`
where they do not.

## Attribution

CC BY-SA 4.0 both ways, so reuse is clean. **But some tile photos are
third-party Flickr** with `attributionText` / `atributionURL` fields in
`data.json` (note the typo in the second key) and an unstated licence — credit
those separately and do not assume BY-SA covers them.

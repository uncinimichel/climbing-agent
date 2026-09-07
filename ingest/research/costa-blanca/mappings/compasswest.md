# compasswest.co.uk → crawl schema

> **Built, and one claim below was wrong.** `ingest/sources/compasswest.py` runs
> and returns 8 crags on the Costa Blanca bbox with **0 routes** — deliberately.
> The route-mapping table further down assumed the descriptions PDFs carry a
> text route list. They do not: `new-campana.pdf` extracts 19.8k characters of
> access and history prose and *not one grade token*, because the route lines
> live in the topo images. A grade regex over that text returns pitch fragments
> ("1. 40m 1V.") and first-ascent sentences, so the adapter stores the verbatim
> text and topo URLs and leaves routes to the LLM/vision phase. Read the route
> table below as the target for that phase, not as something already mechanical.

**Verdict:** build-adapter, priority 5 — the only substantial **English-language**
topo set for the area. **Author:** Rowland Edwards (IFMGA guide, Compass West
International School of Rock Climbing, in Finestrat since 1986), who opened most
of these routes with his son Mark. **Contact:** info@compasswest.co.uk,
+34 965 878 790.
**Scale:** 14 crag blocks on `/topos/` plus ~4 article-PDF crags ≈ 17 free crags,
roughly 150–250 routes. **15 routes on Puig Campana.**

> **Rights.** No terms, privacy or copyright notice anywhere on the site, and no
> licence text in the PDFs. The "Free Topos" framing implies distribution intent,
> but this is a named author's guidebook work. Treat as **copyrighted**: crawl to
> the private store, and email info@compasswest.co.uk for permission and credit
> before any description or topo image reaches the public site. **Exclude
> `/shop/` and `/product/*`** — those are the paid guides.

## Shape of the source: it is PDFs

Static WordPress (Divi), everything server-rendered, no XHR. The route data does
**not** live in HTML — it lives in PDFs.

- **Index:** `/topos/` — 14 Divi blurb blocks, each with a crag title, a blurb,
  and `DOWNLOAD TOPO` / `More information` anchors. This is the reliable
  enumerator; `sitemap.xml` (340 URLs) does not list the PDFs.
- **PDFs:** `/wp-content/uploads/YYYY/MM/<name>.pdf` — some hrefs have a doubled
  `//`, normalise before fetching.
- **Sub-pages** holding several PDFs each: `/lomodeleon/` (4 topo JPGs +
  descriptions), `/penyaroc/` (circo, gallery, descriptions, topo),
  `/seacliff/` (ultimate-journey, descriptions, list, topo).
- **Articles:** `/articles/` — Absolutely Divino, Aguja Pilar, Xanadu, Monte
  Castellet, Serra Gelada, each linking a full-article PDF.

Respect the 2 s crawl delay.

## Crag mapping — a hand-entered coordinate table

There is no geo query and, apart from Puig Campana's in-PDF Garmin reference,
**no coordinates anywhere on the site.** The adapter needs a static
`CRAG_TABLE` mapping the 14 names to hand-entered lat/lon, rock and aspect, and
bbox-filters on that table:

| crag | rough position |
|---|---|
| Puig Campana W face | ≈ 38.590, −0.222 |
| Puig Campana S face | ≈ 38.588, −0.212 |
| Lomo de Leon, Penya Roc, Aguja del Pilar, Haunted Walls, Pleasure Domes | Guadalest / Sella valley |
| Toix sea cliffs | Calpe |
| Castellets N face | Finestrat |
| Bolulla, Dos Hermanos, Pen-y-Martinez | Marina Baixa |

`schema.crag`: `source="compasswest"`, `source_id` = the slug of the crag title,
`name` from the blurb `h`-tag, `lat`/`lon` from the table, `url` = `/topos/` or
the sub-page, `country="ES"`, `region="Alicante"`, `rock_type="limestone"`,
`aspect` from the table where the topo names a face, `description` = the Divi
blurb prose plus the PDF's access/approach text.

## Route mapping — PDF text extraction

Extract with `pypdf`; install `fontTools` to silence the CFF warnings.

| schema field | source | notes |
|---|---|---|
| `source_id` | `<pdf-stem>#<route-index>` | no stable ids exist |
| `name` | route header line in the descriptions PDF | |
| `grade.value` | verbatim, e.g. `"E2 5b"`, `"HVS"`, `"6c/7a"` | |
| `grade.system` | `"uk_adjectival_tech"`, or `"french"` when French-only | UK adjectival+tech primary, French sport or UIAA Roman in brackets |
| `length_m` | per-pitch and total metres | stated in the PDFs |
| `pitches` | pitch count | derives `multi-pitch` |
| `protection` | `None` unless stated | aid noted as `A0` |
| `disciplines` | `trad` by default for these routes; `sport` where the topo says bolted | |
| `fa` | often Rowland/Mark Edwards | keep verbatim |
| `url` | the PDF URL | |
| `description` | the route's PDF paragraph verbatim | |

**Scanned PDFs:** if extracted text is under ~100 characters (`divino.pdf` is
one), the PDF is images. Mark the payload for the LLM-vision/OCR path and emit
the crag with topo pages only — do not guess.

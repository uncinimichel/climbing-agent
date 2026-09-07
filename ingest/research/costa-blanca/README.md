# Costa Blanca / Puig Campana — source research

Which sources hold Costa Blanca climbing data, which we may crawl, and how to
enumerate each one. Two sequential workflow runs (2026-09-05, 2026-09-06)
evaluated **124 domains live** — every one was fetched, its robots.txt and terms
read, and its Puig Campana coverage counted by hand.

`evals.json` is the full record, one object per domain. This file is the summary
and the build order. `mappings/` holds one field-mapping document per
build-adapter source, binding its pages to the crawl schema in `ingest/schema.py`.

| verdict | count | meaning |
|---|---:|---|
| build-adapter | 7 | Licence and robots permit a crawl, and the source carries route or crag data worth the adapter. |
| metadata-only | 7 | Crawlable, but holds only coordinates/access/geometry — no route lists. |
| ask-first | 25 | Has real data, but terms, robots or copyright require written permission first. |
| prose-only | 57 | Trip reports and topo prose, no enumerable structure — later LLM extraction, not an adapter. |
| reject-after-verify | 1 | Rejected on verification. |
| reject | 27 | No climbing data (shops, hotels, hiking), dead, or bot-gated. |

## The finding

**Sources with real structured route data are far rarer than the domain count
suggests.** Of 124 domains, 7 are worth an adapter and 57 are Spanish-language
blogs holding good topo prose with no enumerable structure. The Costa Blanca is
documented mostly in narrative, by locals, in Spanish and Valencian.

The two big English databases under-serve exactly what this trip needs. Mountain
Project has 383 Costa Blanca routes but only **1** on Puig Campana — its coverage
is sport-crag deep and multi-pitch-mountain empty. The multi-pitch classics live
on Spanish sites: multilargo (49 Puig Campana routes), enlavertical (25),
camptocamp (11), panoramicas360 (8).

## Build these, in this order

> **All seven are built** (2026-09-07) and live in `ingest/sources/`. What they
> actually returned on the Costa Blanca bbox, rather than what the research
> estimated, is in the run table at the bottom of this file. Two estimates did
> not survive contact: Compass West yields **0** routes mechanically (they are
> inside the topo images, not the PDF text), and camptocamp yields far more than
> expected once the `wtyp=summit` bug is fixed.

| # | source | Puig Campana routes | Costa Blanca scale | render | why it earns the adapter |
|---|---|---:|---|---|---|
| 1 | [multilargo.com](https://multilargo.com) | 49 | ~590 routes / ~18 zones in bbox | static-html | The densest multi-pitch croquis database in Alicante, and the single best Puig Campana source anywhere. Multi-pitch only. |
| 2 | [enlavertical.com](https://enlavertical.com) | 25 | ~500-600 routes / ~30-35 escuelas | static-html | Broadest crag coverage of the region, static HTML, sector-level route tables. |
| 3 | [api.camptocamp.org](https://www.camptocamp.org) | 11 | 65 routes / ~14 crags + 13 waypoints | json-api | Documented JSON API, CC BY-SA, alpine grades and FA history nobody else carries. Adapter already exists — fix its query. |
| 4 | [panoramicas360.net](https://panoramicas360.net) | 8 | ~65 routes / ~14 crags in bbox | static-html | One local author's 110 long-route reseñas, with pitch-by-pitch detail. |
| 5 | [compasswest.co.uk](https://compasswest.co.uk) | 15 | ~150-250 routes / ~17 free crags | mixed | English-language topos with access and approach prose, from a school that has worked the area for decades. |
| 6 | [mountainproject.com](https://mountainproject.com) | 1 | 383 routes / 34 sub-areas | static-html | Permission already held. Sport-crag depth, near-zero multi-pitch — take it for the sport crags only. |
| 7 | [multi-pitch.com](https://multi-pitch.com) | 2 | 6 routes / 5 crags (our own site) | static-html | Our own curated pages; trivially crawlable, useful as a self-consistency check. |

### Grade systems these emit

Grades are stored verbatim with a system tag and never converted
(`ingest/schema.py`). What each source writes:

| source | grade system as written |
|---|---|
| multilargo.com | Spanish guidebook hybrid: Roman numerals up to V+ (II, III+, IV, IV+, V, V+), French numerals from 6a upward (6a, 6a+, 6b+, 6c+, 7a, 8c+), with aid suffix where relevant ("V+/A0", "6a+/A0", "7a/A1", "II – A5"), occasionally range "IV/III+". Route pages give both 'Grado (guía)' and 'Libre' (free grad… |
| enlavertical.com | Spanish hybrid: UIAA-style Roman numerals for <=V+ (III+, IV, IV+, V, V+) and French numeric from 6a upward (6a+, 6b+, 6c, 6c+, 7a+), optional aid suffix (V+/A0, 6c+/A2). Per-pitch grades in the same system: 'L3: 45m (IV)'. No E-grades, no ranges. |
| api.camptocamp.org | French free grade (rock_free_rating e.g. '6b', rock_required_rating '6a') + alpine global rating (D, TD+, ED-) + aid A0/A1 + equipment P1–P4 + exposition E1–E4 + engagement I–VI. Store as {'value':'6b','system':'french'}; keep global/equipment ratings as separate fields or in description. Pitch coun… |
| panoramicas360.net | Mixed Spanish/French as the author writes it: Spanish Roman numerals for classic grades (IV+, V, V+) and French numeric for harder (6a, 6a+, 6b, 6b+, 6c+), sometimes combined 'V (un paso 6a+)', '6b ó V+/A0', '6c+/Ae'. Store verbatim with system=None (or 'french' when purely numeric, 'spanish_roman'… |
| compasswest.co.uk | UK adjectival + technical (E1-E4, HVS, VS, VD, 5a-6a) as primary, with French sport grade (5+, 6a-7a+) or UIAA roman (1V-, V, V+) in brackets; a few routes French-only (Spellbound 6c/7a per pitch, Corazón en la Roca 7a+). Lengths in metres per pitch and total. Aid noted as 'A0'. |
| mountainproject.com | YDS primary with automatic conversions shown per route: French (5b), Ewbanks (16), UIAA (VI-), ZA (15), British (HVS 4c); NCCS commitment grade (Grade III) on route page; stars 0-4 with vote count. |
| multi-pitch.com | Dual: British adjectival+tech (BAS) shown on page (HS 4c, HS 4b) and UIAA in data.json originalGrade/gradeSys (IV+, V); per-pitch grades in prose are UIAA (IV, IV+, V). Site notes Spanish topos grade Espolón Central V+. Other sites' routes use FS (French), ALP, YDS, N (Norwegian). |

### Mapping documents

One per build-adapter source, in `mappings/`. Each binds that source's pages
to the crag and route fields of `ingest/schema.py`, with the enumeration path,
the grade system, the licence obligation and real Puig Campana examples — enough
to hand-write the adapter without re-researching the site.

| source | mapping doc | licence position |
|---|---|---|
| multilargo.com | [`mappings/multilargo.md`](mappings/multilargo.md) | CC BY-SA 4.0; robots explicitly allows ClaudeBot |
| enlavertical.com | [`mappings/enlavertical.md`](mappings/enlavertical.md) | **No licence stated anywhere — ask before publishing** |
| api.camptocamp.org | [`mappings/camptocamp.md`](mappings/camptocamp.md) | CC BY-SA 3.0 for guidebook docs; outings are BY-NC-ND, skip |
| panoramicas360.net | [`mappings/panoramicas360.md`](mappings/panoramicas360.md) | All rights reserved, one author — ask, credit, never rehost images |
| compasswest.co.uk | [`mappings/compasswest.md`](mappings/compasswest.md) | No notice; named author's guidebook work — treat as copyrighted |
| mountainproject.com | [`mappings/mountainproject.md`](mappings/mountainproject.md) | Permission held; raw stays private. Crawl-delay 60 s |
| multi-pitch.com | [`mappings/multi-pitch.md`](mappings/multi-pitch.md) | First-party (ours), CC BY-SA 4.0 |

> **One concrete bug found.** `ingest/sources/camptocamp.py` queries
> `wtyp=climbing_outdoor` only, but Puig Campana is `wtyp=summit` — which is why
> an earlier Costa Blanca bbox run through that adapter returned nothing and was
> misread as "the source has no Spanish data". See `mappings/camptocamp.md`.

## Metadata-only — coordinates and access, no route lists

These fill gaps the route databases leave: where to park, what the sector
geometry is, whether the crag is closed for nesting.

| source | licence / access | what it uniquely adds |
|---|---|---|
| climbingaway.fr | mixed | vs UKC/theCrag: (1) PARKING GPS as a separate field (38.582199,-0.211846) plus crag GPS (38.589516,-0.206379) — UKC/theCrag give only crag point; (2) structured metadata fields: aspect S, altitude 700 m, approach '60 min… |
| clubescaladacostabla.blogspot.com | static-html | Official-ish access/closure notices for Alicante province crags (Cabeçó d'Or dynamic nesting regulation with per-sector open/closed lists and dates for 2022-2026; Aixorta, Serra Gelada, Biar/Frare, Toix Penya del Corb, S… |
| femecv.com | static-html | Authoritative federation-level crag metadata that UKC/theCrag lack or crowdsource: official access directions (Font del Molí parking for Pared Sur; Camí de la Serra branch for Pared Oeste), water source, local medical/Gu… |
| libreriadesnivel.com | static-html | Only structured guidebook bibliography for the Costa Blanca: identifies the two dedicated paper guides ('Escaladas en el Puig Campana', Manolo Pomares 2003, 240 pp, still in stock 10 EUR; 'Costa Blanca climbs', Roberto L… |
| oblyk.org | mixed | Essentially none for Costa Blanca versus UKC/theCrag: 1 route at Puig Campana (UKC/theCrag have dozens of multi-pitch lines), 12 at Pena Roja. Only distinguishing points: an explicit ODbL/CC BY-NC-SA licence (no permissi… |
| openstreetmap.org | json-api | Only source giving precise cliff/sector GEOMETRY (ways, not just a point): 12 named Sella sector cliff-ways (Final, Ojo de Odra, Competición, Techo del Rino, El Cajón de los Cuartos, Marión, Culo de Rino, Cabeza de Rino… |
| overpass-api.de | json-api | Only source giving machine-readable, openly-licensed GPS for crags AND sector outlines (e.g. Sella's 9 named cliff ways: Final, Ojo de Odra, Competición, Techo del Rino, Cajón de los Cuartos, Marión, Culo de Rino, Cabeza… |

## Ask first — real data, permission required

Each of these has usable data behind a term, a robots rule or a copyright that
needs a written yes. Contacts are the ones the research found live.

| source | what it holds | who to ask |
|---|---|---|
| 27crags.com | Low vs UKC/theCrag for Puig Campana: only 9 routes (Espolón Central x3 variants, Diedros Mágicos x2, Linea Magica, El Diamante, Fisura Neolítica, Pand… | support@thetopo.com (official support/removal address); tim@thetopo.com (Tim De Mazière, Key Account Manager f… |
| 8a.nu | Community ascent-log data that UKC/theCrag do not have: consensus (voted) grades and star ratings from 8a.nu ticks, ascent counts per route (popularit… | support@vertical-life.info (general, decoded from vertical-life.info/en/pages/about and /legal); press@vertica… |
| ayto-finestrat.es | Only the official access layer that UKC/theCrag lack: Font del Molí car-park and approach-path works (2026), PR-CV 289/289.1 trail signage, planned re… | contacta@finestrat.org (general, from footer), tel +34 965 878 100; tourism office touristinfo@finestrat.org,… |
| calameo.com | A 2006 first-person club-magazine account ('Amor de Odio') of climbing Puig Campana — historical narrative, possibly route description/topo sketch of… | No email on Calaméo. Options: (1) Calaméo account page https://www.calameo.com/accounts/7660601 (login-only me… |
| climber.co.uk | Essentially none for Puig Campana. For the wider Costa Blanca the only asset is Rich Mayfield's 2019 feature with DMS GPS for ~9 lesser-known crags (S… | info@climber.co.uk (footer, obfuscated as info_AT_climber_DOT_co_DOT_uk); contact form at https://www.climber.… |
| climbmaps.com | Bolter-authored topos (photo + painted lines) for a handful of Spanish sport crags, notably very dense Siurana (1.6k routes) and Chulilla (1.4k routes… | support@climbmaps.com (login page: "Email to support@climbmaps.com to achieve edit mode"); register.php for an… |
| desnivel.com | Names of the routes a 400-first-ascent local (Manolo Pomares) and José Martín Anaya consider the best on Puig Campana (Diada del País Valencià, Esperó… | redaccion@desnivel.com (editorial team), digital@desnivel.com (web), editorial@desnivel.com, info@desnivel.com… |
| es.scribd.com | The 2010 Diputación guide is the canonical Spanish reference for Alicante classic/multi-pitch: 48 Puig Campana routes with length (80-900 m), grade, t… | No contact on Scribd beyond the uploader profile pages (no email). Write to the rights holder: Diputación de A… |
| es.wikiloc.com | Vs UKC/theCrag: (a) real GPS tracks of the approach, pie de vía, belay stations (R0-R9 waypoints with elevations) and descent for the big Puig Campana… | Terms page states 'Puedes ponerte en contacto con Wikiloc en la dirección de correo electrónico' but the addre… |
| facebook.com | Near zero vs UKC/theCrag: live conditions/partner chatter, rescue reports (Vía Julia incident), occasional first-ascent history and 'línea mágica' lin… | No email exposed logged-out. Contact via Facebook itself: message the group admins from a logged-in account (g… |
| guiaspedrizamania.com | Per-route 'ficha técnica' table with fields UKC/theCrag lack or leave empty: first ascent (Historia), aspect (Orientación), pitches+length, gear list… | info@guiaspedrizamania.com ; +34 613 050 741 (from /contacto/) ; contact form https://guiaspedrizamania.com/co… |
| instagram.com | Potentially fresh, first-hand condition/beta notes and photos from local climbers and guides (recent ascents, fixed-gear state, access changes) that U… | Instagram DM to @jonathansanchezruiz (requires the owner's own IG account); no email or website visible in ser… |
| parquesnaturales.gva.es | Official access/regulation prose only: Penyal d'Ifac north-face climbing ban April-June (nesting), Ifac ascent hours; guided-walk notices for the Pais… | Per-park mailboxes on the site: serragelada@gva.es (covers Puigcampana-Ponotx), parque_lamata@gva.es etc.; Ser… |
| polop.org | Almost none vs UKC/theCrag. Only: (a) official Polop-side walking approach to Coll de Pouet / summit (Margotx via Camí del General from La Alberca, or… | ayto@polop.org; tel 965 870 150 (also 965 870 240); Avda. Sagi Barba 34, 03520 Polop de la Marina; contact for… |
| reddit.com | First-hand recent trip-report prose (time taken, descent in the dark, scrambling, Edwards Finish variant) and informal grade/condition chatter that UK… | Platform: Public Content Policy 'ask us' link / https://support.reddithelp.com (Submit a request), r/reddit4re… |
| rocjumper.com | Spanish-language first-person reseñas of multi-pitch routes and canyons with grade/obligatorio/length and approach prose, plus per-post maps (probably… | Website contact form on www.rocjumper.com (snippet: 'Respondo en cuanto sea posible. He leído y acepto la polí… |
| rockfax.com / rockfax.digital | Rockfax-curated selection and buttress structure for Puig Campana (Aguja Encantada 13, Vía Julia Pillar 9, Diedros Mágicos Area 9, Espolón Central 4,… | rockfax.digital contact form is login-gated (/my_account/contact_us -> redirects to /login_sign_up). rockfax.c… |
| rockfax.digital | Guidebook-curated data that UKC logbook / theCrag do not carry in this form: (1) Rockfax buttress grouping and topo ordering (5 sectors: Espolon Centr… | No public email on rockfax.digital; 'contact us' links go to /my_account/contact_us which requires login. Use… |
| scribd.com | The uploaded guidebook excerpt has a complete numbered list of 48 Puig Campana routes by sector (Oeste 1–12, Aguja Encantada 13–24, Sudoeste 25–29, Ce… | No author email on Scribd; uploader profiles have no messaging. Scribd itself: support via https://support.scr… |
| senders.femecv.com | Zero climbing content — no crag names, no routes, no grades, no topos. Unique vs UKC/theCrag: official, quality-controlled approach-trail data with GP… | Contact form https://senders.femecv.com/es/contacto/index; emails oficina.valencia@femecv.com (Sede València,… |
| terratrem.com | Practically none. The Puig Campana page contains a 2-sentence description (1,410 m, Marina Baixa, semi-equipped adventure routes on good limestone, up… | info@terratrem.com; tel +34 660 666 811; Instagram/Twitter/Facebook @terratremclimbing; contact form on each g… |
| thetopo.com | vs UKC/theCrag: (1) crag-level GPS + access_status/access_info prose for all 76 Costa Blanca crags in one JSON blob (Peñón de Ifach etc. have real acc… | support@thetopo.com (official); tim@thetopo.com (Tim De Mazière, Key Account Manager — customer success, topo… |
| treeline.es | First-person, pitch-by-pitch Spanish reseñas of Puig Campana multi-pitch routes written by a professional guide (TD2/TD3 climbing instructor), includi… | info@treeline.es (mailto link in header/footer and stated as 'Correo electrónico' in Aviso Legal and Términos)… |
| valenciaclimb.com | Low but non-zero, and not route data. UKC and theCrag both already carry Puig Campana far more completely (dozens of routes with pitch-by-pitch grades… | Email info@valenciaclimb.com (named in the aviso legal as the official notification address). Phone/WhatsApp (… |
| wikiloc.com (ca./es./www. subdomains) | Not a route database: no per-crag route lists, no structured grades. Value vs UKC/theCrag is (a) crowd-sourced GPS tracks of the approach (Font del Mo… | About page https://es.wikiloc.com/wikiloc/about-us.do (link present in index HTML, page itself Cloudflare-bloc… |

> **27crags / thetopo.com are the same company.** Their terms forbid scraping
> outright and their robots.txt names `anthropic-ai` and `Claude-Web` directly.
> Nothing from them without a written yes to support@thetopo.com.

## Prose-only — the LLM extraction layer, not adapters

57 domains carry Puig Campana topo prose, trip reports and pitch descriptions
with no enumerable index. These are input for a later extraction pass, one page
at a time, not a crawl. The richest of them:

- **manolopomares.webnode.es** — Primary-source material from the man who opened most of the Puig Campana routes: original first-ascent dates and party (e.g. Pell Bruna 02/2010 M. Pomares & D. Ruiz; Préstame Otra Uña 03/1995 Chorro-Pomares), per-pitch length+grade breakdowns (Recorrido: L1 20…
- **lanochedelloro.es** — Low for Puig Campana: only 3 topos (La danza de la lluvia + Diedro de las sirenas on one sheet plus a photo-topo, Matar o morir by M. Bernabeu, Rompededos) – modern/obscure lines that UKC/theCrag may lack, but no classics. Value is the hand-drawn pitch-by-pitc…
- **fjalejandre.blogspot.com** — Pitch-by-pitch first-hand beta for 4 Puig Campana classics that UKC/theCrag only list as a name+grade: Espolón Central (440 m, 8 largos, V, D+; 8 pitch grades IV to V, gear notes, escape via Directísima/Julia rappels, 40 min approach from Font del Molí, 1h30 d…
- **costablancaclimbing.com** — Puig Campana: El Moro (D. Morrod 1988, ~10 pitches VDiff, mountaineering line right of descent gully) with a topo photo (images/ElMorro.jpg) - rarely documented elsewhere; first-hand Espolón Central approach (Finestrat 'Font de...' road, hairpin parking, 'Espo…
- **ressenyes.joanjover.cat** — Hand-drawn pitch-by-pitch topos (croquis) by an experienced UIAGM guide, including an SE-face photo of Puig Campana with lines; UKC/theCrag have route lists but no pitch topos. Good candidate for the guidebook/topo-editor feature (with permission) and for LLM-…
- **rocacalenta.com** — For Puig Campana: one very careful first-hand write-up of Espolón Central (FA 18/3/1965 Torregrosa/Gascón/Roig, S-facing, approach 45 min / climb 5 h / descent 1 h 30, rack '10 quickdraws, nuts, 2 slings for threads, cams to Camalot #3', descent via cabled pat…
- **costa-vertical.com** — Vs UKC/theCrag: (1) first-hand pitch-by-pitch reseña of Diedros Mágicos (bolted hanging belay P1, old pitons P3, roof on P5, 3-abseil descent) — good description/access colour; (2) La Moleta (Sella) is developed and bolted by the site owner Tony Pearson himsel…
- **hikr.org** — Nothing structural beyond UKC/theCrag (which hold the full Puig Campana route lists). What hikr adds is first-person German-language beta with waypoints: for Espolón Central a precise approach from Font del Molí, how to recognise the start (painted 'EP Central…

Full list in `evals.json` (`verdict == "prose-only"`).

## Rejected

`cms.smartcostablanca.com (+ index/API on www.senderosdealicante.com and cmsapi.smartcostablanca.com)`, `albert.dufour2.free.fr`, `api.openbeta.io`, `cembenidorm.es`, `christianpau.blogspot.com`, `climbing-guide.eu`, `climbinvalencia.com`, `danielmurmarin.blogspot.com`, `deportesariadna.com`, `elrefugiodeportes.com`, `escaladaymas.com`, `explore-share.com`, `fedme.es`, `fmrm.net`, `getoak.app`, `herrstrathmann.de`, `hoteldonpancho.es`, `lacotorradelavall.blogspot.com`, `mediambient.gva.es`, `needlesports.com`, `oliunid.es`, `overpass.private.coffee`, `pasoclave.com`, `picuco.com`, `refugiomarnes.com`, `ro-spain.com`, `senderovertical.com`, `thealpiniashop.com`

Shops, hotels, guiding brochures, hiking portals, dead sites and bot-gated
endpoints. `api.openbeta.io` is rejected here for the same reason it was
rejected globally: it is effectively US-only.

## Open gaps

The run-1 critic named five gaps. Run 2 closed most of them — the Catalan and
Valencian corpus, the German-language angle, OSM/Overpass, ClimbingAway, FEMECV,
27crags and manolopomares were all evaluated in the second pass. What remains:

- **Document hosts were never enumerated.** Calaméo and Yumpu hold scanned club
  magazines and guidebook catalogues with Puig Campana articles. Ask-first, and
  no one has listed what is actually in them.
- **web.archive.org was never queried properly.** `costablancaclimbing.com`
  needs a CDX domain listing, not a guessed URL.
- **`cms.smartcostablanca.com` is marked `reject-after-verify`** while three
  finder notes call it a real route source. Worth one more look.
- **The verify, critic and synthesis stages never ran on run 2.** These 84
  second-pass evaluations are single-agent judgements with no refuter pass.
  Treat the run-2 verdicts as provisional; run-1 verdicts carry votes.

## Provenance

Recovered 2026-09-06 from the sequential workflow task outputs
(`wdtton8j5`, `w35wdm29w`, `wxuajsdc4` for run 1; `wgf773lkd`, `w5q2a86k1`,
`wgsx2cubj` for run 2), deduped by domain, richer record winning. Each eval
carries `_run` and `_src` naming where it came from. The workflow returned this
as JSON and wrote nothing to disk; the outputs lived in `/tmp` and would have
been lost.

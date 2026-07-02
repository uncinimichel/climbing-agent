# References & Authorities — Data & Taxonomy

The people, books, encyclopedias, and standards that the climbing taxonomy is built on.
Use these to justify enum choices, resolve disputes, and cite the origin of a grade system
when tagging a route. Every claim in [`taxonomy.md`](taxonomy.md),
[`grade-conversion.md`](grade-conversion.md), and
[`condition-algorithm.md`](condition-algorithm.md) should trace back to something here.

> **Why this exists:** the vision's Phase-2 Taxonomy Engine must map messy prose onto a
> *defensible* standard. "Defensible" means grounded in the recognised authorities below,
> not invented. Grade conversions are approximate by nature — cite the source and say so.

## Standard reference works (the canon)

| Work | Author / body | Why it's authoritative |
|---|---|---|
| **Mountaineering: The Freedom of the Hills** | The Mountaineers (Seattle); 1st ed. 1960, now 10th ed. | *The* definitive instructional text for 60+ years across 10 editions — the baseline for technique, systems, and terminology. |
| **The Climbing Dictionary** | Matt Samet (2011) | The authoritative lexicon of climbing terms and slang — the reference for *what a word means*. Samet edited Climbing magazine. |
| **UIAA — "The Scales of Difficulty in Climbing"** | G. Mandelli & A. Angriman (UIAA) | The international federation's own comparative study of every grading scale ([PDF](https://www.theuiaa.org/documents/sport/THE-SCALES-OF-DIFFICULTY-IN-CLIMBING_p1b.pdf)). |
| **BMC grade guidance** | British Mountaineering Council | The governing body's canonical explanation of the UK trad two-part grade ([link](https://www.thebmc.co.uk/en/a-brief-explanation-of-uk-traditional-climbing-grades)). |
| **theCrag / UKClimbing / Mountain Project** grade tables | community databases | Widely-used cross-system conversion tables — practical, if approximate. |

## Grade systems — origins & originators

Each system, who created it, and when. Cite these in `grade-conversion.md`.

| System (`gradeSys`) | Originator(s) | Date | Notes |
|---|---|---|---|
| **First difficulty scale** | **Fritz Benesch** (Austria) | 1894 | Seven levels; the first known grading system. |
| **Welzenbach scale → UIAA** | **Willo Welzenbach** (Germany) | 1923; UIAA formalised 1967 | Roman numerals I–VII, later open-ended (VIII+…XII+). The root of the Alpine/UIAA (`UIAA`) system. |
| **British adjectival (`BAS`)** | **Owen Glynn Jones** & successors | 1890s | The M/D/VD/S/VS/HVS ladder; the open-ended **E-grade added in the 1970s**. |
| **Yosemite Decimal System (`YDS`)** | **Royal Robbins, Don Wilson, Chuck Wilts** at Tahquitz Peak, CA | early **1950s** | Decimal subdivision of the Sierra Club's Class 5 (Sierra Club adopted Classes 1–5 in **1936**). First published in Wilts's 1956 Tahquitz guide. |
| **Ewbank (Australian)** | **John Ewbank** | 1967 | Numbers only (1–35+); factors exposure, length, rock, protection. Used in AUS/NZ/RSA. |
| **French Alpine (`ALP`, IFAS)** | **Lucien Devies** & the Groupe de Haute Montagne | proposed 1943, formalised 1967 | Adjectival commitment: F · PD · AD · D · TD · ED (+ ABO). |
| **French sport (`FS`)** | popularised by **François Labande** | late 1980s | Arabic + a/b/c + `+` (e.g. `6a+`, `9c`). |
| **Protection / danger ratings** | **Jim Erickson** | **1980** | G / PG / PG-13 / R / X suffixes — borrowed from the **American movie-rating system**. |
| **V-scale (bouldering)** | **John Sherman** ("Verm") | 1991 | Out of scope here (bouldering), listed for completeness. |

## Condition / rock science (for the Predictive Condition Algorithm)

Backs the friction/drying/seepage model in [`condition-algorithm.md`](condition-algorithm.md).

- **Friction is mostly about skin, not rock temperature.** A rock's coefficient of friction
  barely moves with ambient temperature; what changes is *sweat* — skin grips best when
  cool (roughly 0–5 °C skin temperature). So "good friction" ≈ cool + dry + low humidity.
  ([Climbing.com — friction science](https://www.climbing.com/skills/learn-this-friction-science/))
- **Rock type matters for grip and drying.** Hand-on-rock friction is higher on sandstone
  (~0.74) than limestone (~0.64); poorly-cemented granite/sandstone shed grains that act
  like ball-bearings. ([Tribonet](https://www.tribonet.org/news/friction-the-key-to-rock-climbing/))
- **Humidity prolongs drying; sun and wind accelerate it.** A surface can look dry while the
  rock beneath is still wet. ([Gripped](https://gripped.com/profiles/understanding-rock-climbing-conditions/))
- **Wet sandstone is dangerous and must not be climbed.** Porosity can exceed 20 %; water
  fills the pores, drops inter-grain friction, and cracks propagate far faster when humid —
  holds break. This validates the `sandstone` note in [`taxonomy.md`](taxonomy.md).
  ([Climbing.com — wet sandstone](https://www.climbing.com/travel/wet-sandstone/) ·
  [MadBoulder](https://www.blog.madboulder.org/understanding-wet-sandstone/))

## How to use these when tagging

1. **Attribute the grade system** — store `gradeSys`, and when in doubt about conversion,
   defer to the UIAA study / theCrag table and mark the value approximate.
2. **Infer protection from the grade pairing** (UK trad) — see the "typical pairing" rule in
   [`grade-conversion.md`](grade-conversion.md); a high technical grade relative to the
   adjectival implies a *well-protected single hard move*, a low one implies *serious or
   sustained* — a cheap prior for the `protection` field.
3. **Terminology** — resolve ambiguous words against Samet's *Climbing Dictionary*.
4. **Never assert equivalence** — grades weight danger, sustained difficulty, and crux
   differently across systems; `dataGrade` is a sortable proxy, not an equivalence claim.

## Sources

- [Grade (climbing) — Wikipedia](https://en.wikipedia.org/wiki/Grade_(climbing))
- [Yosemite Decimal System — Wikipedia](https://en.wikipedia.org/wiki/Yosemite_Decimal_System)
- [BMC — UK traditional climbing grades](https://www.thebmc.co.uk/en/a-brief-explanation-of-uk-traditional-climbing-grades)
- [UIAA — The Scales of Difficulty in Climbing (PDF)](https://www.theuiaa.org/documents/sport/THE-SCALES-OF-DIFFICULTY-IN-CLIMBING_p1b.pdf)
- [theCrag — Grades and Grade Conversions](https://www.thecrag.com/en/article/grades)
- [Mountain Project — International Grade Comparison](https://www.mountainproject.com/international-climbing-grades)
- [Mountaineering: The Freedom of the Hills — The Mountaineers](https://www.mountaineers.org/books/books/mountaineering-the-freedom-of-the-hills-10th-edition)
- [The Climbing Dictionary — Matt Samet (review)](http://www.traditionalmountaineering.org/Book_MattSamet.htm)
- [Climbing.com — friction science](https://www.climbing.com/skills/learn-this-friction-science/) ·
  [wet sandstone](https://www.climbing.com/travel/wet-sandstone/)

*All web sources retrieved 2026-07-02. Encyclopedic entries (Wikipedia) are tertiary —
prefer the UIAA/BMC/book sources for anything load-bearing.*

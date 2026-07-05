# The Four Layers — developer guide

One section per operational layer of the engine. This is the **developer contract** for each
layer: its interfaces and the rules for building in it. The *vision* for each layer lives in
[`../vision/mission.md`](../vision/mission.md); the *honest live/planned status* lives in
[`current-state.md`](current-state.md) — this file links to both rather than restating them,
so there is one place for each fact.

The pipeline: **Phase 1** captures raw data → **Phase 2** standardizes + scores it →
**Phase 3** filters it through human taste → **Phase 4** renders the actionable plan.

---

## Phase 1 — Raw data capture

*Vision:* [`mission.md`](../vision/mission.md) (static + live-social scrapers). *Status:*
⚠️ Partial — structured API pulls only; social/guidebook scrapers planned.

**Live sources today** (all inside `fetch_env.py` / `update_report.py`; endpoints, quotas
and retry behaviour in [`../operations/external-apis.md`](../operations/external-apis.md)):

| Source | Pulls | Key? |
|---|---|---|
| Open-Meteo Archive / Forecast / Seasonal | July climatology · 16-day live · ~45-day outlook | none |
| Open-Meteo Marine | hourly tide → high/low water for tidal crags (decision #22) | none |
| multi-pitch.com `data.json` | nearby curated climbs, geo-matched to venue lat/lon | none |
| OSM Overpass | named lodging near each venue (houses/campsites/hotels) | none |
| SerpApi (Google Flights) | round-trip fares, top-N venues × travellers | `SERPAPI_KEY` |

Since decision #24, the trip-independent weather+tide layer is fetched **once per venue** by
`fetch_env.py` → `venue-env.json` and consumed by the build (see
[`venue-env-cache.md`](venue-env-cache.md)). Still missing ⛔: live social condition
scrapers (the highest-value gap), web-scale static guidebook crawlers, and a raw-record store
distinct from normalized data so Phase 2 can re-parse.

**Principles:** free-tier/keyless first, paid sources quota-guarded; retry, don't crash (any
one source failing must degrade, not fail the build); respect ToS/rate-limits/privacy (no
personal data into the public repo); raw ≠ clean (capture only — cleaning is Phase 2); geo is
the join key.

**Interface:** in — `venues.json` (what to query) + `flights.json` (routes); out — per-venue
normalized records (weather day-records, climb lists, flight quotes) for Phase 2.

**When building here:** wrap each new source in a retrying fetch, degrade gracefully, document
it in `external-apis.md`, never commit its key; keep social captures out of the public repo;
add venues in `venues.json`, not in scraper code.

---

## Phase 2 — AI standardization & scoring

*Vision:* [`mission.md`](../vision/mission.md). Two engines:

**2a · Taxonomy Engine** *(planned)* — NLP/LLM parsing of free guidebook text into a strict
data dictionary (style, rock, protection grade). Contract: *free text in → validated route
record out*, with a confidence score and the extracted source span. Vocabulary:
[`../data/taxonomy.md`](../data/taxonomy.md); record shape:
[`../data/route-schema.md`](../data/route-schema.md); grades:
[`../data/grade-conversion.md`](../data/grade-conversion.md). Validate LLM output against the
enums — reject/repair anything off-dictionary. Nothing parses free text yet; structured
metadata comes pre-cleaned from `venues.json` and multi-pitch.com's `data.json`.

**2b · Predictive Condition Algorithm** — ✅ a simplified slice is live: a deterministic
weather score (rain/precip proxy, extended on the live horizon with friction/drying/heat
terms) meaned over trip days across three horizons (live 16-day › climatology 70 / seasonal
30), ranked desc, tie-broken by venue `priority`.
**[`../data/condition-algorithm.md`](../data/condition-algorithm.md) is the single source of
truth for the formula — don't restate it.** The gap ⚠️→⛔: today's score ignores rock type
(seepage), aspect (sun/drying), humidity/dew (friction), wind-as-scored, and antecedent-rain
seepage lag — the real model needs Open-Meteo hourly fields × per-venue rock/aspect params.

**Interface:** in — Phase-1 normalized records; out — validated taxonomy records + per-venue
condition scores + the active **weather-basis** label, for Phases 3/4.

**When building here:** keep scoring **deterministic and reproducible** (climatology must give
identical output across two runs); document formula changes in `condition-algorithm.md` and
log the decision in `../roadmap/decisions.md`; validate any taxonomy parsing against
`taxonomy.md` enums (prefer Claude models — see `/claude-api`); always surface **which basis**
a ranking rests on.

---

## Phase 3 — Curated filter (human taste)

*Vision:* [`mission.md`](../vision/mission.md) — the quality moat: **Zero-Garbage UGC**
(reject unvetted content) and a verified **master index** of classic sectors that all
automated data must map onto, or it doesn't surface. More data is not the goal; better-filtered
data is.

*Status:* ⚠️ Partial — curation is real but **manual**. The master list is the Google Sheet
(`climbing-trips.csv`, ~38 rows), which `build_venues()` turns into ~42 ranked venues
(decision #15); `venues.json` (~13 entries) only **enriches/overrides** curated rows with
coords, `priority`, `rock`, `style`, and a `why`. Editing the sheet changes the ranking.
Missing ⛔: a verified sector directory with stable IDs beyond one trip's shortlist; automated
geo+name mapping of parsed climbs onto sectors (unmatched → **quarantined**, never surfaced);
a promote/demote/merge curation workflow; and per-sector provenance/verification state.

**Principles:** allow-list not block-list (default-deny keeps garbage out); config over code
(the index is data, edited independently of the engine); traceable taste (every entry carries
a `why`); `priority` is editorial (human preference, the tie-breaker on equal weather).

**Interface:** in — Phase-2 validated records seeking a home in the index; out — the curated,
ranked venue/sector set for Phase 4. Human-in-the-loop: the curation edits themselves.

**When building here:** grow the index in `venues.json` / a future sector directory
(keep `lat`/`lon`, `priority`, `rock`, `style`, `why` — see
[`../data/schemas.md`](../data/schemas.md)); when you add automated mapping, **quarantine**
unmatched climbs, never auto-surface them; record curation-policy calls in
[`../roadmap/decisions.md`](../roadmap/decisions.md).

---

## Phase 4 — Trip planner (actionable execution)

*Vision:* [`mission.md`](../vision/mission.md) — the Dual Workspace (vector topos + live
logistics side by side) and the Automated Contingency Engine (watch the plan; on bad weather,
compute three dry nearby alternatives).

*Status:* ✅ **Live (single-trip).** The dashboard at
<https://uncinimichel.github.io/climbing-agent/>, generated into `index.html` by
`update_report.py`: one card per venue best-first (mobile-first, no h-scroll at 390 px); a
per-venue weather mini-graph; an **honest basis banner** (live forecast vs "typical July +
45-day outlook", degrading if seasonal fails); per-traveller flights folded in; data-driven
source links (Maps, geo-matched climbs, sheet row, Windy); and a dated `history/` snapshot +
`daily-report.md` mirror each day. Missing ⛔: the contingency engine, embedded topos, live
social summaries in-card, price-drop/return-leg/date-lock tracking, and multi-trip/multi-user.

**Principles:** concise, best-first, mobile-first; every recommendation is sourced; honest
about basis and forecast horizon; advisory (the humans decide); **regenerated, never
hand-edited** — change the generator, not the HTML.

**Interface:** in — the curated, ranked, scored venue set (Phases 2–3) + flight quotes; out —
`index.html`, `venues/<slug>.html`, `daily-report.md`, `history/<date>.md`, deployed to Pages.

**When building here:** edit `update_report.py`, not `index.html`; keep the 390 px no-h-scroll
constraint as a verification checkpoint; build the contingency engine by reusing the ranking
(on an alert, surface the top-3 dry venues by score within a distance bound, and explain why) —
log the design in [`../roadmap/decisions.md`](../roadmap/decisions.md).

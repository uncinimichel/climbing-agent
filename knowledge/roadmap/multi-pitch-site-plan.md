# The multi-pitch.com site plan — the engine's product surface

*Compiled 2026-07-05. Sources: feature brainstorm + web research into climbing platforms
(UKC, Mountain Project, theCrag, 27 Crags/The Topo, Kaya, Vertical-Life, Rockfax,
Peakbagger, OpenBeta), water-sports conditions products (Surfline, Magicseaweed
post-mortem, Windguru, Windfinder, Windy.com/Windy.app, Surf-Forecast, WeatherFlow/
iWindsurf, Buoyweather, Swellnet, kite apps), and adjacent outdoor apps (AllTrails Peak,
Komoot, Gaia, FATMAP post-mortem, Outdooractive, OpenSnow, avalanche.org, Skitourenguru,
Mountain-Forecast, MWIS, Fishbrain, onX, Strava).*

## Where this sits

[`vision/mission.md`](../vision/mission.md)'s north star is turning multi-pitch.com from a
static guidebook into a **Dynamic, Predictive Trip Decision Engine**. This document is that
vision made concrete as a **product roadmap for the multi-pitch.com website itself** —
climbing-agent is the engine (taxonomy, condition scoring, Postgres corpus, retrieval
agent); multi-pitch.com is the product surface the engine is meant to power. The two repos
stay separate (`~/dev/multi-pitch`, Node/Lambda, vs. this repo's Python/Postgres stack);
this doc is the shared plan, kept here because engine work in `roadmap/roadmap.md` and
`data/condition-algorithm.md` should track it.

**Open question, not yet decided:** where the conditions-engine code actually runs — inside
multi-pitch.com's own lambdas (`~/dev/multi-pitch/lambda-node/`), or exposed as a service
climbing-agent's Postgres/agent stack serves and multi-pitch.com calls. See
[`roadmap/decisions.md`](decisions.md) #21.

## The big insight

**No major climbing platform does live conditions.** Mountain Project shows monthly climate
averages; theCrag, 27 Crags and Kaya have nothing; real forecasting got pushed into onX
Backcountry's paid tier. Tides: only Rockfax (static symbols) and UKC (a flag) acknowledge
them at all.

Meanwhile water sports proved the model a decade ago. Every successful product there is the
same machine:

> raw forecast in → per-spot calibration → **one glanceable colored verdict** → alerts on
> top → ground truth to close the loop

Multi-pitch.com already has: a per-climb weather lambda, a tides lambda, and structured
per-climb metadata (seepage, tidal, loose, aspect, altitude, approach). It is uniquely
positioned to be the **first climbing site that answers "should I go, and where?"** — and
with only ~50 climbs, hand-calibrating each one is a weekend's work. Hand-tuned per-spot
calibration is exactly the moat Surfline built with LOTUS.

**climbing-agent already has a first cut of this exact idea running** — the NI trip
planner's `day_score`/`climo_score` (heat curve, aspect × sun, dew-point friction; see
[`data/condition-algorithm.md`](../data/condition-algorithm.md), decisions #16/#17) is a
proto version of Tier 1.1 below, just scoped to ~40 candidate venues instead of per-climb.
The gap documented there (rock type, seepage, antecedent rain not yet scored) is the same
gap Tier 1.1 needs closed.

---

## Tier 1 — The conditions engine

### 1.1 Per-climb "climbability" rating
*Inspired by: Surfline LOTUS, Skitourenguru, Magicseaweed*

- [ ] Rules-based score per climb per day/hour, computed in the existing weather lambda:
      rain now + trailing 48–72 h (drying/seepage), wind at the crag, temperature, tide
      window for tidal climbs, daylight.
- [ ] Calibration profile per climb from metadata that already exists (seepage-prone →
      weight trailing rain; exposed arête → weight wind; tidal → weight tide).
- [ ] Output: **Poor / Fair / Good / Prime** pill with traffic-light colors on every card
      and map marker.
- [ ] Steal Magicseaweed's beloved **"faded stars"**: show what the day *would* rate and
      name the limiting factor ("Prime but for 45 km/h gusts", "still drying from Tuesday's
      rain"). It teaches the reasoning, builds trust, and is trivial to derive — it's
      whichever input capped the score.
- [ ] Publish the scoring rules on a page — Skitourenguru's lesson: **transparency is the
      credibility**.
- [ ] **Never paywall the rating** — Magicseaweed's lesson: the free, glanceable, calibrated
      rating is beloved and currently unserved.

### 1.2 "Where's on this weekend?" ranked page
*Inspired by: Surf-Forecast Wavefinder, meteoblue Where2Go, OpenSnow favorites-compare*

- [ ] One page ranking all ~50 climbs by rating over the next 3–5 days, filterable by
      region/grade.
- [ ] Homepage sort option ("best conditions first").
- Turns 50 forecasts into one decision; the single most differentiating page the site could
  ship.

### 1.3 Best-window + 7-day strip on every climb page
*Inspired by: Windy.app Windybar, Surfline hourly strip, Buoyweather Captain's Brief*

- [ ] Colored 7-day outlook bar at the top of each climb page.
- [ ] Computed best window for today: *"11:00–16:30 — dry rock, light W wind, tide clear of
      the base 10:40–17:50"*. For sea cliffs, daylight × dry × tide-below-X is computable
      **now** from the two existing lambdas, and shown by no climbing site anywhere.
- [ ] One-sentence plain-language verdict above the numbers (template-generated is fine —
      that's what Buoyweather does). No incumbent ships LLM forecast summaries yet; open
      ground.

### 1.4 Wishlist alerts
*Inspired by: OpenSnow powder alerts, Surfline custom alerts*

- [ ] "Email me when a wishlisted climb goes Good+ on a weekend."
- [ ] Key insight from every good alert system: constrain to when the user can actually go
      (days of week, daylight).
- [ ] One scheduled lambda + an email endpoint.

### 1.5 Forecast quality upgrades
*Inspired by: Mountain-Forecast, meteoblue, yr.no*

- [ ] Forecast at route elevation (base vs top for long alpine routes).
- [ ] Always show freezing level.
- [ ] Simple per-day confidence indicator from model agreement — "only commit if
      predictability is high". open-meteo / api.met.no expose what's needed, free.

---

## Tier 2 — Curation as product (cheap, static, on-brand)

### 2.1 Rockfax-style "conditions character" block per climb
- [ ] Hand-written structured fields per climb: faces SW · sun from 14:00 · dries in 2 days
      · seeps after wet winters · sheltered from N wind · tidal approach.
- [ ] Structured fields (not prose) so the rating engine can also consume them.
- Surfline's spot-guide fields map 1:1 to trad: ability level, hazards, crowd factor, best
  season/tide/wind, approach, ethics. The most-loved conditions feature in climbing needs no
  backend.

### 2.2 Season grid + expiring condition notes
*Inspired by: Outdooractive*

- [ ] 12-month best-season bar per climb.
- [ ] Dated condition notes ("Jun 2026: P4 anchor replaced") that visibly age and auto-flag
      as stale after N months. Solves guidebook rot; pure static content.

### 2.3 "How a climb earns its place" page
- [ ] Make the less-but-better criteria explicit; name the curator and when each route was
      last verified; optional "under consideration" pipeline list.
- The 2024–26 pattern is unambiguous: FATMAP's expert guidebook layer was mourned, Kaya got
  burned for devaluing authors, 27 Crags pays authors 50%, Swellnet sells named humans,
  Komoot torched its trust overnight. **Small + trusted + opinionated is a market position
  the big platforms keep vacating.**

### 2.4 Ticklist completion mechanic
*Inspired by: UKC Classic Rock, Peakbagger*

- [ ] "You've climbed 12 of 51" — completion percentage, localStorage only.
- Completion is the strongest retention loop in the niche; Classic Rock (this site's direct
  ancestor) still drives engagement 50 years on.

### 2.5 Shareable wishlist + tick log with conditions snapshot
- [ ] URL-encoded wishlist to share trip plans; CSV export (portability is a repeated user
      demand on every platform).
- [ ] On marking a climb done, snapshot that day's weather with the tick (Fishbrain
      pattern) — "climbed 14 May, sunny, 18 °C". Aggregated, it becomes "usually climbed
      May–Sept".

### 2.6 Printable route sheet + offline PWA
*Inspired by: Outdooractive print; offline is every climbing app's #1 paid feature*

- [ ] One-pager per climb: topo, pitch table, approach/descent, tide + emergency numbers.
      Print CSS gets 80% of it.
- [ ] Service-worker caching of visited climb pages = "works at the base of the wall".

---

## Tier 3 — Bigger swings (later, if ever)

### 3.1 3D route preview *(FATMAP's orphaned legacy)*
Approach + route line + descent draped on 3D terrain (MapLibre GL terrain, free EU DEMs).
FATMAP proved people love visually rehearsing a line; its guidebook-on-3D-map combo has been
unclaimed since Oct 2024. Descent gullies with slope shading = safety bonus.

### 3.2 Lightweight ground-truth reports
One-tap "climbed today: dry / seeping P3 / wet", timestamped, auto-expiring. Seepage is the
one variable no model sees; yesterday's report beats any forecast. Governance steal from
Surfline: the model can only say "Good" — **"Prime, confirmed" is reserved for a human
report**. Keep it structured and expiring; never open comments/reviews/grades.

### 3.3 Seasonality climatology
Run the rating function over historical weather (ERA5/OWM history): "May: 61% of days
Good+, October: 22%". Windfinder's monthly probability stats are the best trip-booking tool
in any adjacent market. **climbing-agent already runs this exact computation** for the NI
trip (`climo_score` over ERA5 archive) — the reusable part is the historical-scoring
pipeline, not the UI.

### 3.4 Weather-aware map mode
Map markers colored by today's rating — the Windguru color-scan experience applied to a
climbing map.

---

## Deliberate non-goals

- **No** social feeds, forums, partner-finding, beta videos, grade votes, leaderboards —
  network-scale features the big five own; every failed mid-size platform died bolting them
  on (Glassy: community + logging with no revenue = dead).
- **No** user-submitted routes or reviews — curation is the brand.
- **Don't paywall the rating** or the long-range view (Magicseaweed resentment is three
  years old and still driving users to rivals).
- If anything is ever charged for: Windguru's non-recurring, no-dark-patterns pricing is the
  goodwill template.
- Stay transparently open with your own data; link out generously (UKC ticks, Rockfax for
  depth). The industry is walling data off (UKC 402s, theCrag 403s, the Kaya scandal) —
  openness is now a differentiator (see [`data/external-models.md`](../data/external-models.md)).

---

## Content / blog plan

| Idea | Model | Notes |
|---|---|---|
| Weekly "Conditions & Picks" note | OpenSnow *Daily Snow*, Swellnet *Forecaster Notes* | A named human interpreting the data. People pay for this in every adjacent sport; here it's free marketing + newsletter content (Mailchimp form already exists). Cheapest high-value item — can start now. |
| "Anatomy of a classic" series | — | One deep-dive per listed climb: history, first ascent, why it's on the list, link-up beta. Interlinks with climb pages; SEO compounds. |
| Impact-phrased weather literacy | MWIS | "What 40 km/h wind feels like on an exposed belay"; tide/swell judgement for sea cliffs; freezing level explained. |
| Skills for the VDiff–E1 leader | — | Belay changeovers, linking pitches, retreating without leaving the rack, route-finding, abseil descents. Underserved audience. |
| Seasonal routing | — | "Multi-pitch in January: Costa Blanca not Cornwall"; autumn sea-cliff windows. |
| Gear by grade | — | "What rack for VS?"; 2026 update of the trad gear tier list (they age fast, rank well). |
| Epics & lessons | — | Honest near-miss write-ups; reinforces the safety-conscious tone. |
| "Why less but better" | — | The mission piece / curation criteria (pairs with 2.3). |

---

## Housekeeping that unlocks the above

- [ ] More climbs remains the core flywheel (1–2/month).
- [ ] **GA4** (needs a `G-` measurement ID only the owner can create) — flying blind on
      content performance since UA died in 2023.
- [ ] Newsletter: quarterly "new climbs + best condition windows" once the rating engine
      exists.
- [ ] yr.no / open-meteo as free, reliable supplementary forecast APIs.

---

## Suggested sequence

1. **Climbability rating** — lambda + pill on cards/map *(1.1)*
2. **"This weekend" ranked page** + climb-page 7-day strip *(1.2, 1.3)*
3. **Conditions-character blocks + season grids** — content pass *(2.1, 2.2)*
4. **Ticklist completion + shareable wishlist** *(2.4, 2.5)*
5. **Printable sheets** *(2.6)*
6. **Wishlist email alerts** *(1.4)*
7. Reassess; Tier 3 only if the above lands.

*The weekly conditions note can start any time — it needs no code at all.*

## How this maps onto climbing-agent's roadmap

| This plan | climbing-agent equivalent |
|---|---|
| Tier 1 conditions engine (1.1–1.5) | [`roadmap/roadmap.md`](roadmap.md) Stage 1 (real condition intelligence) + [`data/condition-algorithm.md`](../data/condition-algorithm.md)'s "target: the physical condition model" |
| Tier 2 curation-as-product (2.1–2.3) | Stage 3 (scale curation) — `area`/`area_reference` tables, [`data/database.md`](../data/database.md) |
| Tier 3.3 seasonality climatology | Already partly live — `climo_score` over ERA5 archive in the NI trip planner |
| 3.2 ground-truth reports | Phase 1 social/static scrapers ([`phases.md` — Phase 1](../architecture/phases.md#phase-1-raw-data-capture)) + Phase 3's Zero-Garbage UGC principle |

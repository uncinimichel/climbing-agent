# The Mission — multi-pitch.com "Live"

The overarching mission is to transform the platform from a **static guidebook library**
into a **Dynamic, Predictive Trip Decision Engine**. The system replaces the tedious,
multi-app logistics of climbing-trip planning with a single, elegant question-and-answer
flow: *"Where should we climb, on what dates, and how do we get there?"*

The engine executes across four operational layers, moving from raw web noise to a
refined, premium user experience:

```
[1. THE SCRAPER]  ──> [2. THE AI TAXONOMY] ──> [3. THE CURATED FILTER] ──> [4. THE TRIP PLANNER]
(Raw Data Capture)     (Standardization)        (Human Taste & Curation)     (Actionable Execution)
```

---

## Phase 1 — The Scraper (Raw Data Capture)

The foundation is continuous, automated data ingestion. The system deploys **dual-track
scrapers** to capture both historical records and live environmental reality:

- **Static scrapers** — crawl legacy, unstructured text databases and guidebook
  registers across the web.
- **Live social scrapers** — continuously monitor active regional climbing groups,
  local mountain-guide whitelists, and geotagged hashtags across Meta, X, and TikTok to
  extract immediate, real-world condition updates.

→ Detail: [`phases/phase-1-scraper.md`](../phases/phase-1-scraper.md)

## Phase 2 — The AI Layer (Standardization & Intelligence)

Raw internet data is chaotic, inconsistent, and full of text-heavy noise. The AI is the
system's translator and analyst:

- **The Taxonomy Engine** — uses NLP / LLM-driven parsing to clean raw, unstructured
  text and force it into a **strict data dictionary**. It isolates explicit technical
  metadata: climbing style, rock type, and **protection quality** (`PG-13`, `R`, `X`).
- **The Predictive Condition Algorithm** — evaluates live micro-climate forecasts
  against physical rock parameters, mathematically scoring real-time **friction windows**
  and **drying / seepage rates**.

→ Detail: [`phases/phase-2-ai-taxonomy.md`](../phases/phase-2-ai-taxonomy.md)

## Phase 3 — The Curated Filter (Human Taste)

AI and code can only take the platform so far; automated aggregators inevitably suffer
from a total lack of quality filtering. This is the core competitive advantage:

- **Zero-Garbage UGC** — the platform actively rejects the messy, unverified
  user-generated content of legacy sites.
- **The Standard of Taste** — every recommendation is filtered through a carefully
  managed **master index**. Automated data flows are mapped *exclusively* onto a verified
  directory of classic sectors, so the engine only ever surfaces high-quality,
  worthwhile climbs.

→ Detail: [`phases/phase-3-curation.md`](../phases/phase-3-curation.md)

## Phase 4 — The Trip Planner (Actionable Execution)

The final stage translates the curated, intelligent data matrix into a practical,
interactive **split-screen dashboard**:

- **The Dual Workspace** — premium vector climbing topos side-by-side with real-time
  transit pricing, hyper-local weather tracking, and active social-media condition
  summaries.
- **The Automated Contingency Engine** — continuously watches the plan. If ingestion
  scrapers detect incoming bad weather or high seepage for a scheduled weekend, the
  planner raises an instant alert and programmatically computes **three dry geographic
  alternatives** nearby.

→ Detail: [`phases/phase-4-trip-planner.md`](../phases/phase-4-trip-planner.md)

---

## Design principles (the "why" behind the layers)

1. **Free and always-on by default.** The reference implementation runs entirely on
   free tiers (GitHub Actions + Pages, Open-Meteo) so it can run daily with no laptop
   and no manual step. Paid APIs are opt-in and quota-guarded.
2. **The repo is the database.** State lives in versioned JSON + a git history. Every
   run is reproducible and auditable; no hidden server state.
3. **Single sources of truth.** Config files (`venues.json`, `flights.json`) drive
   everything downstream. Change the config, not the code, to change behaviour.
4. **Honest uncertainty.** The system always states *what basis* a recommendation rests
   on (live forecast vs climatology vs sub-seasonal outlook) and labels weak signals.
5. **Advisory, not autocratic.** The engine ranks and flags; the humans decide.
6. **Taste beats volume.** More scraped data is worthless without the curated master
   index (Phase 3). Curation is the moat.

## North Star vs today

This document is the **destination**. Only a slice is live now — a single-trip Phase-4
dashboard with partial Phase-1/2 plumbing. Read
[`architecture/current-state.md`](../architecture/current-state.md) for the honest
snapshot, and [`roadmap/roadmap.md`](../roadmap/roadmap.md) for the path from here to
there.

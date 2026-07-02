# 📚 multi-pitch.com "Live" — Knowledge Base

The reference brain for the project. Start here, then follow the map below.
This folder is **documentation**, not code — it explains *what we're building, why,
and how the pieces fit*. Keep it truthful: separate the **vision** (where we're going)
from the **current state** (what actually runs today).

> **One-line mission:** turn a static climbing-guidebook library into a **Dynamic,
> Predictive Trip Decision Engine** — one question-and-answer flow that replaces the
> tedious multi-app logistics of planning a climbing trip.

## How to use this folder

- **New here / an AI agent picking up the project?** Read in this order:
  `vision/mission.md` → `architecture/current-state.md` → `architecture/overview.md`.
- **Building a feature?** Find its layer in `phases/`, then check `data/schemas.md`
  and `operations/` before writing code.
- **Making a non-obvious call?** Log it in `roadmap/decisions.md`.
- **Keep it honest.** If a doc describes something aspirational, label it
  *(planned)*. Today only a slice of the vision is live — see `current-state.md`.

## Map

```
knowledge/
├── README.md                 ← you are here (index + navigation)
├── CONVENTIONS.md            ← writing + code conventions for this repo
│
├── vision/
│   ├── mission.md            ← the North Star: the 4-layer engine, in full
│   └── glossary.md           ← domain vocabulary (climbing + system terms)
│
├── architecture/
│   ├── overview.md           ← the 4 layers → concrete components + diagram
│   ├── current-state.md      ← HONEST snapshot: what exists & runs today
│   └── data-flow.md          ← how a data point travels scraper → dashboard
│
├── phases/                   ← one file per operational layer
│   ├── phase-1-scraper.md    ← raw data capture (static + social scrapers)
│   ├── phase-2-ai-taxonomy.md← standardization + predictive condition AI
│   ├── phase-3-curation.md   ← human taste / master index / zero-garbage UGC
│   └── phase-4-trip-planner.md← the actionable dashboard (LIVE today)
│
├── data/
│   ├── taxonomy.md           ← the strict data dictionary (rock/style/protection/incline/flags)
│   ├── route-schema.md       ← the tagging target: full route record (from multi-pitch.com)
│   ├── grade-conversion.md   ← normalized dataGrade 1–7 ladder across grade systems
│   ├── schemas.md            ← JSON shapes: venues, flights, conditions
│   ├── condition-algorithm.md← the predictive condition scoring maths
│   ├── references.md         ← authorities: people, books, encyclopedias + grade origins
│   └── external-models.md    ← how UKC/theCrag/MP/OpenBeta model data + what to adopt
│
├── operations/
│   ├── deployment.md         ← GitHub Actions + Pages + secrets
│   ├── external-apis.md      ← Open-Meteo, SerpApi, multi-pitch.com data.json
│   └── runbook.md            ← run / verify / maintain, day to day
│
└── roadmap/
    ├── roadmap.md            ← prototype → platform, staged
    └── decisions.md          ← lightweight ADR log (why we chose X)
```

## The four layers at a glance

```
[1. THE SCRAPER]  ──> [2. THE AI TAXONOMY] ──> [3. THE CURATED FILTER] ──> [4. THE TRIP PLANNER]
(Raw Data Capture)     (Standardization)        (Human Taste & Curation)     (Actionable Execution)
   planned/partial         partial                    planned                    ✅ LIVE (single-trip)
```

| Layer | What it does | Status today |
|---|---|---|
| **1 · Scraper** | Ingest static guidebooks + live social condition reports | ⚠️ Partial — weather/flight/climb pulls only, no social scrapers |
| **2 · AI Taxonomy** | Clean raw text → strict data dictionary; score friction/seepage | ⚠️ Partial — deterministic weather scoring, no NLP taxonomy yet |
| **3 · Curated Filter** | Map data onto a verified master index of classic sectors | ⛔ Planned — curation is manual (`venues.json`) |
| **4 · Trip Planner** | Split-screen dashboard: topos + transit + weather + conditions | ✅ Live for one trip (NI, July 2026) |

See `architecture/current-state.md` for the unvarnished detail.

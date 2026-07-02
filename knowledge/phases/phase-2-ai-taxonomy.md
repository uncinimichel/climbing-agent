# Phase 2 — The AI Layer (Standardization & Intelligence)

> **Purpose:** turn chaotic raw text and micro-climate data into clean, structured,
> scored intelligence. The system's translator and analyst.
> **Status:** ⚠️ Partial — deterministic weather scoring is live; NLP taxonomy & a true
> physical condition model are planned.

Phase 2 has two distinct engines.

---

## 2a · The Taxonomy Engine *(planned)*

Uses NLP / LLM-driven parsing to clean raw, unstructured text and force it into a
**strict data dictionary**. It isolates explicit technical metadata:

- **Climbing style** — trad / sport / multi-pitch / alpine …
- **Rock type** — granite / limestone / dolerite / rhyolite …
- **Protection quality** — the safety grade: `G`, `PG`, `PG-13`, `R`, `X`.

The controlled vocabulary it must map onto is specified in
[`data/taxonomy.md`](../data/taxonomy.md); the **full record it must emit** (the tagging
target for a found climb) is [`data/route-schema.md`](../data/route-schema.md), and grade
normalization is [`data/grade-conversion.md`](../data/grade-conversion.md). Both are
grounded in the real **multi-pitch.com** data model. The engine's contract: *free text in
→ validated route record out*, with a confidence score and the source span it extracted
from, written to the description **style rules** in `route-schema.md`.

**Why LLM parsing:** guidebook prose is idiosyncratic ("bold, serious leading, spaced
gear high up") — rules miss it; an LLM can map it to `R` with a rationale. Validate the
LLM's output against the enum (reject/repair anything off-dictionary) rather than
trusting free-form output.

### Not built yet
Nothing currently parses free text into the dictionary. Structured metadata today comes
pre-cleaned from `venues.json` and multi-pitch.com's `data.json`.

---

## 2b · The Predictive Condition Algorithm

Evaluates live micro-climate forecasts against physical rock parameters to score, in
real time:

- **Friction windows** — when it's cool/dry enough for good rock friction.
- **Drying rate** — how fast a crag becomes climbable after rain.
- **Seepage** — lingering water weeping through rock long after the sky clears.

### What exists today ✅ (a simplified slice)

A **deterministic weather score** — a rain/precipitation proxy, not yet a physical
friction/seepage model. Full maths in
[`data/condition-algorithm.md`](../data/condition-algorithm.md):

- `day_score()` = `100 − 0.8·rain% − 6·precip_mm`, capped at 25 if rain code ≥ 61
  (rain) and 15 for thunderstorms.
- **Venue score** = mean `day_score` over the trip days used.
- **Three horizons blended:** live 16-day forecast › (climatology **70** / 45-day
  seasonal **30**) while beyond live range. Live supersedes both once available (~8 July).
- Rank by score desc, tie-break by venue `priority` (NI preferred when tied).

### The gap ⚠️ → ⛔

Today's score ignores the physics the vision calls for:

| Vision factor | Today | Needed |
|---|---|---|
| Rock type (seepage propensity) | ignored | limestone/overhangs seep for days; granite dries fast |
| Aspect (sun/shade, drying) | ignored | S-facing dries & bakes; N-facing stays shaded/cool |
| Humidity / dew point (friction) | ignored | core to a real "friction window" |
| Wind (drying) | shown on graph, not scored | accelerates drying |
| Antecedent rain (seepage lag) | not modelled | yesterday's rain sets today's seepage |

Building the real model means combining Open-Meteo hourly fields (humidity, wind, temp,
precipitation) with per-venue rock/aspect parameters (a new field in the master index).

## Interfaces

- **Input:** Phase-1 normalized records (weather day-records, raw climb text).
- **Output:** validated taxonomy records + per-venue condition scores + the active
  **weather basis** label, consumed by Phase 3/4.

## When building here

- Extend scoring → keep it **deterministic and reproducible** (verification relies on
  identical output across two runs for climatology). Document the formula change in
  `data/condition-algorithm.md` and log the decision in `roadmap/decisions.md`.
- Add taxonomy parsing → validate LLM output against the enums in `data/taxonomy.md`;
  never let off-dictionary values through. Prefer Claude models (see `/claude-api`).
- Always surface **which basis** a ranking rests on — honesty about uncertainty is a
  product principle.

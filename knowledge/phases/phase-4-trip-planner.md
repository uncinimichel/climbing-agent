# Phase 4 — The Trip Planner (Actionable Execution)

> **Purpose:** translate the curated, scored data matrix into a practical, interactive
> dashboard that answers "where / when / how do we climb?" and watches the plan for us.
> **Status:** ✅ Live (single-trip) — dashboard shipped; contingency engine & embedded
> topos planned.

## Vision

- **The Dual Workspace** — a split-screen: premium **vector climbing topos** on one side,
  and **real-time transit pricing + hyper-local weather + social condition summaries** on
  the other. The climb and its logistics, in one glance.
- **The Automated Contingency Engine** — continuously watches the plan. If ingestion
  scrapers detect incoming bad weather or high seepage for a scheduled weekend, the
  planner raises an **instant alert** and programmatically computes **three dry geographic
  alternatives** nearby.

## What exists today ✅

The live dashboard at <https://uncinimichel.github.io/climbing-agent/>, generated into
`index.html` by `update_report.py` and served on GitHub Pages:

- **One card per venue, best-first.** #1 highlighted. Mobile-first; no horizontal scroll
  at 390 px.
- **Per-venue weather mini-graph** — rain bars + temperature line + wind dashed line,
  with a legend.
- **Honest basis banner** — states whether the ranking rests on the live forecast or
  "typical July + 45-day outlook", and degrades gracefully if the seasonal API fails.
- **Per-traveller flights folded in** — ✈️ Michel (London) + ✈️ Dan (Belfast/Dublin),
  3 best-value options each with outbound times, book links, and country flags; NI shows
  Dan as local.
- **Data-driven source links** — Google Maps, multi-pitch.com climbs (geo-matched),
  spreadsheet row, and a Windy "forecast ↗".
- **History** — a dated snapshot every day (`history/`), plus the `daily-report.md`
  markdown mirror that renders on GitHub.

## What's missing ⛔ (planned)

- **The Automated Contingency Engine** — the "3 dry nearby alternatives on a bad-weather
  alert" flow. Today the dashboard *ranks* venues (so alternatives are implicit in the
  order) but doesn't actively alert or compute a targeted contingency set.
- **Embedded premium vector topos** — currently links out; no topo in the workspace.
- **Live social condition summaries** in the card (blocked on Phase-1 social scrapers).
- **Price-drop alerts, return-leg times, tides, date-lock tracking** — see the backlog in
  [`roadmap/roadmap.md`](../roadmap/roadmap.md).
- **Multi-trip / multi-user** — the whole planner is scoped to one hard-coded trip.

## Design principles

1. **Concise, best-first, mobile-first.** The user should get the answer at a glance on a
   phone. No horizontal scroll.
2. **Every recommendation is sourced.** Cards link back to Maps, climbs, and the
   spreadsheet — the user can verify the machine.
3. **Honesty about basis.** Always show what the ranking rests on and how far out the
   forecast is trustworthy.
4. **Advisory.** The planner ranks and flags; Michel & Dan make the call.
5. **Regenerated, never hand-edited.** `index.html` is an output — change the generator
   (`update_report.py`) or the config, never the HTML by hand.

## Interfaces

- **Input:** the curated, ranked, scored venue set (Phases 2–3) + flight quotes.
- **Output:** `index.html`, `daily-report.md`, `history/<date>.md`, deployed to Pages.

## When building here

- The dashboard is **generated** — edit `update_report.py`, not `index.html`.
- Keep the mobile constraint (no h-scroll at 390 px) as a verification checkpoint.
- Building the contingency engine → reuse the existing ranking: on an alert for the
  chosen venue, surface the top-3 *dry* venues by score within a distance bound, and
  explain why. Log the design in [`roadmap/decisions.md`](../roadmap/decisions.md).

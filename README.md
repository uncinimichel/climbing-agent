# 🧗 Climbing Trip Planner — Michel & Dan

**▶ Live: [Multi-pitch climbing trip planner — 40+ European venues ranked daily by weather](https://uncinimichel.github.io/climbing-agent/)**

An automated, free, always-on planner for a multi-pitch climbing trip around
**Fri 24 – Tue 28 July 2026**. It ranks candidate venues by weather and prices
flights for both travellers — rebuilt and redeployed **every day at 06:00 UTC**
by GitHub Actions (no laptop, no manual step).

## What it does

- **Ranks venues by weather** — July climatology now (free historical data), and the
  live 16-day forecast once the trip is in range (~8 July). A mini graph shows the
  typical outlook across the trip window ±2 days.
- **Prices flights** for the top venues, for **Michel (from London)** and
  **Dan (from Belfast or Dublin)**, via Google Flights — 3 best-value options each
  with times and booking links.
- **Finds places to stay** near each crag (OpenStreetMap, free) — houses/apartments
  (Airbnb-style), campsites (bring your own kit) and hotels for 2 adults, with
  date-filled Airbnb/Booking.com search links. The cheapest realistic bed also
  feeds the venue's travel score.
- **Links back to sources** — each venue links to Google Maps, its
  [multi-pitch.com](https://multi-pitch.com/) climbs, and its row in the
  [venue spreadsheet](https://docs.google.com/spreadsheets/d/1N4Xs-aSGFc8-ibysqpdCvQIfMH4Rjx4n5WQnqITGPC8/edit).
- **Keeps history** — a dated snapshot every day in `trip-ni-july-2026/history/`.

## How it works

| Piece | File |
|---|---|
| Live dashboard (GitHub Pages) | [`index.html`](index.html) |
| Build script (weather + flights → HTML) | [`trip-ni-july-2026/scripts/update_report.py`](trip-ni-july-2026/scripts/update_report.py) |
| Candidate venues + per-traveller airports | [`trip-ni-july-2026/venues.json`](trip-ni-july-2026/venues.json) |
| Flight rules & date combos | [`trip-ni-july-2026/flights.json`](trip-ni-july-2026/flights.json) |
| Daily cloud job | [`.github/workflows/weather.yml`](.github/workflows/weather.yml) |
| Plan, architecture, backlog | [`trip-ni-july-2026/PLAN.md`](trip-ni-july-2026/PLAN.md) |

Weather: [Open-Meteo](https://open-meteo.com/) (free, no key). Flights: Google Flights
via SerpApi (key stored as a GitHub secret, never committed). Stays:
[OpenStreetMap Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) (free, no
key; cached in `trip-ni-july-2026/stays-cache.json` — prices shown are typical
estimates per lodging type, not live quotes).


## The route corpus & the Curation Studio ✏️

Behind the trip planner sits a **curated database of multi-pitch trad routes**
(Postgres + PostGIS in [`db/`](db/)). Its governance rule is simple and enforced by the
database itself:

> **Suggestions and rankings may only use routes a human has verified** —
> `status: publish` + `taggedBy: human`. Everything scraped or AI-tagged stays a
> **draft** until a person reviews it.

The **Curation Studio** is the tool that does that review — a localhost-only admin
(it writes to the DB, so it is never deployed):

```bash
colima start && (cd db && docker-compose up -d)    # the database
agent/.venv/bin/python db/tools/curate.py          # → http://localhost:8890
```

One draft at a time, with the evidence alongside (source links, the AI's tag receipt, a
map pin, monthly climate): verify the facts, fix the tags, write the **intro / approach /
pitch-by-pitch** prose, then **Publish** (⌘⏎) — or flag 🥾 *needs field check* if someone
has to go look at the rock. A Grid view handles bulk column edits. **⇩ Export** writes the
whole DB to [`db/corpus.json`](db/corpus.json) — the committed, git-diffable backup that
the read-only [Corpus Inspector](https://uncinimichel.github.io/climbing-agent/knowledge/corpus-inspector.html)
serves.

| Where the routes come from | They enter as |
|---|---|
| Hand-verified in the Studio | ✅ **curated** (`publish` + human-tagged) |
| [multi-pitch.com](https://multi-pitch.com/) seed (own site; tags AI-inferred from the prose) | draft, `taggedBy: llm` |
| UKC / theCrag crawler ([`db/tools/crawl_worker.py`](db/tools/crawl_worker.py)) | draft, untagged |

Full policy: [data governance](https://uncinimichel.github.io/climbing-agent/knowledge/data/governance.html) ·
manual & design: [curation-studio plan](https://uncinimichel.github.io/climbing-agent/knowledge/roadmap/curation-studio-plan.html) ·
wiring: [data map](https://uncinimichel.github.io/climbing-agent/knowledge/data-dependencies.html)
(decisions #32/#34).

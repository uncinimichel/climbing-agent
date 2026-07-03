# 🧗 Climbing Trip Planner — Michel & Dan

**▶ Live dashboard: https://uncinimichel.github.io/climbing-agent/**

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

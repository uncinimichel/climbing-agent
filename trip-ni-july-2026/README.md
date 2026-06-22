# Climbing Trip — ~24 July 2026

**Who:** Michel Uncini (London, W5 4LA) + Dan Knight (Belfast, NI)
**Target dates:** around 2026-07-24 (flexible by a few days to chase weather)
**Goal:** a good trad multi-pitch venue, dates + flights locked in.

## Decision rule

Destination is **weather-driven**. Default to Northern Ireland (Dan is local → cheapest logistics). If the forecast for the NI window looks wet/unclimbable, switch to the backup.

| Priority | Venue | Why | Travel for Michel |
|---|---|---|---|
| 1 | **Northern Ireland** — Fair Head / Mournes | Dan lives in Belfast; cheap, short flight | LON → BFS/BHD (~1h) |
| 2 (backup) | **Dolomites, Italy** | Peak season late July, vast multi-pitch, routes already scoped in `dolomites-trip.csv` | LON → Venice/Innsbruck + drive |
| 3 (alt) | **East Tyrol, Austria** | Similar alpine summer window | LON → Innsbruck/Salzburg |

NI venues: **Fair Head** (world-class dolerite, long single/multi-pitch trad) and the **Mournes** (granite, moderate multi-pitch — in `climbing-trips.csv`, <4h, 2-day min).

## Status / open items

- [ ] Confirm exact date window with Dan
- [ ] Start daily weather log ~10 days out (from ~2026-07-14) — see `forecast-log.md`
- [ ] Go/no-go destination call ~3–4 days before
- [ ] Check flights once destination is likely (London ⇄ Belfast for Michel)
- [ ] Book

## Candidate venues — `venues.json`

`venues.json` is the **single source of truth** for which venues get monitored. The weather script reads it to decide what to query, so edit that file to add/remove a venue or change the target date window. Current candidates: Fair Head (NI, primary), Mournes (NI, primary), Dolomites (backup), East Tyrol (alt).

## Files

- `venues.json` — candidate venues + target window (drives the weather queries)
- `flights.json` — flight route + date combos to price (rules: Fri/Sat out, Mon/Tue back, 3–4 nights)
- `flights-latest.json` — latest prices per combo (filled on demand / by an API; not wiped by weather runs)
- `daily-report.md` — latest dashboard with weather + flights (GitHub renders it); regenerated each run
- `history/YYYY-MM-DD.md` — permanent dated snapshots (never overwritten)
- `forecast-log.md` — running append-only log
- `scripts/update_report.py` — fetches Open-Meteo + renders flights, writes report + history
- `../.github/workflows/weather.yml` — daily cloud job that runs the script

## How this is monitored

- **Weather:** automated daily forecast pull (Open-Meteo, no key) for NI + backup venues, appended to `forecast-log.md`. Reliable inside ~14 days.
- **Flights:** checked on demand (no reliable free flight-price API). Ask Claude to check London⇄Belfast fares; closer to booking, run a few times.

See persistent memory `trip-ni-july-2026` for the durable summary.

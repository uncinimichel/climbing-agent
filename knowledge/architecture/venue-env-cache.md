# Venue Environment Cache — weather & tide, computed once per venue

The design for splitting **trip-independent environment data** (weather, wind, tide) out of
the daily build and into a standalone, reusable cache keyed by venue. Today's monolith
(`trip-ni-july-2026/scripts/update_report.py`) fetches weather *and* prices flights *and*
renders HTML in one pass, re-deriving everything from scratch for one hardcoded trip. This
doc describes the seam that separates the two, so the environment layer is computed **once
per day per venue** and reused across every trip, every user, and the website's
"browse a venue before I commit to a trip" path. Decision
[#24](../roadmap/decisions.md). Storage target: [`../data/database.md`](../data/database.md).
Current flow it refactors: [`data-flow.md`](data-flow.md).

> **Status: ⚠️ Partial — env layer extracted (2026-07-05).** `fetch_env.py` fetches the
> trip-independent weather/tide layer once per venue and writes `venue-env.json`;
> `update_report.py` **consumes** it (via `_env_raw()` in `forecast()`, `_seasonal_raw()`,
> `tide_extremes()`), falling back to live fetches when the cache is absent. `weather.yml`
> runs `fetch_env` before the report. Verified: the cache-fed ranking is byte-identical to a
> live run. **Not done:** the cosmetic `fetch_trip.py` / `build_report.py` file-split —
> scoring and rendering share rich in-memory state across a 3-pass flight-repricing loop, so
> splitting them into separate processes is risk with no functional gain today. They stay in
> `update_report.py`, which is now the env-cache *consumer* + trip/report orchestrator.

## Why split at all

Weather, wind and tide are a **pure function of `(lat/lon, date)`** — they do not depend on
who is going, where they fly from, or which trip is active. Flights and stays are a function
of `(origin, venue, dates)`. That is the normalization boundary:

| Layer | Depends on | Cardinality | Refresh |
| --- | --- | --- | --- |
| **Environment** (this doc) | venue × date | **O(venues)** | daily (later: sub-daily for weather; tide is astronomical, ~weekly is ample) |
| **Booking** (flights/stays) | trip × person × venue × dates | O(trips × people × venues) | per trip, quota-guarded |

Computing the environment layer once and letting every trip read it keeps weather at
**O(venues)** no matter how many trips or users exist. It also serves the website directly:
a visitor can open Fair Head and see its forecast **without a trip existing at all**.

This is a **structural** win first (one 3086-line script doing three jobs → three files each
doing one) and a **reuse** win second. It is *not* a cost optimization — Open-Meteo is free;
the scarce resource remains SerpApi flight quota, which lives entirely in the booking layer.

## The join key is the venue, never the climb

Weather is per **lat/lon** (venue); tide is per **crag/coast**. A venue has dozens to
hundreds of climbs but one forecast. The reference therefore runs

```
climb ──▶ venue ──▶ environment
```

never `climb ──▶ environment`. A weather record is stored **once per venue**, and any climb
inherits its venue's environment by lookup. Storing a forecast blob per route would duplicate
the same numbers thousands of times.

## Latest-only, no history

One record per `(venue, date)`, **overwritten every run**. The two use cases —
"create a trip for tomorrow/next weekend" and "browse a venue's weather before deciding" —
both want only *the current best forecast for date X*. Neither needs "what did we predict for
the 24th as seen from the 10th."

**Given up:** forecast-skill tracking (how right the 10-day-out call was). **Recoverable
later** by adding an `issued_at` column to the key — additive, not a rewrite — if that need
ever appears.

## Horizon tiers

Open-Meteo's standard forecast API caps at **16 days** (`forecast_days=16`). Each daily date
carries a `src` tag naming which model produced it, so a downstream renderer can say
"forecast" vs. "typical for the region" honestly rather than guessing:

| `src` | Horizon | Open-Meteo endpoint | Meaning |
| --- | --- | --- | --- |
| `forecast` | days 0–16 | `api.open-meteo.com/v1/forecast` | live forecast (+ tide from `marine-api`) |
| `seasonal` | ~17–45 | `seasonal-api.open-meteo.com` | sub-seasonal outlook — weak signal, label it so |
| `climo`    | beyond | `archive-api.open-meteo.com` (2021–24) | climatological typical, already disk-cached |

A trip for tomorrow or next weekend is always well inside the 16-day `forecast` band, so it
reads live numbers straight from cache with zero extra fetching.

## Shape (JSON now, 1:1 with the future Postgres table)

The file carries **two views of the same data**, because the report needs more than the
normalized view exposes:
- **`raw`** — the raw Open-Meteo payloads (`forecast` incl. hourly dewpoint/precip,
  `seasonal`, derived tide `extremes`). This is what `update_report.py` consumes, so its
  output stays identical to a live run — `evaluate()` reads hourly humidity, gusts, precip
  probability and UV that the normalized view drops.
- **`days`** — the normalized, per-`(venue, date)`, latest-only view. This is the
  reuse/website/future-Postgres surface, and one entry **is** one future DB row — no second
  migration when the Postgres corpus ([`../data/database.md`](../data/database.md),
  decision #18) comes online. `forecast` (0–16d) wins; `seasonal` fills the ~17–45d tail.

```jsonc
// venue-env.json  (generated by fetch_env.py — never hand-edit; regenerated each run)
{
  "generated_at": "2026-07-05T06:00Z",
  "target_window": { "start": "2026-07-22", "end": "2026-07-27" },
  "venues": {
    "fair-head-ni": {
      "name": "Fair Head, NI", "lat": 55.222, "lon": -6.156, "tidal": true,
      "fetched_at": "2026-07-05T06:00Z",
      "raw":  { "forecast": { /* Open-Meteo 16-day, incl. hourly */ },
                "seasonal": { /* Open-Meteo ~45-day ensemble */ },
                "tides":    { "2026-07-22": [ { "t": "05:12", "h": 1.8, "k": "H" } ] } },
      "days": {
        "2026-07-05": { "src": "forecast", "tmax": 17, "precip": 0.4, "wind": 9,
                        "dir": 266, "code": 3,
                        "tide_hw": ["05:12", "17:40"], "tide_lw": ["11:20", "23:48"] },
        "2026-07-22": { "src": "seasonal", "tmax": 18, "precip": 1.1 }
      }
    }
  }
}
```

**Climatology is not in this file** — it's the fixed 2021–24 archive, already persisted and
committed in `climo-cache.json`, so re-caching it here would be waste; a `src: "climo"` tier
can fill dates beyond the ~45-day seasonal reach when needed.

**The file is git-ignored, not committed.** With raw hourly payloads × ~42 venues it is
~2.6 MB and fully re-churned daily; committing it would bloat this public repo's history.
`fetch_env.py` writes it and `update_report.py` reads it **within the same CI run**.
Publishing the lightweight `days` view to the website (so a visitor can see a venue's weather
with no trip) is a follow-up — the site is a separate surface.

Maps directly to:

```sql
venue_env (
  venue_id   text,
  date       date,
  src        text,          -- forecast | seasonal | climo
  tmax       real,
  precip     real,
  wind       real,
  dir        smallint,
  code       smallint,      -- WMO weather code
  tide_hw    text[],        -- high-water times, local; null for non-tidal venues
  tide_lw    text[],        -- low-water times
  fetched_at timestamptz,
  primary key (venue_id, date)   -- upsert each run = latest-only
)
```

Tide fields are populated only when the venue's crag-level `tidal` flag is set (decision
[#22](../roadmap/decisions.md); `venue_is_tidal()`), and only within the marine model's
~10-day horizon — dates beyond it come back without tide times, which is expected.

## Repo split (as built)

```
scripts/
  fetch_env.py       # ✅ trip-independent: weather + tide, once per venue → venue-env.json
  update_report.py   # consumes venue-env.json (via _env_raw / _seasonal_raw / tide_extremes),
                     #   then does flights + stays + scoring + render. Live-fetch fallback.
```

`weather.yml` runs `fetch_env → update_report`. `fetch_env.py` is the reusable core — the
same cache serves the report today and (once its `days` view is published) the website.

**Why not the full `fetch_trip.py` / `build_report.py` split yet:** the clean seam is
environment vs. everything-else. Scoring and rendering, by contrast, share rich in-memory
state across a **3-pass flight-repricing loop** (score → rank → price top-N → re-score →
re-rank → re-price → render). Forcing that into two separate OS processes means serializing
the whole ranked/scored state between them — pure risk, no functional gain today. So the
trip+render half stays in `update_report.py`, which is now the env-cache *consumer*. The
file rename is a cosmetic follow-up, tracked but deliberately deferred.

## Staleness (splitting processes splits failure modes)

One atomic run used to guarantee weather, flights and HTML were mutually consistent. Now
`fetch_env` is a separate step, so `update_report` could read a cache a failed run left stale.
Current behaviour and the intended hardening:

- ✅ **Degrades, never crashes** — if `venue-env.json` is absent or a venue is missing from it,
  every fetcher (`forecast`/`_seasonal_raw`/`tide_extremes`) falls back to a live call, so the
  report still builds. Because `fetch_env` and `update_report` run in the same CI job, the
  cache is fresh by construction.
- ⛔ *(planned)* a **"weather N days old"** badge from `fetched_at` for the day the two steps
  drift (e.g. `fetch_env` fails but a prior cache lingers) — not needed while the file is
  git-ignored and rebuilt each run, but required before the `days` view is published to a
  longer-lived surface.

## What this does *not* change

- **Scoring stays put.** `day_score` / `climo_score` and the composite blend
  ([`../data/condition-algorithm.md`](../data/condition-algorithm.md)) still consume the same
  per-day fields; they just read them from the cache instead of a fresh fetch. Determinism of
  the climatology base is preserved.
- **Venues remain config-driven.** `venue-env.json` is generated from the same venue list
  (`venues.json` + the curated sheet); no venue is defined here.
- **Booking quota discipline is untouched** — flight top-N capping stays in `fetch_trip.py`.

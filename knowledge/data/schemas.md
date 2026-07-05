# Data Schemas

The JSON shapes that drive the engine. These are the **single sources of truth** — the
build script reads them to decide what to query and price. Change behaviour by editing
these, not the code.

> **Direction of travel:** the route/venue corpus now has a relational home — the
> Postgres schema in `db/` ([`database.md`](database.md), decision #18). These JSON
> configs stay authoritative for the live trip dashboard; corpus-shaped data
> (`venues.json` venue facts, `extra-climbing.json` links) migrates into the DB, which
> eventually becomes the only source of truth.

## `venues.json` — the master index (Phase 3, manual)

Which venues get monitored. The script reads this to decide what to query for weather and
flights. Located at `trip-ni-july-2026/venues.json`.

```json
{
  "trip": "Climbing trip ~24 July 2026 — Michel & Dan",
  "target_window": { "start": "2026-07-22", "end": "2026-07-27" },
  "notes": "Single source of truth for candidate venues.",
  "venues": [
    {
      "name": "Fair Head, NI",
      "country": "Northern Ireland",
      "priority": "1 (primary)",       // editorial rank + tie-breaker
      "lat": 55.222,
      "lon": -6.156,                    // one representative point per area
      "rock": "dolerite",
      "style": "long single & multi-pitch trad",
      "why": "Dan lives in Belfast — cheapest logistics; world-class venue.",
      "hub": "Belfast (BFS/BHD), ~1h flight from London",
      "travel": {
        "michel": { "mode": "fly", "to": "BFS" },   // fly | local | drive
        "dan":    { "mode": "local" }
      }
    }
    // … 9 venues total
  ]
}
```

Field notes:
- **`priority`** — human/editorial preference; used as the tie-break when weather scores
  are equal (NI preferred). Format is `"N (label)"`.
- **`travel.<person>.mode`** — `fly` (needs `to`, an IATA airport), `local` (no travel),
  or `drive` (no airport).
- **`lat`/`lon`** — the geo join key for climbs and weather; one point per area.
- *Planned fields for the condition model:* `aspect`, `seepage_class`.

## `flights.json` — route + date combos (Phase 1 input)

Flight search rules. The report enumerates each depart×return combo within `max_nights`
and shows the cheapest. Located at `trip-ni-july-2026/flights.json`.

```json
{
  "route": {
    "origin_city": "London",
    "traveller_origins": {
      "michel": ["LGW", "LHR", "LTN", "STN", "LCY"],
      "dan": ["BFS", "BHD", "DUB"]
    },
    "passengers": 1
  },
  "rules": { "depart_days": ["Fri","Sat"], "return_days": ["Mon","Tue"],
             "min_nights": 3, "max_nights": 4 },
  "combos": [
    { "id": "fri-mon", "out": "2026-07-24", "back": "2026-07-27", "nights": 3 },
    { "id": "fri-tue", "out": "2026-07-24", "back": "2026-07-28", "nights": 4 },
    { "id": "sat-tue", "out": "2026-07-25", "back": "2026-07-28", "nights": 3 }
  ],
  "target_price_gbp": 120
}
```

Rule: exactly **3 combos, all 3–4 nights** (no 2-night option). The max-nights combo is
the representative round-trip priced per venue.

## `flights-latest.json` — latest prices (output state)

Per-venue cached prices for both travellers, written by `update_report.py`. **Never
contains the API key.** Not wiped by weather-only runs, so prices persist between flight
pulls. Structure is per-venue → per-traveller → best options (price, outbound times,
booking URL).

## Condition record *(planned — Phase 2 output)*

The scored output the Predictive Condition Algorithm should emit per venue/day:

```json
{
  "venue": "Fair Head, NI",
  "date": "2026-07-24",
  "basis": "live",                 // live | climatology | seasonal-blend
  "day_score": 87.4,
  "inputs": { "rain_prob_pct": 15, "precip_mm": 0.2, "tmax_c": 18, "wind_kmh": 12 },
  "friction_window": "am",         // planned
  "seepage_risk": "low"            // planned
}
```

## Conventions

- All config is **hand-edited JSON**; outputs (`index.html`, `*-latest.json`, history)
  are **generated** — don't hand-edit them.
- Prefer adding a field to changing code paths — the script should read config, not
  hard-code venue facts.
- Keep coordinates and IATA codes accurate; they're the join keys for weather and flights.

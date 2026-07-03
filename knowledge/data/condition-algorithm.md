# The Predictive Condition Algorithm

How the engine scores weather into a climbability ranking. This documents the **live,
deterministic** scoring today and the **physical model** the vision calls for.

Source of truth for the maths: `trip-ni-july-2026/scripts/update_report.py`. Keep this
file in sync when the formula changes, and log formula changes in
[`roadmap/decisions.md`](../roadmap/decisions.md).

## Today: deterministic rain-proxy scoring ✅

### Per-day score

```
day_score = 100 − 0.8·(rain_prob_%) − 6·(precip_mm)
          capped at 25  if weather_code ≥ 61   (rain)
          capped at 15  if thunderstorm
   # live-forecast horizon only — gentle, bounded climbing-quality nudges:
          − 0.6·max(0, gust_kmh − 30)          (exposure; ~−12 at 50 km/h)
          − 0.8·min(precip_hours, 12)          (drizzle-all-day vs one burst)
          + 10·(sunshine_frac − 0.5)           (sun dries rock, ±5)
          − 1.2·max(0, daytime_dewpoint − 12)  (friction / grease; ~−10 at dew 20)
          − heat_penalty(tmax)                 (climbing heat curve, below)
```

### The climbing heat curve (2026-07-03)

Dry-but-hot venues were out-ranking climbable ones (Costa Blanca, Wadi Rum topping a
July list on 0% rain alone). Friction research puts ideal sending temperatures at
**~7–18°C** — skin and rubber grease out past ~20–25°C — and this trip is
**multi-pitch**: hours exposed on the wall with no shade retreat
(climbing.com's *Science of Friction*; UKC conditions threads; full list in
[`references.md`](references.md)). Both horizons now share one curve:

```
heat_penalty(tmax) = 1.2·max(0, tmax − 20)     gentle from 20°C
                   + 3.0·max(0, tmax − 25)     steep from 25°C
                   + 5.0·max(0, tmax − 30)     brutal from 30°C
   # a 31°C coastal venue loses ~36 points; a 35°C desert ~73 → bottom of the table

climo_score = 100 − 0.9·rain_pct
            − 2·max(0, 8 − tmax)               (numb fingers below ~8°C)
            − heat_penalty(tmax)
```

- Higher is better; 100 = perfect dry day.
- Rain probability and precipitation both penalise; heavy/coded rain hard-caps the score
  so a wet day can't look mediocre-but-okay.
- The four extra terms apply **only when the live 16-day forecast is in range** (they need
  fields climatology/seasonal don't carry). Each is small and clamped so ranking never
  swings wildly — they refine ties, they don't overturn a rain verdict. `daytime_dewpoint`
  is the mean of hourly dew point 09–18 local; `sunshine_frac = sunshine ÷ daylight`.
  Surfaced on the dashboard as a friction/gusts/dry-mornings chip strip + hover tooltips.

### Venue weather score

```
weather_score = mean(day_score over the trip days used)     (live horizon)
              | 0.7·climo_score + 0.3·seasonal_score        (beyond live range)
```

### Composite trip score (2026-07-03)

Weather is dominant but no longer the whole ranking — the spreadsheet's judgment
columns and flight costs now count:

```
trip_score = 0.55·weather + 0.25·travel + 0.20·venue_fit

travel    = mean of: cost score (known flight prices per person, £0 → 100,
            £400+ avg → 0; local=£0, drive≈£90) and the sheet's
            "Rough Travel Time from UK" band (<4h → 95 … 12-24h → 30)
venue_fit = mean of: volume band (Vast 100 / Large 85 / Moderate 65 / Smaller 45),
            difficulty band (Full Range 100 / Moderate 90 / Medium-Hard 75 / Hard 50),
            min-trip fit (100 if sheet min-trip ≤ trip days, −25/extra day)
```

Flight prices exist only for the top-N priced venues, so ranking runs twice: a
provisional pass (time-band travel), price the top-N, then a final pass with real
prices. The UI shows the split as the **donut** in the venue header (click a segment
for the maths); the leaderboard states the formula in its subtitle.

Ranking: **sort by `trip_score` desc, tie-break by `priority`** (NI preferred when tied).

### Three weather horizons (all free, no key)

| Horizon | Source | Role |
|---|---|---|
| **Live forecast** | Open-Meteo 16-day | Ranks the trip once in range (~8 July); **supersedes** the others. |
| **Climatology** | Open-Meteo Archive (ERA5 July averages) | Deterministic base ranking + the per-venue rain/temp/wind mini-graph. |
| **Sub-seasonal** | Open-Meteo Seasonal (CFS, ~45 d) | Weak signal; **blended 70/30** (climatology dominant) while beyond live range. |

**Basis selection:** while the trip is beyond the 16-day window, rank on
`0.7·climatology + 0.3·seasonal`, labelled "typical July + 45-day outlook". Once the live
forecast reaches the trip window, it supersedes both. The active basis is always stated
in the dashboard banner (honest-uncertainty principle).

### Properties that matter

- **Reproducible.** Climatology scoring is deterministic — two runs give identical rain%
  and ordering. This is a verification checkpoint (see `operations/runbook.md`).
- **Graceful degradation.** Seasonal-API failure → climatology-only, not a crash.

### Known limitations (accepted)

- **"Wet day" = ≥3 mm/day** from ERA5. Penalises alpine venues (Dolomites, Tyrol) whose
  brief afternoon convection still leaves climbable mornings.
- **Sub-seasonal skill is modest** (~30 days) — hence the cautious 70/30 blend, labelled
  "experimental".
- **One point per venue** — a single representative coordinate, not per-crag.

## The gap: this is not yet a *friction/seepage* model ⚠️

The vision's Predictive Condition Algorithm scores **friction windows, drying rate, and
seepage** from micro-climate × rock physics. The live-forecast horizon now takes a **first
cut** at friction (dew point) and drying (sunshine + gusts); climatology/seasonal remain a
rain proxy, and the physics below is still coarse (no rock type, aspect, or seepage yet):

| Factor | Why it matters | Status |
|---|---|---|
| **Humidity / dew point** | the crux of a real friction window | **scored (live)** — daytime dew point → friction band + score term |
| **Sunshine / precip-hours** | drying rate; distinguishes drizzle-all-day from one burst | **scored (live)** — sunshine fraction + wet-hours terms |
| **Wind gusts** | exposure on multi-pitch / sea-cliffs; also drying | **scored (live)** — gust penalty above 30 km/h |
| **Rock type** | limestone seeps for days; granite dries in hours | in `venues.json`, *not yet scored* |
| **Aspect** | S-facing dries/bakes; N-facing stays cool/shaded | *planned field* |
| **Antecedent rain** | yesterday's rain drives today's seepage | Open-Meteo archive/forecast, *not yet scored* |

## Target: the physical condition model *(planned)*

A sketch to build toward — combine hourly micro-climate with per-sector rock parameters:

```
friction    = f(temp, dew_point, humidity, wind)         → best when cool & dry
drying_rate = f(rock_type, aspect, sun, wind, temp)      → granite/S-facing fast
seepage     = f(rock_type, antecedent_rain_Ndays, aspect)→ limestone/overhang high
climbability = combine(friction, dryness_now, seepage_risk)  per sector, per window
```

Output the richer condition record in [`data/schemas.md`](schemas.md) (with
`friction_window` and `seepage_risk`), and feed the Phase-4 contingency engine so "3 dry
alternatives" means *actually dry*, not just *low forecast rain*.

### Science basis (what the literature says)

The model above is grounded, not guessed — full citations in
[`references.md`](references.md):

- **Friction is skin-limited, not rock-temperature-limited.** A rock's friction barely
  changes with air temperature; what changes is *sweat*. Cool + dry + low humidity = good
  friction. So model the **friction window** from temp/dew-point/humidity, not rain alone.
- **Rock type sets grip and drying.** Sandstone (~0.74) grips better dry than limestone
  (~0.64); limestone/overhangs seep for days; granite dries fast.
- **Drying = f(sun, wind, humidity).** Sun and wind speed it; humidity prolongs it — and a
  surface can read dry while the rock beneath is wet (so `antecedent_rain` matters).
- **Wet sandstone is a hard no** — porous, weak when wet, holds break. A `sandstone` +
  recent-rain combination should score *unclimbable*, not merely *poor*.

## When you change the scoring

1. Keep climatology **deterministic** (reproducibility is a verification checkpoint).
2. Update the formula here and in `update_report.py` together.
3. Always keep the **basis label** honest in the UI.
4. Log the change in `roadmap/decisions.md` with the rationale.

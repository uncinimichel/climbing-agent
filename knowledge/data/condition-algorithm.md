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
```

- Higher is better; 100 = perfect dry day.
- Rain probability and precipitation both penalise; heavy/coded rain hard-caps the score
  so a wet day can't look mediocre-but-okay.

### Venue score

```
venue_score = mean(day_score over the trip days used)
```

Ranking: **sort by `venue_score` desc, tie-break by `priority`** (NI preferred when tied).

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
seepage** from micro-climate × rock physics. Today's score uses none of that physics —
it's a rain proxy. Factors currently ignored:

| Factor | Why it matters | Data available |
|---|---|---|
| **Rock type** | limestone seeps for days; granite dries in hours | in `venues.json` |
| **Aspect** | S-facing dries/bakes; N-facing stays cool/shaded | *planned field* |
| **Humidity / dew point** | the crux of a real friction window | Open-Meteo hourly |
| **Wind** | accelerates drying | Open-Meteo (shown, not scored) |
| **Antecedent rain** | yesterday's rain drives today's seepage | Open-Meteo archive/forecast |

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

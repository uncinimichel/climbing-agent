# Route geometry × weather — why one forecast number can't cover a climb

How a route's *shape* (height gain, traverses, abseil approach) changes what a forecast
means, and what a widget or scorer may honestly claim. Companion to
[`weather-models.md`](weather-models.md) (which API and why) and
[`condition-algorithm.md`](condition-algorithm.md) (the scoring maths). Grounded in the
2026-07-17 multi-pitch.com top-out work (PR #92 there) — every number below is from live
calls, not theory.

> **Method:** verified against Open-Meteo with forced-elevation calls on
> **Sass Pordoi (46.499, 11.808)** and cross-checked against BBC/MeteoGroup village
> stations at three crags (NW Scotland, Mourne, Dolomites) on 2026-07-16/17.

## 1. Forecasts are model points at ONE elevation

Open-Meteo output is a numerical model **statistically downscaled with a 90 m DEM** to
the request point's elevation (their docs, `elevation` parameter). It is *not* station
interpolation — stations only feed the models' initial conditions upstream. Measured
consequence, same Sass Pordoi coordinates, only `&elevation=` changed:

| Forced elevation | Tomorrow's max | Gusts |
|---|---|---|
| 2709 m (DEM default = the massif) | 12.6 °C | 13.9 m/s |
| 1465 m (Canazei, the valley town) | 23.2 °C | 6.6 m/s |
| 0 m (unphysical extrapolation) | 31.5 °C | 18.7 m/s — garbage |

Implied gradient ≈ **7.0 °C/km ≈ the standard lapse rate (6.5 °C/km)**, and
**valley→summit roughly doubles gusts**. The 0 m row is the warning: downscaling is
trustworthy near the terrain's real elevation only.

## 2. A multi-pitch route climbs through its own weather

The climber starts at the base and tops out `length` metres higher, hours later. On a
555 m line (Fedele) that is ≈3.6 °C and a wind class *within one climb*; on the 720 m
Grande Fermeda ≈4.7 °C. **No single number covers both ends.** Any per-route weather
display must either state which point it describes or show both.

**The relative-offset trick:** you usually don't know whether the crag's DEM point sits
at the cliff's base or top (it can be off by the full cliff height — dankni, multi-pitch
PR #91). But a *second* forecast at `DEM_elevation + route_length` gives a correct
**base→top delta** wherever the DEM point sits, because the offset — not the absolute —
carries the signal.

## 3. Length ≠ height gain — geometry gates everything

`route length` approximates height gain **only on broadly vertical lines**:

- **Traverse / girdle routes** (taxonomy hazard `traverse`) cover *distance*, not
  altitude — Via Maria's 370 m includes long traverses. Applying lapse maths to their
  length fabricates cold that isn't there. **Rule: `traverse` ⇒ no top-out figures.**
- **Traverse-then-climb, up-then-down lines**: same problem, unknown split.
- **Abseil routes**: the taxonomy's `abseil` flag conflates **abseil-approach** (marker
  at the top; you drop `length` m then climb back — sea stacks, Old Man of Hoy) with
  **abseil-descent** (marker at the base; normal alpine descent). The two put the
  marker at *opposite ends* of the height band, so the flag carries **no directional
  signal** for weather. Vertical abseil routes keep length≈height; direction stays
  unknown.

**Taxonomy proposal** (to add via the Curation Studio per decision #35): split the
hazard into `abseil-approach` and `abseil-descent`. Beyond planning value, the split is
weather-relevant: approach ⇒ the coordinate describes the *top*; descent ⇒ the *base*.

## 4. Further nuances the one-number view hides

- **Hours-on-route**: a 10-pitch day spans a forecast's morning and afternoon — hourly
  data matters more than daily on long routes (see the widget's hour rows).
- **Remote ranges = weaker models**: NWP assimilates observations; sparse networks
  (exactly where the best multi-pitch lives) mean less-constrained output.
- **Aspect × hour**: a south face at valley dawn vs an arête at 14:00 differ more than
  any model resolves; taxonomy `aspect` + hourly sun is the best proxy.
- **Wind exposure**: summits/arêtes take the doubled gust figure above; sheltered bases
  may feel none of it — the model knows elevation, not shelter.
- **Valley inversions / föhn**: the two classic cases where lapse-rate intuition
  *inverts* (warm summit over cold valley); models catch some, not all.
- **Dew point is elevation-dependent too**: friction scoring
  ([`condition-algorithm.md`](condition-algorithm.md) §friction) uses the base
  elevation's dew point; the top-out spread differs. Reader-facing rule of thumb shipped
  in multi-pitch's widget: *rock temp near dew point ⇒ grease; wide gap ⇒ friction*.
- **Tidal windows and seepage** already have their own machinery (hazards `tidal`,
  `seepage`); they interact with the above (e.g. abseil-approach + tidal = committed).

## What a widget may honestly claim (shipped rules, multi-pitch PR #92 — final)

The two-figure/model-call version was **rolled back in review**: climbed length ≥
vertical gain on nearly every route (wandering lines, diagonal pitches), so
`DEM + length` systematically overshoots the summit and precise-looking top figures
overclaim. What survives is the one statement route length supports *by construction* —
since `length ≥ height gain`, `lapse × length` is a strict **upper bound** on the drop:

1. Vertical routes whose bound rounds ≥2 °C: one clause — *"the top of this 555 m route
   could be **up to** ≈4° colder (rough estimate)"*. No second model call, no per-cell
   marks.
2. `traverse` routes and anything shorter: **one figure, no claims**.
3. Everything under a blunt caveat (dankni's wording): *"This forecast comes from a
   weather model calculated for the climb's coordinates. Never take a forecast for
   granted."*

Cross-validation that the *physics* holds even though the *per-route geometry* doesn't:
met.no (independent model, explicit altitude) at 3264 m brackets Open-Meteo's forced-
elevation numbers there (1.2–10.6 vs 3.2–9.1 °C, 2026-07-17); BBC's nearest Dolomites
stations are valley towns only — the altitude signal is real, the route-specific claim
is what must stay humble.

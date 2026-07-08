# Weather models — why Open-Meteo, and the forecast-horizon strategy

Why the engine uses [Open-Meteo](https://open-meteo.com/) (free, keyless) rather than a
"longer" forecast API, and how the three forecast horizons are chosen. Companion to
[`condition-algorithm.md`](condition-algorithm.md) (the scoring maths) and decision
[#30](../roadmap/decisions.md).

> **Method:** live-tested every candidate against **Fair Head (55.222, −6.156)**, the NI
> trip's primary venue, on 2026-07-08 (16 days before the ~24 July window). Numbers below
> are from those calls, not vendor claims.

## The question: is there a better API with a longer forecast?

Short answer — **no, and length is the wrong axis.** The atmosphere has a hard
predictability limit near **~15 days**; beyond it a deterministic day-by-day forecast has
essentially **no skill over climatology** ([RMetS, *skill of weather prediction 1–14
days*](https://rmets.onlinelibrary.wiley.com/doi/10.1002/qj.2559)). The 30-day products on
the market ([OpenWeather 30-day](https://openweathermap.org/api/forecast30), Meteosource)
are climatology/ensemble blends dressed as daily numbers — more confident-looking noise, not
more signal.

**Proof from our own venue** — the top deterministic models on 20 July (12 days out):

| Date | best_match | ECMWF | GFS |
|---|---|---|---|
| 20 Jul | 16.3° / **2.2 mm** | 13.9° / **5.6 mm** | 15.0° / **0.0 mm** |
| 21 Jul | 15.3° / 3.0 mm | 14.4° / 6.4 mm | 14.0° / 0.0 mm |

Three leading models split from bone-dry to soaking on the same day. A single "16.3°/2.2 mm"
is noise; buying a 30-day API just buys more of it.

## Why Open-Meteo, and why `best_match`

Open-Meteo is free, keyless (10k calls/day), and exposes **model choice**. Model depth over
the 16-day window at Fair Head (non-null days returned):

| Model | Non-null days / 16 |
|---|---|
| **best_match (default — what we use)** | **15** |
| gfs_seamless | 16 |
| ecmwf_ifs025 | 14 |
| ukmo_seamless | 6 |
| icon_seamless | 7 |

Takeaway: **don't force a single model.** `best_match` auto-stitches the best model per
horizon (high-res local models short-range, ECMWF medium-range) and carries the most usable
days; ECMWF-only would cost a day at the edge, and UKMO/ICON high-res die at ~6–7 days.

## The real lever: the ECMWF ensemble (days ~7–16)

`ensemble-api.open-meteo.com` returns **51 ECMWF members** — a probability spread instead of
one fragile number, the honest signal exactly where a single run fails. Same venue, live:

| Date | tmax spread | P(rain ≥1 mm) | members |
|---|---|---|---|
| 19 Jul | 13–24 °C (σ 2.4) | **53 %** | 51 |
| 20 Jul | 14–24 °C (σ 2.7) | **75 %** | 51 |
| 21 Jul | 14–24 °C (σ 2.7) | **80 %** | 51 |

"80 % of members wet, 10 °C temp spread" is a far more honest input to `day_score` than
"14.4°/6.4 mm". Measured member depth: **ECMWF-ENS full to ~day 14**; the GFS ensemble
(`gfs025`, 31 members) reaches **35 days** but is coarser — a future candidate to enrich the
17–35 d tail now filled by CFS `seasonal`.

This is adopted in [decision #30](../roadmap/decisions.md): `weather.ensemble_raw` /
`ensemble_metrics`, merged as `ens_prob` for in-window venues, feeding `effective_rain_prob`.

## The candidates, for the record

| API | Max range | Free tier | Verdict |
|---|---|---|---|
| **Open-Meteo** (in use) | 16 d + 51-member ENS + ~45 d seasonal | keyless, 10k/day | Best free option; model choice + ensemble |
| [OpenWeather 30-day](https://openweathermap.org/api/forecast30) | 30 d | paid add-on | Climatology past ~2 wks; not "better" |
| [Meteosource](https://www.meteosource.com/) | 30 d | freemium | Same caveat |
| [Weatherbit 16-day](https://www.weatherbit.io/api/weather-forecast-16-day) | 16 d | 50 calls/day | No range gain over Open-Meteo |
| [Visual Crossing](https://www.visualcrossing.com/weather-api/) | 15 d + climatology | 1k records/day | Comparable, less generous |

## Operational note

The ensemble adds ~1 call per in-window venue. Run live across all venues it triggers
Open-Meteo's rate limit (HTTP 429) — so the intended source is the per-venue cache built by
`fetch_env.py` (`raw.ensemble`), and `scoring.evaluate` fetches it **only for in-window
venues**. Failure degrades gracefully to the weathercode fallback, never a crash.

## Sources

- [Open-Meteo](https://open-meteo.com/) · [ensemble API](https://open-meteo.com/en/docs/ensemble-api) · [seasonal API](https://open-meteo.com/en/docs/seasonal-forecast-api)
- [RMetS — skill of weather prediction at 1–14 days](https://rmets.onlinelibrary.wiley.com/doi/10.1002/qj.2559)
- [World Climate Service — deterministic vs ensemble forecasts](https://www.worldclimateservice.com/2021/10/12/difference-between-deterministic-and-ensemble-forecasts/)
- [Nature — extending deterministic range beyond 10 days](https://www.nature.com/articles/s43247-025-02502-y)

*Retrieved 2026-07-08. Live-tested against Fair Head. See also
[`references.md`](references.md).*

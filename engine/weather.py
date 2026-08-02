"""Back-compat shim — `engine.weather` was one module doing two jobs.

It has been split along the line the refactor is built on:

  core.weather.providers   fetching  — forecast, tides, climatology, seasonal,
                                       ensemble. Infrastructure, shared by every sport.
  core.weather.metrics     parsing   — turning provider payloads into per-date
                                       records. Also infrastructure.
  domains.climbing.conditions         judgement — heat/rain curves, friction,
                                       drying, wind-on-the-face. Climbing's alone.

This module re-exports all three so `engine.weather.day_score` and friends keep
working. New code should import the specific one it means — and if what you want
is a scoring curve, that is a deliberate signal you are writing domain code.
"""
# fetching (sport-agnostic)
from core.weather.providers import (  # noqa: F401
    CLIMO_VER, climatology, ensemble_raw, forecast, seasonal, seasonal_raw,
    tide_extremes, tides,
)
# payload parsing (sport-agnostic)
from core.weather.metrics import (  # noqa: F401
    ENS_WET_MM, code_rain_prob, compass, effective_rain_prob, ensemble_metrics,
    hourly_by_date,
)
# climbing's own judgement
from domains.climbing.conditions import (  # noqa: F401
    ASPECT_ADJ, ASPECT_DEG, CLIMB_H0, CLIMB_H1, COLD_C, GUST_BAD_KMH,
    HEAT_BRUTAL_C, HEAT_HOT_C, HEAT_WARM_C, NIGHT_RAIN_W, RAIN_IDEAL_PCT,
    RAIN_STEEP_PCT, asp_m, climo_score, day_rain_penalty, day_score,
    drying_factor, drying_traits, forecast_metrics, friction_label,
    heat_penalty, rain_penalty, sun_adjusted_tmax, wind_factor,
)

"""Back-compat shim — `engine.models` split by who owns the decision.

  core.trip                       TripContext: dates, travellers, venues, flex.
                                  Sport-agnostic — a trip is a trip.
  domains.climbing.weights        the composite weights (65/15/20).
  domains.climbing.preferences    the per-sub-signal ranking knobs.

The weights and preferences moved because they are climbing's answer, not a
universal one: a golf domain weighs wind where climbing weighs dry rock.
"""
from core.trip import (  # noqa: F401
    DEFAULT_CLIMO_YEARS, NeutralPreferences, TripContext, md_range,
    period_label, short_name,
)
from domains.climbing.preferences import ClimbingPreferences as Preferences  # noqa: F401
from domains.climbing.weights import W_FIT, W_TRAVEL, W_WEATHER  # noqa: F401

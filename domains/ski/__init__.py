"""Ski — resorts ranked on snow depth, lift status and what the weather will do
to the snow that is already there.

STATUS: conditions model only, and honestly blocked on a data source rather than
on code — the two signals that decide a ski trip (base depth, lifts turning)
come from resort feeds nobody has connected yet. `conditions.snow_score` and
`conditions.lift_penalty` are ready for them; until then the dials report
"needs the resort feed" rather than guessing.

Self-contained by design: imports core infrastructure only, never another domain.
"""
from core.sport import Domain, register

SKI = register(Domain(
    key="ski",
    label="Ski",
    status="opening Nov",
    blurb="Resorts ranked on snow depth and lift status first, then thaw risk, "
          "fresh snowfall and wind holds.",
    owns=("conditions",),
))

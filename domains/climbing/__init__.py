"""Climbing — multi-pitch trad, the domain this project started as.

Self-contained on purpose. Everything that encodes a climbing judgement lives
here and nowhere else:
  conditions.py  the curves — heat, rain, friction, drying, wind-on-the-face
  weights.py     how weather / travel / venue fit trade off
  climbs.py      multi-pitch.com routes near a venue, tidal crags
  venues.py      the curated Google-Sheet venue list
  scoring.py     venue evaluation, the five dials, venue fit, the composite
  render.py      the dashboard
  site_index.py  the multi-trip picker
  driver.py      one trip, end to end

From outside it takes only infrastructure (core.weather, core.travel, core.http,
core.cache, core.trip). It imports no other domain, and no other domain imports
it — so this folder can be worked on, reviewed and rewritten on its own.
"""
from core.sport import Domain, register

CLIMBING = register(Domain(
    key="climbing",
    label="Climbing",
    status="live",
    blurb="Multi-pitch trad venues ranked on hours of dry rock, felt temperature "
          "on the wall, friction and wind on the face.",
    owns=("conditions", "weights", "climbs", "venues", "scoring", "render",
          "site_index", "driver"),
))

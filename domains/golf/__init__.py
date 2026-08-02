"""Golf — courses ranked on wind, rain and how fast the course drains.

STATUS: conditions model only. There is no curated course list yet, so nothing
ranks golf venues end to end — `conditions.py` is complete and testable on its
own, and a venue dataset + scoring + render slot in beside it when the curation
work lands.

Self-contained by design: it imports core infrastructure (weather providers and
payload parsing) and nothing else. It does not import domains.climbing, and
domains.climbing does not import it — so this folder can be built out by someone
who has never read the climbing code.
"""
from core.sport import Domain, register

GOLF = register(Domain(
    key="golf",
    label="Golf",
    status="in curation",
    blurb="Courses ranked on wind first, then rain, temperature and how fast "
          "the course drains after it.",
    owns=("conditions", "weights"),
))

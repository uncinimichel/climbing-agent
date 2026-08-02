"""Tiny geo helper: great-circle distance between two points.

Used wherever "how far is this from that" comes up — lodging distance in
core.travel.stays, route proximity in domains/climbing, and whatever the next
domain needs. Moved verbatim from update_report.py's module-level `_haversine`."""
import math


def haversine_km(la1, lo1, la2, lo2):
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))

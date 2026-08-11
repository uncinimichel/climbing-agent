"""The one shared inventory shape every source maps into (decided in the
2026-08-11 design session): same SCHEMA per source, not same entities —
cross-source merging is the later LLM phase's job, never this module's.

Grades are stored native + system tag ({value: "E1 5b", system:
"uk_adjectival_tech"}), no conversion tables here: comparison across systems
is judgment, and judgment lives downstream.

crag = {
    source, source_id, name, lat, lon, url,
    country, region, rock_type,          # only if the source states them
    routes: [route, ...],
}
route = {
    source_id, name,
    grade: {value, system} | None,       # verbatim; system None when the
                                         # source doesn't say (theCrag mixes
                                         # systems by regional context)
    length_m, pitches, stars, bolts_count,
    protection,                          # source-stated protection grade (G/PG/R/X…)
    disciplines: [str, ...],             # mechanical map of the source's own label
    fa, url,
    description,                         # verbatim prose — phase-2 LLM input
}
"""
from __future__ import annotations

CRAG_KEYS = {"source", "source_id", "name", "lat", "lon", "url",
             "country", "region", "rock_type", "routes"}
ROUTE_KEYS = {"source_id", "name", "grade", "length_m", "pitches", "stars",
              "bolts_count", "protection", "disciplines", "fa", "url", "description"}


def crag(source: str, source_id: str, name: str, *, lat=None, lon=None, url=None,
         country=None, region=None, rock_type=None, routes=None) -> dict:
    return {"source": source, "source_id": str(source_id), "name": name,
            "lat": lat, "lon": lon, "url": url, "country": country,
            "region": region, "rock_type": rock_type, "routes": routes or []}


def route(source_id: str, name: str, *, grade_value=None, grade_system=None,
          length_m=None, pitches=None, stars=None, bolts_count=None,
          protection=None, disciplines=None, fa=None, url=None, description="") -> dict:
    grade = {"value": grade_value, "system": grade_system} if grade_value else None
    return {"source_id": str(source_id), "name": name, "grade": grade,
            "length_m": length_m, "pitches": pitches, "stars": stars,
            "bolts_count": bolts_count, "protection": protection,
            "disciplines": disciplines or [], "fa": fa, "url": url,
            "description": description or ""}


def validate(c: dict) -> list[str]:
    """Cheap structural check (no jsonschema dep): returns problems, [] if fine."""
    problems = []
    if set(c) != CRAG_KEYS:
        problems.append(f"crag keys off: extra={set(c) - CRAG_KEYS} missing={CRAG_KEYS - set(c)}")
    if not c.get("name"):
        problems.append("crag with no name")
    for r in c.get("routes", []):
        if set(r) != ROUTE_KEYS:
            problems.append(f"route keys off ({r.get('name')}): extra={set(r) - ROUTE_KEYS} missing={ROUTE_KEYS - set(r)}")
            break
        g = r.get("grade")
        if g is not None and (not isinstance(g, dict) or "value" not in g or "system" not in g):
            problems.append(f"route grade malformed: {r.get('name')} -> {g!r}")
            break
    return problems

"""The one shared inventory shape every source maps into (decided in the
2026-08-11 design session): same SCHEMA per source, not same entities —
cross-source merging is the later LLM phase's job, never this module's.

Enum-typed fields are bound to the corpus taxonomy
(corpus/record/taxonomies.json) — it IS the schema for them (Michel's ruling
2026-08-12): every `disciplines` entry must be a `discipline` code,
`protection` a `protection_grade` code, `rock_type` a `rock_type` code (all
nullable). Adapters map source labels onto those codes mechanically and emit
None for what they can't map — never a raw source string in an enum field.

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

import json
from pathlib import Path

_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "corpus" / "record" / "taxonomies.json"


def taxonomy_codes(name: str) -> frozenset[str]:
    data = json.loads(_TAXONOMY_PATH.read_text())["taxonomies"][name]
    return frozenset(v["code"] for v in data)


DISCIPLINES = taxonomy_codes("discipline")
PROTECTION_GRADES = taxonomy_codes("protection_grade")
ROCK_TYPES = taxonomy_codes("rock_type")
SUN_WINDOWS = taxonomy_codes("sun_window")
CHARACTER = taxonomy_codes("character")
FEATURES = taxonomy_codes("feature")
HAZARDS = taxonomy_codes("hazard")
INCLINES = taxonomy_codes("incline")

CRAG_KEYS = {"source", "source_id", "name", "lat", "lon", "url",
             "country", "region", "rock_type", "aspect", "routes"}
ROUTE_KEYS = {"source_id", "name", "grade", "length_m", "pitches", "stars",
              "bolts_count", "protection", "disciplines", "fa", "url", "description"}


def crag(source: str, source_id: str, name: str, *, lat=None, lon=None, url=None,
         country=None, region=None, rock_type=None, aspect=None, routes=None) -> dict:
    return {"source": source, "source_id": str(source_id), "name": name,
            "lat": lat, "lon": lon, "url": url, "country": country,
            "region": region, "rock_type": rock_type,
            "aspect": aspect,  # source-stated compass facing ("N", "SW", "all") — verbatim
            "routes": routes or []}


def route(source_id: str, name: str, *, grade_value=None, grade_system=None,
          length_m=None, pitches=None, stars=None, bolts_count=None,
          protection=None, disciplines=None, fa=None, url=None, description="") -> dict:
    grade = {"value": grade_value, "system": grade_system} if grade_value else None
    disciplines = list(disciplines or [])
    if (pitches or 0) >= 2 and "multi-pitch" not in disciplines:
        disciplines.append("multi-pitch")  # derived, purely structural — same rule for every source
    return {"source_id": str(source_id), "name": name, "grade": grade,
            "length_m": length_m, "pitches": pitches, "stars": stars,
            "bolts_count": bolts_count, "protection": protection,
            "disciplines": disciplines or [], "fa": fa, "url": url,
            "description": description or ""}


def validate(c: dict) -> list[str]:
    """Structural + taxonomy check (no jsonschema dep): returns problems, [] if fine."""
    problems = []
    if set(c) != CRAG_KEYS:
        problems.append(f"crag keys off: extra={set(c) - CRAG_KEYS} missing={CRAG_KEYS - set(c)}")
    if not c.get("name"):
        problems.append("crag with no name")
    if c.get("rock_type") is not None and c["rock_type"] not in ROCK_TYPES:
        problems.append(f"crag rock_type not a taxonomy code: {c['rock_type']!r}")
    for r in c.get("routes", []):
        if set(r) != ROUTE_KEYS:
            problems.append(f"route keys off ({r.get('name')}): extra={set(r) - ROUTE_KEYS} missing={ROUTE_KEYS - set(r)}")
            break
        g = r.get("grade")
        if g is not None and (not isinstance(g, dict) or "value" not in g or "system" not in g):
            problems.append(f"route grade malformed: {r.get('name')} -> {g!r}")
            break
        bad = [d for d in r.get("disciplines") or [] if d not in DISCIPLINES]
        if bad:
            problems.append(f"route disciplines not taxonomy codes ({r.get('name')}): {bad}")
            break
        if r.get("protection") is not None and r["protection"] not in PROTECTION_GRADES:
            problems.append(f"route protection not a taxonomy code ({r.get('name')}): {r['protection']!r}")
            break
    return problems

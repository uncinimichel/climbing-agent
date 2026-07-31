#!/usr/bin/env python3
"""OpenBeta source — the first wired catalog source (CC0 data, keyless, live).

Thin adapter over the existing, working GraphQL client
(corpus/tools/openbeta_client.py — schema verified live 2026-07-06): it fetches
an area, and shapes OpenBeta's records into the store's area/route dicts. All
OpenBeta-specific knowledge (its `type` booleans, `safety` string, all-systems
grade object) lives here; the worker and map.py stay source-agnostic.

Why the API and not a clone: the CC0 bulk repo (github.com/OpenBeta/climbing-data)
has its USA routes dump temporarily pulled and was last pushed 2024-11, so the
live API is the current source. See ingest/sources.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "corpus" / "tools"))
import openbeta_client as ob  # noqa: E402  (standalone, stdlib-only — no Postgres import)

SOURCE_ID = "openbeta"
NEEDS_BROWSER = False  # keyless GraphQL — the browser sources (thecrag/ukc) set this True

# OpenBeta `type` booleans → our discipline enum (taxonomies.json). "multi-pitch"
# is derived (pitch count), not an OpenBeta type.
DISCIPLINE_MAP = {
    "trad": "trad", "sport": "sport", "bouldering": "bouldering", "alpine": "alpine",
    "snow": "snow", "ice": "ice", "mixed": "mixed", "aid": "aid", "tr": "tr",
    "deepwatersolo": "deepwatersolo",
}
# OpenBeta `safety` → our protection_grade enum (mechanical, no LLM needed).
SAFETY_MAP = {"G": "G", "PG": "PG", "PG13": "PG-13", "R": "R", "X": "X"}
# area gradeContext → (grade object key, our grade_system_code). US-only in
# practice; the others are here so a non-US area degrades gracefully, not wrongly.
GRADE_CONTEXT = {
    "US": ("yds", "YDS"), "FR": ("french", "FS"), "UK": ("uiaa", "UIAA"),
    "AU": ("ewbank", "EW"), "ZA": ("ewbank", "EW"),
}


def seed_area(name: str, country: str = "USA") -> dict | None:
    """Resolve a human area name to a real OpenBeta start node (totalClimbs > 0,
    right country). Returns {uuid, pathTokens, totalClimbs} or None."""
    return ob.best_match(name, country)


def fetch(external_id: str, session=None) -> dict:
    """Raw OpenBeta area: meta + children (for discovery) + climbs (leaf only).
    `session` is unused (keyless GraphQL — kept for the uniform source interface)."""
    return ob.fetch_area(external_id)


def to_area(raw: dict) -> dict:
    """OpenBeta area → a store area dict (parent_id/kind assigned by the worker,
    which knows the tree it's building). Coords + gradeContext are mechanical."""
    meta = raw.get("metadata") or {}
    return {
        "name": raw["areaName"],
        "lat": meta.get("lat"),
        "lon": meta.get("lng"),
        "grade_context": raw.get("gradeContext"),
        "external_id": raw["uuid"],
    }


def children(raw: dict) -> list[dict]:
    """Child areas to enqueue for breadth-first descent (area → crag → route),
    in the uniform {external_id, name, total} shape the worker expects."""
    return [{"external_id": c["uuid"], "name": c["areaName"], "total": c.get("totalClimbs", 0)}
            for c in (raw.get("children") or [])]


def map_routes(raw: dict) -> list[dict]:
    """This area's climbs → mapped route dicts (leaf areas only carry climbs)."""
    gc = raw.get("gradeContext")
    return [to_route(climb, gc) for climb in (raw.get("climbs") or [])]


def _grade(climb: dict, grade_context: str | None) -> tuple[str | None, str | None]:
    grades = climb.get("grades") or {}
    key, sys_code = GRADE_CONTEXT.get((grade_context or "").upper(), ("yds", "YDS"))
    return (grades.get(key), sys_code) if grades.get(key) else (None, None)


def _disciplines(climb: dict, pitch_count: int) -> list[str]:
    t = climb.get("type") or {}
    out = [DISCIPLINE_MAP[k] for k, v in t.items() if v and k in DISCIPLINE_MAP]
    if pitch_count >= 2 and "multi-pitch" not in out:
        out.append("multi-pitch")
    return out


def to_route(climb: dict, grade_context: str | None) -> dict:
    """OpenBeta climb → a store route dict with the MECHANICAL fields only
    (name, grade, length, pitches, disciplines, protection-from-safety, bolts,
    FA, external ref). Prose-inferred fields (character/feature/hazards/incline)
    are left for the LLM tag stage. `area_id`/`id`/`status`/`tagged_by` are set
    by the worker at land time. Returns the dict plus the raw description text
    the tagger needs, under `_raw_description`."""
    pitches = climb.get("pitches") or []
    pitch_count = len(pitches) or None
    length_m = climb.get("length") if (climb.get("length") or 0) > 0 else None
    original_grade, grade_system_code = _grade(climb, grade_context)
    safety = (climb.get("safety") or "").upper()
    content = climb.get("content") or {}
    meta = climb.get("metadata") or {}

    route = {
        "name": climb["name"],
        "lat": meta.get("lat"),          # OpenBeta gives per-climb coords — keep them
        "lon": meta.get("lng"),
        "original_grade": original_grade,
        "grade_system_code": grade_system_code,
        "length_m": length_m,
        "pitches_count": pitch_count,
        "bolts_count": climb.get("boltsCount"),
        "protection_code": SAFETY_MAP.get(safety),  # None if OpenBeta gave no safety
        "tags": {"disciplines": _disciplines(climb, pitch_count or 0),
                 "features": [], "character": []},
        "first_ascents": climb.get("fa") or None,
        "external_refs": [{
            "source_id": SOURCE_ID,
            "external_id": climb["uuid"],
            "url": f"https://openbeta.io/climbs/{climb['uuid']}",
        }],
        # the tagger reads this; not a stored field (stripped before save)
        "_raw_description": content.get("description") or "",
    }
    return route

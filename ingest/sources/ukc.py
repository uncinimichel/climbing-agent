#!/usr/bin/env python3
"""UKClimbing source — best UK/Ireland coverage (~150k routes) + real pitch-by-
pitch prose (so its routes tag richly, unlike theCrag's bare listings). Public
pages via headless browser (ukc_client.py, Cloudflare-fronted); scraped with
Michel's permission, raw never leaves the private repo.

Uniform source interface. UKC has no area tree to walk — one crag page returns
every route in one fetch — so `children` is always empty and each frontier row
is a crag seeded by URL: --seed <url> --path "<breadcrumb>".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "corpus" / "tools"))
import ukc_client as uc  # noqa: E402

SOURCE_ID = "ukclimbing"
NEEDS_BROWSER = True

# UKC discipline label (the type-icon title, Title-case) → our discipline enum.
DISCIPLINE_MAP = {
    "trad": "trad", "sport": "sport", "boulder": "bouldering", "alpine": "alpine",
    "winter": "mixed", "ice": "ice", "aid": "aid", "scramble": "scrambling",
    "top rope": "tr", "solo": "trad",
}


def fetch(external_id: str, session) -> dict:
    return uc.fetch_crag(session, external_id)


def children(raw: dict) -> list[dict]:
    return []  # a crag page already lists every route — nothing to discover


def _disciplines(label, pitch_count: int) -> list[str]:
    out = []
    d = DISCIPLINE_MAP.get((label or "").strip().lower())
    if d:
        out.append(d)
    if pitch_count and pitch_count >= 2 and "multi-pitch" not in out:
        out.append("multi-pitch")
    return out


def map_routes(raw: dict) -> list[dict]:
    """UKC gives the British adjectival grade (→ grade_system_code 'BAS') + tech
    grade, and often pitch-by-pitch `desc` prose — kept as `_raw_description`
    for the LLM tagger (protection/hazards/character/feature)."""
    routes = []
    for r in raw.get("routes") or []:
        adj, tech = r.get("adjectival_grade"), r.get("tech_grade")
        original = " ".join(x for x in (adj, tech) if x) or None
        pitches = int(r["pitches"]) if r.get("pitches") else None
        stars = int(r["stars"]) if r.get("stars") not in (None, "") else None
        routes.append({
            "name": r["name"],
            "original_grade": original,
            "grade_system_code": "BAS" if adj else None,   # British Adjectival System
            "length_m": r.get("length_m"),
            "pitches_count": pitches,
            "bolts_count": None,
            "protection_code": None,
            "stars": stars,
            "tags": {"disciplines": _disciplines(r.get("discipline_label"), pitches or 0),
                     "features": [], "character": []},
            "external_refs": [{"source_id": SOURCE_ID, "external_id": str(r["id"]),
                               "url": r.get("url")}],
            "_raw_description": r.get("description") or "",
        })
    return routes

#!/usr/bin/env python3
"""theCrag source — worldwide coverage (~1M routes), the real path off US-only
OpenBeta. Public pages via headless browser (thecrag_client.py, Cloudflare-
fronted); scraped with Michel's permission, raw never leaves the private repo.

Uniform source interface (same shape as openbeta.py): NEEDS_BROWSER, fetch,
children, map_routes. theCrag's tree is area pages: a parent lists child areas,
a leaf lists routes — never both. Seeded by URL (no name search), so the worker
takes --seed <url> --path "<breadcrumb>".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "corpus" / "tools"))
import thecrag_client as tc  # noqa: E402

SOURCE_ID = "thecrag"
NEEDS_BROWSER = True

# theCrag styleStub (already lowercase) → our discipline enum.
DISCIPLINE_MAP = {
    "trad": "trad", "sport": "sport", "boulder": "bouldering", "aid": "aid",
    "alpine": "alpine", "ice": "ice", "mixed": "mixed", "topRope": "tr",
    "toprope": "tr", "dws": "deepwatersolo",
}


def fetch(external_id: str, session) -> dict:
    return tc.fetch_area(session, external_id)


def children(raw: dict) -> list[dict]:
    return [{"external_id": c["url"], "name": c["name"], "total": None}
            for c in (raw.get("children") or [])]


def _disciplines(style_stub, pitch_count: int) -> list[str]:
    out = []
    d = DISCIPLINE_MAP.get((style_stub or "").strip())
    if d:
        out.append(d)
    if pitch_count and pitch_count >= 2 and "multi-pitch" not in out:
        out.append("multi-pitch")
    return out


def map_routes(raw: dict) -> list[dict]:
    """theCrag's listing carries no route description prose (only the grade
    atom + structural fields), so `_raw_description` is honestly empty — the
    LLM tagger will return empty tags, and the mechanical fields carry the load."""
    routes = []
    for r in raw.get("routes") or []:
        grade = (r.get("gradeAtom") or {}).get("grade") or None
        pitches = int(r["pitches"]) if r.get("pitches") else None
        length_m = (r.get("displayHeight") or [None])[0]
        stars = int(r["stars"]) if r.get("stars") not in (None, "") else None
        routes.append({
            "name": r["name"],
            "original_grade": grade,
            "grade_system_code": None,          # theCrag mixes systems by context; curator resolves
            "length_m": length_m,
            "pitches_count": pitches,
            "bolts_count": None,
            "protection_code": None,
            "stars": stars,
            "tags": {"disciplines": _disciplines(r.get("styleStub"), pitches or 0),
                     "features": [], "character": []},
            "external_refs": [{"source_id": SOURCE_ID, "external_id": str(r["id"]),
                               "url": r.get("url")}],
            "_raw_description": "",
        })
    return routes

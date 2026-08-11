"""OpenBeta source — the one real geo API of the three (CC-licensed, keyless
GraphQL). Discovery is `cragsNear` (verified live 2026-08-11: bbox center +
covering radius, then filter to the box — there is also `cragsWithin(bbox)`
but it 502/504'd on every live attempt, so the working query won).

Reuses corpus/tools/openbeta_client.py for transport + the area query
(schema verified live 2026-07-06); grade/discipline mapping harvested from
the superseded PR #1 adapter and reshaped to the shared inventory schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "corpus" / "tools"))
import openbeta_client as ob  # noqa: E402

from .. import geo, schema  # noqa: E402

SOURCE_ID = "openbeta"
NEEDS_BROWSER = False
DELAY_S = 0.7

def _post(query: str, variables: dict):
    """Not ob._post: the live API is currently answering in ~45s (measured
    2026-08-11), past the client's hardcoded 30s timeout — so post with a 90s
    timeout, and retry socket drops as well as coded HTTP errors."""
    import json as _json
    import time as _t
    import urllib.request as _rq
    body = _json.dumps({"query": query, "variables": variables}).encode()
    req = _rq.Request(ob.GRAPHQL_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent)",
    })
    last = None
    for attempt in range(4):
        try:
            with _rq.urlopen(req, timeout=90) as resp:
                payload = _json.load(resp)
            if payload.get("errors"):
                raise ob.OpenBetaError(str(payload["errors"]))
            return payload["data"]
        except (TimeoutError, OSError, ob.OpenBetaError) as e:
            last = e
            _t.sleep(3 * (attempt + 1))
    raise last

CRAGS_NEAR_QUERY = """
query($ll: Point, $max: Int) {
  cragsNear(lnglat: $ll, maxDistance: $max, includeCrags: true) {
    crags { uuid areaName totalClimbs metadata { lat lng leaf } }
  }
}
"""

DISCIPLINE_MAP = {
    "trad": "trad", "sport": "sport", "bouldering": "bouldering", "alpine": "alpine",
    "snow": "snow", "ice": "ice", "mixed": "mixed", "aid": "aid", "tr": "tr",
    "deepwatersolo": "deepwatersolo",
}
SAFETY_MAP = {"G": "G", "PG": "PG", "PG13": "PG-13", "R": "R", "X": "X"}
# area gradeContext -> (which grades{} key to read, our grade-system tag)
GRADE_CONTEXT = {
    "US": ("yds", "yds"), "FR": ("french", "french"), "UK": ("uiaa", "uiaa"),
    "AU": ("ewbank", "ewbank"), "ZA": ("ewbank", "ewbank"),
}


def plan(bbox: geo.Bbox, session=None, root=None) -> list[dict]:
    lat, lon = geo.center(bbox)
    radius = geo.covering_radius_m(bbox)
    data = _post(CRAGS_NEAR_QUERY, {"ll": {"lat": lat, "lng": lon}, "max": radius})
    items = []
    for group in data["cragsNear"] or []:
        for c in group.get("crags") or []:
            meta = c.get("metadata") or {}
            if not geo.contains(bbox, meta.get("lat"), meta.get("lng")):
                continue  # cragsNear is a circle covering the box; trim the corners
            if not c.get("totalClimbs"):
                continue
            items.append({"kind": "crag", "id": c["uuid"], "name": c["areaName"],
                          "lat": meta.get("lat"), "lon": meta.get("lng")})
    return items


def fetch(item: dict, session=None) -> dict:
    return _post(ob.AREA_DETAIL_QUERY, {"id": item["id"]})["area"]


def parse(item: dict, payload: dict, bbox: geo.Bbox) -> dict:
    meta = payload.get("metadata") or {}
    gc = payload.get("gradeContext")
    routes = [_route(c, gc) for c in (payload.get("climbs") or [])]
    c = schema.crag(
        SOURCE_ID, payload["uuid"], payload["areaName"],
        lat=meta.get("lat"), lon=meta.get("lng"),
        url=f"https://openbeta.io/areas/{payload['uuid']}",
        country=(payload.get("pathTokens") or [None])[0],
        region=" / ".join((payload.get("pathTokens") or [])[1:-1]) or None,
        routes=routes,
    )
    # non-leaf areas inside the box can slip into cragsNear; descend into them
    children = [{"kind": "crag", "id": ch["uuid"], "name": ch["areaName"]}
                for ch in (payload.get("children") or []) if ch.get("totalClimbs")]
    return {"crags": [c] if routes else [], "next": children}


def _route(climb: dict, grade_context: str | None) -> dict:
    grades = climb.get("grades") or {}
    key, system = GRADE_CONTEXT.get((grade_context or "").upper(), ("yds", "yds"))
    value = grades.get(key)
    if value and system == "yds" and value.upper().startswith("V"):
        system = "vscale"  # OpenBeta stores US boulder V-grades in the yds field
    pitches = len(climb.get("pitches") or []) or None
    t = climb.get("type") or {}
    disciplines = [DISCIPLINE_MAP[k] for k, v in t.items() if v and k in DISCIPLINE_MAP]
    meta = climb.get("metadata") or {}
    content = climb.get("content") or {}
    length = climb.get("length")
    return schema.route(
        climb["uuid"], climb["name"],
        grade_value=value, grade_system=system if value else None,
        length_m=length if (length or 0) > 0 else None,   # -1 = OpenBeta's unknown sentinel
        pitches=pitches,
        bolts_count=climb.get("boltsCount") if (climb.get("boltsCount") or 0) >= 0 else None,
        protection=SAFETY_MAP.get((climb.get("safety") or "").upper()),
        disciplines=disciplines,
        fa=climb.get("fa") or None,
        url=f"https://openbeta.io/climbs/{climb['uuid']}",
        description=content.get("description") or "",
    )

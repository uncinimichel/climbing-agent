"""camptocamp.org — the collaborative Alps DB, and the cleanest source of the
lot: a real public JSON API (api.camptocamp.org, CC BY-SA content) with NATIVE
bbox queries — no tree walking, no HTML. Verified live 2026-08-13: 86 climbing
waypoints in a small Chamonix box, route lists per waypoint with French grades
(rock_free_rating), equipment rating, orientations and single/multi type.

Coordinates are EPSG:3857 web-mercator both ways: our WGS84 bbox converts for
the query, waypoint/route points convert back. Discipline is deliberately NOT
guessed from equipment_rating (P1 usually means sport, but that's inference);
only `climbing_outdoor_type == "multi"` -> multi-pitch is taken, since it's
source-stated structure. Coverage is Alps-heavy (Marche: 0 — checked), so this
source earns its keep on alpine/trad bboxes, which is the trip planner's home
turf anyway.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request

from .. import geo, schema

SOURCE_ID = "camptocamp"
NEEDS_BROWSER = False
DELAY_S = 1.0

API = "https://api.camptocamp.org"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"
_R = 6378137.0

ROCK_MAP = {  # c2c rock_types (French) -> taxonomy rock_type codes
    "calcaire": "limestone", "granit": "granite", "granite": "granite",
    "gneiss": "gneiss", "quartzite": "quartzite", "gres": "sandstone",
    "grès": "sandstone", "basalte": "basalt", "conglomerat": "conglomerate",
    "conglomérat": "conglomerate", "schiste": "schist", "dolomie": "dolomite",
    "calcaire_dolomitique": "dolomite", "andesite": "andesite", "rhyolite": "rhyolite",
}


def _to_merc(lat: float, lon: float) -> tuple[float, float]:
    return (_R * math.radians(lon),
            _R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _to_wgs(x: float, y: float) -> tuple[float, float]:
    return (math.degrees(2 * math.atan(math.exp(y / _R)) - math.pi / 2),
            math.degrees(x / _R))


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _title(doc: dict) -> str:
    locs = doc.get("locales") or []
    for lang in ("en", "it", "fr", "de", "es"):
        for l in locs:
            if l.get("lang") == lang and l.get("title"):
                return l["title"]
    return (locs[0].get("title") if locs else None) or "?"


def _point(doc: dict) -> tuple[float | None, float | None]:
    try:
        x, y = json.loads(doc["geometry"]["geom"])["coordinates"]
        return _to_wgs(x, y)
    except Exception:
        return None, None


def plan(bbox: geo.Bbox, session=None, root=None) -> list[dict]:
    s, w, n, e = bbox
    xmin, ymin = _to_merc(s, w)
    xmax, ymax = _to_merc(n, e)
    items, offset = [], 0
    while True:
        data = _get("/waypoints", {"wtyp": "climbing_outdoor",
                                   "bbox": f"{xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f}",
                                   "limit": 100, "offset": offset})
        docs = data.get("documents") or []
        for doc in docs:
            lat, lon = _point(doc)
            if not geo.contains(bbox, lat, lon):
                continue
            items.append({"kind": "crag", "id": str(doc["document_id"]),
                          "name": _title(doc), "lat": lat, "lon": lon})
        offset += len(docs)
        if offset >= (data.get("total") or 0) or not docs:
            break
        time.sleep(DELAY_S)
    return items


def fetch(item: dict, session=None) -> dict:
    wp = _get(f"/waypoints/{item['id']}")
    routes, offset = [], 0
    while True:
        data = _get("/routes", {"w": item["id"], "limit": 100, "offset": offset})
        docs = data.get("documents") or []
        routes.extend(docs)
        offset += len(docs)
        if offset >= (data.get("total") or 0) or not docs:
            break
        time.sleep(DELAY_S)
    return {"waypoint": wp, "routes": routes}


def parse(item: dict, payload: dict, bbox: geo.Bbox) -> dict:
    wp = payload.get("waypoint") or {}
    rock = None
    for rt in wp.get("rock_types") or []:
        rock = ROCK_MAP.get((rt or "").strip().lower())
        if rock:
            break
    aspect = ",".join(wp.get("orientations") or []) or None
    prose = []
    for l in wp.get("locales") or []:
        for key in ("summary", "description", "access", "access_period"):
            if l.get(key):
                prose.append(l[key])
        break  # one language's prose is enough for the tagger
    routes = [_route(doc) for doc in payload.get("routes") or []]
    c = schema.crag(
        SOURCE_ID, item["id"], item["name"],
        lat=item.get("lat"), lon=item.get("lon"),
        url=f"https://www.camptocamp.org/waypoints/{item['id']}",
        rock_type=rock, aspect=aspect,
        description="\n\n".join(prose),
        routes=routes,
    )
    return {"crags": [c] if routes else [], "next": []}


def _route(doc: dict) -> dict:
    grade = doc.get("rock_free_rating") or doc.get("global_rating")
    disciplines = []
    acts = doc.get("activities") or []
    if "ice_climbing" in acts:
        disciplines.append("ice")
    if "mountain_climbing" in acts:
        disciplines.append("alpine")
    if doc.get("climbing_outdoor_type") == "multi":
        disciplines.append("multi-pitch")  # source-stated, not inferred
    summary = ""
    for l in doc.get("locales") or []:
        if l.get("summary"):
            summary = l["summary"]
            break
    return schema.route(
        doc["document_id"], _title(doc),
        grade_value=grade, grade_system="french" if grade else None,
        length_m=doc.get("height_diff_difficulties"),
        disciplines=disciplines,
        url=f"https://www.camptocamp.org/routes/{doc['document_id']}",
        description=summary,
    )

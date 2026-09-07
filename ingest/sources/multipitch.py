"""multi-pitch.com — our own site (Dan Knight + Michel Uncini, source at
github.com/dankni/multi-pitch), CC BY-SA 4.0, own topo images CC BY 4.0.
51 published climbs across 19 countries; 6 routes on 5 crags inside the Costa
Blanca bbox (Puig Campana ×2, Peñón de Ifach ×2, Penya Roc, El Castellet).

Its value is not volume — it is a SELF-CONSISTENCY CHECK. These are routes we
already curated by hand, so running them back through crawl -> merge tests
whether the pipeline reproduces our own judgement.

Enumeration is one JSON file (/data/data.json) with every climb, so `plan` needs
exactly one fetch and prunes the bbox client-side. A crag here is a cliff; the
per-cliff attributes the site states (aspect, rock, approach) live on the route
page, so one route page per cliff is fetched for them and the remaining routes
of that cliff come from the JSON with their own URLs kept for later enrichment.

Note: some tileImage entries are third-party Flickr with `attributionText` /
`atributionURL` (the typo is the site's) under an unstated licence — credit
those separately; CC BY-SA does not cover them.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "multipitch"
NEEDS_BROWSER = False
DELAY_S = 1.0

BASE = "https://www.multi-pitch.com"
DATA = f"{BASE}/data/data.json"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"

_GRADE_SYS = {"BAS": "uk_adjectival_tech", "UIAA": "uiaa", "FS": "french",
              "ALP": "alpine", "YDS": "yds", "N": "norwegian"}
_ROCK = {"limestone": "limestone", "granite": "granite", "sandstone": "sandstone",
         "gritstone": "gritstone", "gabbro": "gabbro", "dolerite": "dolerite",
         "quartzite": "quartzite", "rhyolite": "rhyolite", "schist": "schist",
         "gneiss": "gneiss", "basalt": "basalt", "slate": "slate",
         "conglomerate": "conglomerate", "dolomite": "dolomite", "volcanic": "volcanic"}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _slug(s: str) -> str:
    """The site's own slug: lowercase, spaces to dashes, accents KEPT
    ('espolón-central-on-puig-campana')."""
    s = s.lower().replace("'", "").replace(",", "").replace(".", "")
    return re.sub(r"[\s_]+", "-", s.strip())


def _url(route_name: str, cliff: str) -> str:
    return f"{BASE}/climbs/{_slug(route_name)}-on-{_slug(cliff)}/"


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    data = json.loads(_get(root or DATA))
    by_cliff: dict[str, list[dict]] = {}
    for c in data.get("climbs", []):
        if c.get("status") != "publish":
            continue
        try:
            lat, lon = [float(x) for x in (c.get("geoLocation") or "").split(",")]
        except ValueError:
            continue
        if not geo.contains(bbox, lat, lon):
            continue
        by_cliff.setdefault(c["cliff"], []).append(dict(c, _lat=lat, _lon=lon))

    items = []
    for cliff, climbs in sorted(by_cliff.items()):
        items.append({"kind": "cliff", "name": cliff, "id": _slug(cliff),
                      "url": _url(climbs[0]["routeName"], cliff),
                      "climbs": climbs})
    return items


def fetch(item: dict, session=None) -> str:
    return _get(urllib.parse.quote(item["url"], safe=":/"))


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    climbs = item["climbs"]
    lat = sum(c["_lat"] for c in climbs) / len(climbs)
    lon = sum(c["_lon"] for c in climbs) / len(climbs)
    if not geo.contains(bbox, lat, lon):
        return {"crags": [], "next": []}

    text = soup.get_text(" ", strip=True)
    rock = next((code for word, code in _ROCK.items() if re.search(rf"\b{word}\b", text, re.I)), None)
    aspect = None
    m = re.search(r"\b(N|NE|E|SE|S|SW|W|NW)\b\s+(?:facing|aspect)", text, re.I)
    if m:
        aspect = m.group(1).upper()

    prose = []
    for sec in soup.select("section"):
        t = sec.get_text(" ", strip=True)
        if t:
            prose.append(t)

    routes = []
    for c in climbs:
        grade = c.get("originalGrade") or c.get("tradGrade")
        extras = []
        for flag in ("abseil", "tidal", "loose", "polished", "seepage", "traverse", "boat"):
            if c.get(flag):
                extras.append(flag)
        if c.get("approachTime"):
            extras.append(f"approach {c['approachTime']} min")
        if c.get("tradGrade") and c.get("techGrade"):
            extras.append(f"BAS {c['tradGrade']} {c['techGrade']}")
        routes.append(schema.route(
            source_id=str(c["id"]), name=c["routeName"],
            grade_value=grade or None,
            grade_system=_GRADE_SYS.get(c.get("gradeSys")) if grade else None,
            length_m=c.get("length"), pitches=c.get("pitches"),
            stars=None, bolts_count=None, protection=None,
            disciplines=["trad"],   # the site's whole premise; multi-pitch derived
            fa=None, url=_url(c["routeName"], c["cliff"]),
            description="; ".join(extras),
        ))

    crag = schema.crag(
        SOURCE_ID, item["id"], item["name"],
        lat=lat, lon=lon, url=item["url"], country=climbs[0].get("country"),
        region=climbs[0].get("county"), rock_type=rock, aspect=aspect,
        description="\n".join(prose), routes=routes)
    return {"crags": [crag], "next": []}

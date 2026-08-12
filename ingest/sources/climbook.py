"""Climbook (climbook.com) — the Italian community crag DB, found by the
2026-08-12 Italy research: ~84 Marche crags / ~7,600 routes where theCrag has
a handful and Mountain Project has zero. Robots: `User-agent: * / Disallow:`
(everything allowed), no terms/legal page exists (checked homepage + content
pages), plain server-rendered PHP with no bot protection — polite plain-HTTP
scraping. Also covers French/Spanish regions (same /regioni tree), so this
adapter is not Italy-only.

Geography: Climbook pages carry NO coordinates (checked crag + region pages
live), so the bbox is satisfied by REGION MEMBERSHIP: bbox center -> Nominatim
admin region ("Marche") -> /falesie region index -> region page -> crag list.
Crags get lat/lon null — never guessed (a region is coarser than a bbox;
crags in the region but outside the box ARE included and flagged by their
null coords; the LLM/link phases can place them later).

Route data: /falesie/<id>/<slug>/vie is the full table — # | Nome | Grado
("6b 6b+.1" = setter grade + community grade with vote count) | Ripetizioni |
Note | Bellezza. Grades are French-scale sport grades (Italian falesie);
multipitch appears as separate L1/L2/L3 rows — kept verbatim as rows, the
LLM phase can regroup. The Note column often names the sector — kept as the
route description (real prose for the tagger).
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "climbook"
NEEDS_BROWSER = False
DELAY_S = 1.5

BASE = "https://climbook.com"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"


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


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _region_from_bbox(bbox: geo.Bbox) -> tuple[str, str | None]:
    lat, lon = geo.center(bbox)
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=5"
        "&accept-language=en",  # English names — keys must match across sources ("Italy", not "Italia")
        headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        addr = json.load(resp).get("address") or {}
    region = addr.get("state") or addr.get("region")
    if not region:
        raise RuntimeError("could not resolve an admin region for this bbox — pass --root <climbook region url>")
    return region, addr.get("country")


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    country = None
    if root:
        region_url, region_name = root, root.rstrip("/").rsplit("/", 1)[-1]
    else:
        region_name, country = _region_from_bbox(bbox)
        index = _get(f"{BASE}/falesie")
        want = _slug(region_name)
        m = re.search(rf'href="({BASE}/regioni/\d+[^"]*{re.escape(want)}[^"]*)"', index)
        if not m:
            raise RuntimeError(f"no climbook region matching {region_name!r} — pass --root <region url>")
        region_url = m.group(1)
    html = _get(region_url)
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select(f'a[href^="{BASE}/falesie/"]'):
        href = a["href"].rstrip("/")
        m = re.match(rf"{BASE}/falesie/(\d+)/([a-z0-9-]+)$", href)
        name = a.get_text(strip=True)
        if not m or not name or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        items.append({"kind": "crag", "id": f"{m.group(1)}/{m.group(2)}", "name": name,
                      "region": region_name, "country": country, "url": href})
    return items


def fetch(item: dict, session=None) -> str:
    return _get(f"{BASE}/falesie/{item['id']}/vie")


GRADE_RE = re.compile(r"^([1-9][abc][+]?|\?)")


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    routes = []
    for tr in soup.select("tr"):
        link = tr.select_one(f'a[href^="{BASE}/vie/"]')
        if not link:
            continue
        m = re.match(rf"{BASE}/vie/(\d+)/", link["href"])
        if not m:
            continue
        cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
        grade_cell = next((c for c in cells if GRADE_RE.match(c)), "")
        gm = GRADE_RE.match(grade_cell)
        grade = gm.group(1) if gm and gm.group(1) != "?" else None
        note = cells[-3] if len(cells) >= 3 else ""  # Note column precedes Bellezza + actions
        routes.append(schema.route(
            m.group(1), link.get_text(strip=True),
            grade_value=grade, grade_system="french" if grade else None,
            disciplines=["sport"],
            url=link["href"],
            description=note if note and not GRADE_RE.match(note) else "",
        ))
    c = schema.crag(
        SOURCE_ID, item["id"].split("/")[0], item["name"],
        lat=None, lon=None,  # climbook pages carry no GPS — never guessed
        url=item["url"], country=item.get("country"), region=item.get("region"),
        routes=routes,
    )
    return {"crags": [c] if routes else [], "next": []}

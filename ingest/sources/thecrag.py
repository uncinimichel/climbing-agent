"""theCrag source — worldwide coverage, but no open geo endpoint (their map
loads nothing headless, and probing endpoint guesses gets Cloudflare-BLOCKED,
verified 2026-08-11 — so no endpoint guessing, ever). Discovery is therefore
an area-tree walk with bbox pruning: every theCrag area page embeds its own
bounding box (`bbox: [[lat,lng],[lat,lng]]` in an inline script) plus
place:location meta coords, so a subtree whose box misses the query box is
dropped without fetching its children.

The walk starts from a root area URL: `--root` if given, else the bbox center
is reverse-geocoded (Nominatim) to a country and looked up in ROOTS. NB URL
slugs lie about the hierarchy — Fair Head lives at /ireland/fair-head but its
breadcrumb is United Kingdom > Northern Ireland (verified live 2026-08-11), so
the walk trusts breadcrumbs/children, never URL prefixes; when the country
mapping is ambiguous, pass --root explicitly rather than let the walk guess.

Page parsing (routes/children) rides the proven corpus/tools/thecrag_client.py.
Scraped with Michel's permission; raw stays out of the public repo.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "corpus" / "tools"))
import thecrag_client as tc  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from .. import geo, schema  # noqa: E402

SOURCE_ID = "thecrag"
NEEDS_BROWSER = True
DELAY_S = 2.0

ROOTS = {
    "ie": "https://www.thecrag.com/en/climbing/ireland",
    "gb": "https://www.thecrag.com/en/climbing/united-kingdom",
    "us": "https://www.thecrag.com/en/climbing/united-states",
    "fr": "https://www.thecrag.com/en/climbing/france",
    "es": "https://www.thecrag.com/en/climbing/spain",
    "it": "https://www.thecrag.com/en/climbing/italy",
    "ch": "https://www.thecrag.com/en/climbing/switzerland",
    "at": "https://www.thecrag.com/en/climbing/austria",
    "de": "https://www.thecrag.com/en/climbing/germany",
}

_BBOX_RE = re.compile(
    r"bbox:\s*\[\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]\s*,\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]\s*\]")
_META_RE = re.compile(
    r'place:location:(latitude|longitude)"\s+content="(-?[\d.]+)"')


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    url = root or _resolve_root(bbox)
    return [{"kind": "area", "url": url, "name": "(walk root)"}]


def _resolve_root(bbox: geo.Bbox) -> str:
    lat, lon = geo.center(bbox)
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=3",
        headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        cc = (json.load(resp).get("address") or {}).get("country_code", "")
    if cc not in ROOTS:
        raise RuntimeError(
            f"no known theCrag root for country {cc!r} — pass --root <theCrag area url>")
    return ROOTS[cc]


def fetch(item: dict, session=None) -> str:
    return session.fetch(item["url"])


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    page_bbox = _page_bbox(html)
    if page_bbox and not geo.intersects(page_bbox, bbox):
        return {"crags": [], "next": []}  # whole subtree is elsewhere — prune

    soup = BeautifulSoup(html, "html.parser")
    area = _area_from_soup(soup, item["url"])
    lat, lon = _page_point(html)

    if area["routes"]:
        # leaf area = a crag; only keep it if it's actually in the box (a leaf
        # with no coords at all is kept — never drop a venue by guesswork)
        if (lat is not None or lon is not None) and not geo.contains(bbox, lat, lon):
            return {"crags": [], "next": []}
        c = schema.crag(SOURCE_ID, item["url"], area["name"] or item.get("name") or "?",
                        lat=lat, lon=lon, url=item["url"],
                        routes=[_route(r) for r in area["routes"]])
        return {"crags": [c], "next": []}

    nxt = [{"kind": "area", "url": ch["url"], "name": ch["name"]}
           for ch in area["children"]]
    return {"crags": [], "next": nxt}


def _area_from_soup(soup: BeautifulSoup, url: str) -> dict:
    """thecrag_client.fetch_area minus the fetch — same route parsing, but
    children come from the `a[data-nid] > span.primary-node-name` nav markers:
    the client's /area/<id>-only matcher missed pretty-URL children entirely
    (the Ireland page lists Dalkey Quarry at /ireland/dalkey-quarry, no /area/
    id — found live 2026-08-11 when a country walk yielded zero crags). Only
    hrefs under this page's own path count: the same nav also lists sibling
    countries."""
    from urllib.parse import urlparse
    title = soup.title.get_text(strip=True) if soup.title else ""
    name = title.split(",")[0].strip() if title else None
    base_path = urlparse(url).path.rstrip("/")
    routes = tc._route_records(soup)
    children = []
    if not routes:
        # This page's real children live in div.regions__nav, in the ULs that
        # are NOT class="embed-menu" (embed-menu holds the ancestor menus —
        # self, siblings, whole-continent country lists). Crucially, child
        # hrefs are NOT always under this page's path: Fair Head sits under
        # /united-kingdom/northern-ireland but links as /ireland/fair-head
        # (historical slug, verified live 2026-08-11) — so no path filtering.
        seen = set()
        for nav in soup.select("div.regions__nav"):
            for ul in nav.find_all("ul"):
                if "embed-menu" in (ul.get("class") or []):
                    continue
                for a in ul.select("a[data-nid]"):
                    span = a.select_one("span.primary-node-name")
                    href = (a.get("href") or "").split("#")[0].rstrip("/")
                    if not span or not href.startswith("/en/climbing/") or href in seen:
                        continue
                    seen.add(href)
                    children.append({"url": "https://www.thecrag.com" + href,
                                     "name": span.get_text(strip=True)})
        if not children:  # leaf-adjacent pages without the nav: the client's matcher
            children = tc._child_areas(soup, base_path)
    return {"url": url, "name": name, "children": children, "routes": routes}


def _page_bbox(html: str) -> geo.Bbox | None:
    m = _BBOX_RE.search(html)
    if not m:
        return None
    lat1, lon1, lat2, lon2 = (float(x) for x in m.groups())
    return (min(lat1, lat2), min(lon1, lon2), max(lat1, lat2), max(lon1, lon2))


def _page_point(html: str) -> tuple[float | None, float | None]:
    vals = {k: float(v) for k, v in _META_RE.findall(html)}
    return vals.get("latitude"), vals.get("longitude")


DISCIPLINE_MAP = {
    "trad": "trad", "sport": "sport", "boulder": "bouldering", "aid": "aid",
    "alpine": "alpine", "ice": "ice", "mixed": "mixed", "topRope": "tr",
    "toprope": "tr", "dws": "deepwatersolo",
}


def _route(r: dict) -> dict:
    grade = (r.get("gradeAtom") or {}).get("grade") or None
    pitches = int(r["pitches"]) if r.get("pitches") else None
    stars = int(r["stars"]) if r.get("stars") not in (None, "") else None
    disciplines = []
    d = DISCIPLINE_MAP.get((r.get("styleStub") or "").strip())
    if d:
        disciplines.append(d)
    height = r.get("displayHeight")
    length_m = height[0] if isinstance(height, list) and height else None
    return schema.route(
        r["id"], r["name"],
        grade_value=grade, grade_system=None,  # theCrag mixes systems by regional context
        length_m=length_m, pitches=pitches, stars=stars,
        disciplines=disciplines, url=r.get("url"),
        description="",  # listings carry no prose — honestly empty
    )

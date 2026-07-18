"""theCrag scraper — their developer API is real but gated behind a
review-approved application key we don't have; pages are fetched via headless
browser (browser_fetch.py) instead, since Cloudflare protects the site.
Scraping is done with Michel's direct permission from theCrag — see the
decision log in knowledge/roadmap/ingestion-plan.md.

theCrag's area tree is real HTML pages, not a JSON API: a parent area page
links to child areas (`/area/<id>`), a leaf area page lists routes directly,
each as a `<div class="route" data-nid="..." data-route-tick="{...json...}">`
— verified live against real Fair Head pages 2026-07-06, not guessed.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from browser_fetch import BrowserSession


def _route_records(soup: BeautifulSoup) -> list[dict]:
    """theCrag's own per-route JSON: id, name, gradeAtom.grade, stars,
    styleStub (discipline, already lowercase — trad/sport/...), and
    pitches + maybeMultipitch when the route has pitch data. `url` is added
    from the card's own link (not in data-route-tick)."""
    routes = []
    for div in soup.select("div.route[data-route-tick]"):
        try:
            data = json.loads(html_lib.unescape(div["data-route-tick"]))
        except json.JSONDecodeError:
            continue
        link = div.select_one("a[href*='/route/']")
        data["url"] = "https://www.thecrag.com" + link["href"] if link else None
        routes.append(data)
    return routes


_CHILD_AREA_RE = re.compile(r"^/area/\d+$")


def _child_areas(soup: BeautifulSoup, base_path: str) -> list[dict]:
    """Direct child areas only — `href^="{base_path}/area/"` also matches
    utility links like `.../area/<id>/locate` (a map-pin button, not a real
    sub-area); those 0-route/0-child dead ends wasted ~half the fetches on
    the first real crawl run (verified live 2026-07-06), so the suffix is
    anchored to nothing but digits."""
    seen: dict[str, str] = {}
    for a in soup.select(f'a[href^="{base_path}/area/"]'):
        href = a["href"]
        if not _CHILD_AREA_RE.match(href[len(base_path):]):
            continue
        name = a.get_text(strip=True)
        if href != base_path and name and href not in seen:
            seen[href] = name
    return [{"url": "https://www.thecrag.com" + href, "name": name} for href, name in seen.items()]


def fetch_area(session: BrowserSession, url: str) -> dict:
    """One area page -> {name, url, children: [...], routes: [...]}. A parent
    area has children and no routes on the page; a leaf area has routes
    directly — never both, so `children` is only populated when `routes`
    is empty."""
    html = session.fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else ""
    name = title.split(",")[0].strip() if title else None
    base_path = urlparse(url).path.rstrip("/")

    routes = _route_records(soup)
    children = [] if routes else _child_areas(soup, base_path)

    return {"url": url, "name": name, "children": children, "routes": routes}


if __name__ == "__main__":
    import sys

    url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.thecrag.com/en/climbing/ireland/fair-head/area/12518215"
    )
    with BrowserSession() as session:
        area = fetch_area(session, url)
    print(f"{area['name']!r}: {len(area['children'])} children, {len(area['routes'])} routes")
    for r in area["routes"][:5]:
        print(" ", r)
    for c in area["children"][:5]:
        print(" child:", c)

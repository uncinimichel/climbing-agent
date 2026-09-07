"""Mountain Project (mountainproject.com, onX Maps) — permission held directly
(project agreement: raw stays in the private store and never on the public
site). The onX TOU otherwise prohibits scrapers, and robots.txt sets
Crawl-delay 60, which this adapter honours: DELAY_S is 60.0 and must not be
lowered without a written yes.

Costa Blanca reality check from the 2026-09-05/06 research: 383 routes across
34 sub-areas, but only 1 route on Puig Campana, 1 on Ponoig, 1 on Bernia.
MP is deep on sport crags (Sierra de Toix 48, Bellús 45, Sella 44) and empty on
the multi-pitch mountains — worth running for the roadside days, not for the
trip's main objectives.

Robots-disallowed and therefore untouched: /ajax*, the area map, the search
suggestion endpoint and the old /data API. The sitemap index has no geographic
key, so enumeration is an area-tree walk from a country/region root; area
coordinates are a point, not a bbox, so parents are always expanded and only
leaf areas (those carrying a route table) are pruned on their own GPS.
"""
from __future__ import annotations

import re
import time
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "mountainproject"
NEEDS_BROWSER = False
DELAY_S = 60.0  # robots.txt Crawl-delay — do not lower without written agreement

BASE = "https://www.mountainproject.com"
ROOTS = {"ES": f"{BASE}/area/106111770/spain"}
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"

_TYPE = {"trad": "trad", "sport": "sport", "tr": "tr", "toprope": "tr",
         "alpine": "alpine", "aid": "aid", "ice": "ice", "mixed": "mixed",
         "boulder": "bouldering", "snow": "snow"}
_ROCK = {"limestone": "limestone", "granite": "granite", "sandstone": "sandstone",
         "conglomerate": "conglomerate", "quartzite": "quartzite", "basalt": "basalt",
         "gneiss": "gneiss", "schist": "schist", "slate": "slate", "dolomite": "dolomite"}

_GPS_RE = re.compile(r"GPS:\s*(-?[\d.]+),\s*(-?[\d.]+)")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise last


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    if not root:
        raise RuntimeError(
            "mountainproject needs an explicit walk root (a country root costs one "
            "60s fetch per area) — pass e.g. "
            "--root https://www.mountainproject.com/area/106282611/costa-blanca")
    return [{"kind": "area", "url": root, "name": "(walk root)"}]


def fetch(item: dict, session=None) -> str:
    return _get(item["url"])


def _section(soup: BeautifulSoup, heading: str) -> str:
    for h in soup.select("h2, h3"):
        if heading.lower() in h.get_text(" ", strip=True).lower():
            nxt = h.find_next(["div", "p"])
            if nxt:
                return nxt.get_text(" ", strip=True)
    return ""


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Child areas: always expanded (an MP area has a point, not a bbox, so a
    # parent's coordinate says nothing about where its children are).
    nxt, seen = [], set()
    for a in soup.select('div.lef-nav-row a[href*="/area/"]'):
        href = a["href"].split("?")[0]
        if href in seen:
            continue
        row = a.find_parent("div", class_="lef-nav-row")
        counts = re.findall(r"\d+", row.get_text(" ", strip=True)) if row else []
        if counts and counts[-1] == "0":
            continue  # empty area — nothing to walk to
        seen.add(href)
        nxt.append({"kind": "area", "url": href if href.startswith("http") else BASE + href,
                    "name": a.get_text(" ", strip=True)})

    table = soup.select_one("#left-nav-route-table")
    if not table:
        return {"crags": [], "next": nxt}

    m = _GPS_RE.search(text)
    lat, lon = (float(m.group(1)), float(m.group(2))) if m else (None, None)
    if not geo.contains(bbox, lat, lon):
        return {"crags": [], "next": nxt}

    routes = []
    for tr in table.select("tr"):
        a = tr.select_one('a[href*="/route/"]')
        if not a:
            continue
        rid = re.search(r"/route/(\d+)", a["href"])
        if not rid:
            continue
        grades = {}
        for span in tr.select("span[class^=rate]"):
            cls = " ".join(span.get("class") or [])
            grades[cls.split()[0]] = span.get_text(" ", strip=True)
        # MP renders the rating as N full stars plus an optional half
        full = len(tr.select('img[src$="starBlue.svg"]'))
        half = len(tr.select('img[src$="starBlueHalf.svg"]'))
        stars = (full + 0.5 * half) or None
        # The climb type is in the element's CLASS ("route-type Rock Trad"),
        # never in its text — the text is the grade conversion row.
        type_el = tr.select_one("span.route-type")
        disciplines = []
        if type_el:
            for cls in type_el.get("class") or []:
                code = _TYPE.get(cls.strip().lower())
                if code and code not in disciplines:
                    disciplines.append(code)
        french = grades.get("rateFrench")
        extras = [f"{k.replace('rate', '')}: {v}" for k, v in grades.items()
                  if k != "rateFrench" and v]
        routes.append(schema.route(
            source_id=rid.group(1), name=a.get_text(" ", strip=True),
            grade_value=french or None,
            grade_system="french" if french else None,
            length_m=None, pitches=None, stars=stars, bolts_count=None,
            protection=None, disciplines=disciplines, fa=None,
            url=a["href"] if a["href"].startswith("http") else BASE + a["href"],
            # MP's other grade columns are its own conversions, not source data
            # — kept as prose so nothing downstream mistakes them for a reading.
            description="; ".join(extras)))

    name = re.sub(r"\s+Rock Climbing$", "",
                  soup.h1.get_text(" ", strip=True) if soup.h1 else item.get("name") or "?")
    crumbs = [a.get_text(" ", strip=True) for a in soup.select('div.mb-half a[href*="/area/"]')]
    description = "\n".join(x for x in (_section(soup, "Description"),
                                        _section(soup, "Getting There")) if x)
    crag = schema.crag(
        SOURCE_ID, item["url"].rstrip("/").split("/")[-2], name,
        lat=lat, lon=lon, url=item["url"], country=(crumbs[1] if len(crumbs) > 1 else None),
        region=(crumbs[-1] if crumbs else None),
        rock_type=next((c for w, c in _ROCK.items() if re.search(rf"\b{w}\b", description, re.I)), None),
        aspect=None, description=description, routes=routes)
    return {"crags": [crag], "next": nxt}

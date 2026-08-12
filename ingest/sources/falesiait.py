"""falesia.it — Italian crag-METADATA source (found by our own survey lens
`inurl:falesia`, 2026-08-12; robots allows content paths). Crag pages carry
real GPS (a maps.google.com?q=lat,lon link), rock type ("Roccia Arenaria…")
and access/character prose — but NO route lists (verified live: zero grade
tokens on crag pages). So this source emits routeless crags on purpose: it is
the coordinates-and-prose complement to Climbook, which has Marche's routes
but no GPS. The LLM merge phase joins them.

Structure: homepage nav -> section/<id>/<region>.html -> crag/<id>/<slug>.html
cards. Sections cover Italian regions plus some other countries; v1 supports
the Italian regions (bbox -> Nominatim region name -> section link match).
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

SOURCE_ID = "falesiait"
NEEDS_BROWSER = False
DELAY_S = 1.5

BASE = "https://www.falesia.it"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"

ROCK_MAP = {"arenaria": "sandstone", "calcare": "limestone", "granito": "granite",
            "basalto": "basalt", "gneiss": "gneiss", "conglomerato": "conglomerate",
            "dolomia": "dolomite", "quarzite": "quartzite", "scisto": "schist",
            "ardesia": "slate", "porfido": "volcanic", "calcare dolomitico": "dolomite"}

_GPS_RE = re.compile(r"maps\.google\.com/maps\?q=(-?\d+\.\d+),(-?\d+\.\d+)")
_ROCK_RE = re.compile(r"[Rr]occia\s+([A-Za-zÀ-ú ]{3,25})")


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


def _slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    if root:
        section_url, region = root, root.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
    else:
        lat, lon = geo.center(bbox)
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=5"
            "&accept-language=en",
            headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            addr = json.load(resp).get("address") or {}
        if addr.get("country_code") != "it":
            raise RuntimeError(f"falesia.it v1 covers Italian regions; bbox is in {addr.get('country')!r} — pass --root <section url>")
        region = addr.get("state") or ""
        home = _get(BASE + "/")
        m = re.search(rf'href="(section/\d+/{re.escape(_slugify(region))}\.html)"', home)
        if not m:
            raise RuntimeError(f"no falesia.it section for region {region!r} — pass --root <section url>")
        section_url = f"{BASE}/{m.group(1)}"
    html = _get(section_url)
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select('a[href*="crag/"]'):
        m = re.search(r"crag/(\d+)/([a-z0-9-]+)\.html", a.get("href") or "")
        if not m or m.group(1) in seen:
            continue
        name_el = a.select_one("h5") or a
        name = name_el.get_text(strip=True)
        if not name:
            continue
        seen.add(m.group(1))
        items.append({"kind": "crag", "id": f"{m.group(1)}/{m.group(2)}", "name": name,
                      "region": region, "country": "Italy",
                      "url": f"{BASE}/crag/{m.group(1)}/{m.group(2)}.html"})
    return items


def fetch(item: dict, session=None) -> str:
    return _get(item["url"])


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    gps = _GPS_RE.search(html)
    lat, lon = (float(gps.group(1)), float(gps.group(2))) if gps else (None, None)
    if (lat is not None) and not geo.contains(bbox, lat, lon):
        return {"crags": [], "next": []}  # section is region-wide; trim to the box
    rock = None
    rm = _ROCK_RE.search(html)
    if rm:
        rock = ROCK_MAP.get(rm.group(1).strip().lower().split(" e ")[0])
    soup = BeautifulSoup(html, "html.parser")
    prose = []
    for p in soup.select(".card-text, .justify-side, p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 60 and not t.lower().startswith(("cookie", "questo sito")):
            prose.append(t)
        if len(prose) >= 4:
            break
    c = schema.crag(
        SOURCE_ID, item["id"].split("/")[0], item["name"],
        lat=lat, lon=lon, url=item["url"],
        country=item.get("country"), region=item.get("region"), rock_type=rock,
        description="\n\n".join(dict.fromkeys(prose)),
        routes=[],  # falesia.it has no route lists — crag metadata only, by design
    )
    return {"crags": [c], "next": []}

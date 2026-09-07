"""multilargo.com — the Spanish multi-pitch community DB, found by the
2026-09-05/06 Costa Blanca research: 4,786 routes / 176 zones nationally, and
the best Puig Campana source anywhere (49 routes where Mountain Project has 1).
Multi-pitch only — no single-pitch sport crags, which is exactly the trip
planner's shape.

Licence: contributions are CC BY-SA 4.0 (terms §3) — attribution + share-alike,
so `url` is stored on every crag and route and the credit line travels with the
data. Robots explicitly ALLOWS the AI crawlers by name (ClaudeBot, Claude-Web,
GPTBot …) on content paths and disallows only /api/, /croquis/, /admin and the
edit routes — none of which this adapter touches. Terms §4 asks for no
"scraping masivo … que degrade la plataforma", hence DELAY_S 1.5 and a province
root rather than the national sitemap.

Geography: coordinates are NOT in any index page — they appear on the zone page
as a Google Maps / OSM link pair. So the zone page is the bbox pruning point,
one fetch per zone. `--root https://multilargo.com/escalada/alicante` keeps a
Costa Blanca run to ~20 zone fetches instead of the 186 in the sitemap.

Depth: the zone page carries the FULL route list (name, grade, length, pitches,
sector), so one fetch per zone yields a complete crag. The per-route ficha
(/via/<slug>: 1ª ascensión, Protección, Material, Cuerda, per-pitch breakdown)
is a later enrichment pass — every route keeps its `url` so that pass costs no
re-discovery.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "multilargo"
NEEDS_BROWSER = False
DELAY_S = 1.5

BASE = "https://multilargo.com"
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


def _abs(href: str) -> str:
    return href if href.startswith("http") else BASE + href


def _province_slug(bbox: geo.Bbox) -> str | None:
    """Nominatim -> the /escalada/<provincia> page, so a regional run costs ~20
    zone fetches instead of 186. Returns None when it can't be resolved; the
    caller then falls back to the full sitemap."""
    lat, lon = geo.center(bbox)
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=8"
        "&accept-language=es",  # multilargo slugs are Spanish ("alicante", "castellon")
        headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            addr = json.load(resp).get("address") or {}
    except (TimeoutError, OSError, ValueError):
        return None
    for key in ("county", "province", "state_district", "region", "state"):
        name = addr.get(key)
        if not name:
            continue
        # "Provincia de Alicante" / "Alacant / Alicante" -> "alicante"
        for part in re.split(r"[/,]", name):
            slug = _slug(part)
            slug = re.sub(r"^(provincia|province)-de-", "", slug)
            if slug:
                return slug
    return None


def _slug(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _zone_items(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select('a[href^="/zona/"]'):
        href = a["href"].rstrip("/")
        if href in seen or href == "/zona/nueva":
            continue
        seen.add(href)
        items.append({"kind": "zone", "url": _abs(href),
                      "name": a.get_text(" ", strip=True) or href.rsplit("/", 1)[-1]})
    return items


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    if root:
        path = urllib.parse.urlparse(root).path
        if path.startswith("/zona/"):
            return [{"kind": "zone", "url": _abs(root), "name": path.rsplit("/", 1)[-1]}]
        return _zone_items(_get(_abs(root)))

    slug = _province_slug(bbox)
    if slug:
        try:
            items = _zone_items(_get(f"{BASE}/escalada/{slug}"))
            if items:
                return items
        except (TimeoutError, OSError):
            pass  # fall through to the sitemap

    # No province resolved: every zone in the sitemap, pruned by coords on fetch.
    sitemap = _get(f"{BASE}/sitemap.xml")
    items, seen = [], set()
    for loc in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        if "/zona/" not in loc or loc.rstrip("/").endswith("/zona/nueva"):
            continue
        url = loc.rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        items.append({"kind": "zone", "url": url, "name": url.rsplit("/", 1)[-1]})
    return items


def fetch(item: dict, session=None) -> str:
    return _get(item["url"])


# The separator before `query=`/`mlon=` is "&", "&amp;" or "&" depending on
# whether it came from the server HTML or the inlined RSC payload — so match on
# the parameter itself rather than on the ampersand.
_COORD_RE = re.compile(r"maps/search/\?api=1[^\"']{0,12}?query=(-?\d+\.\d+),(-?\d+\.\d+)")
_COORD_OSM_RE = re.compile(r"mlat=(-?\d+\.\d+)[^\"']{0,12}?mlon=(-?\d+\.\d+)")
_LEN_RE = re.compile(r"(\d+)\s*m\b")
_PITCH_RE = re.compile(r"(\d+)\s*L\b")
_ROCK = {"caliza": "limestone", "granito": "granite", "conglomerado": "conglomerate",
         "arenisca": "sandstone", "cuarcita": "quartzite", "esquisto": "schist",
         "gneis": "gneiss", "basalto": "basalt", "dolomia": "dolomite",
         "pizarra": "slate", "riolita": "rhyolite", "andesita": "andesite"}


def _coords(html: str) -> tuple[float | None, float | None]:
    m = _COORD_RE.search(html) or _COORD_OSM_RE.search(html)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def _rock_type(text: str) -> str | None:
    low = text.lower()
    for es, code in _ROCK.items():
        if es in low:
            return code
    return None


def _disciplines(grade: str | None, protection_text: str) -> list[str]:
    """Mechanical map of what the source itself says — never a guess. Every
    multilargo route is multi-pitch by the site's own premise; the runner's
    schema.route() adds that code from the pitch count, so only the style
    codes are decided here."""
    out = []
    low = protection_text.lower()
    if "deportiv" in low or "equipada" in low and "semi" not in low:
        out.append("sport")
    if "autoprotecc" in low or "fisurero" in low or "friend" in low or "clavo" in low:
        out.append("trad")
    if grade and re.search(r"/A[0-9e]", grade, re.I):
        out.append("aid")
    return out


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    if item["kind"] == "index":
        return {"crags": [], "next": _zone_items(html)}

    lat, lon = _coords(html)
    if not geo.contains(bbox, lat, lon):
        return {"crags": [], "next": []}

    name = soup.h1.get_text(" ", strip=True) if soup.h1 else item.get("name") or "?"
    header = soup.h1.parent.get_text(" ", strip=True) if soup.h1 else ""
    region = None
    m = re.search(rf"{re.escape(name)}\s+([^·]+)", header)
    if m:
        region = re.sub(r"\s+([,;])", r"\1", m.group(1)).strip(" ,")

    # Access prose: the zone page's dl of Cómo llegar / Aproximación / Descenso.
    prose = [header]
    for dl in soup.select("dl"):
        for dt, dd in zip(dl.select("dt"), dl.select("dd")):
            prose.append(f"{dt.get_text(' ', strip=True)}: {dd.get_text(' ', strip=True)}")
    description = "\n".join(p for p in prose if p)

    routes = []
    seen = set()
    for li in soup.select("li.card-link"):
        a = li.select_one('a[href^="/via/"]')
        if not a or a["href"] in seen:
            continue
        seen.add(a["href"])
        rname = li.select_one("span.font-semibold")
        grade_el = li.select_one("span.font-mono")
        grade = grade_el.get_text(strip=True) if grade_el else None
        text = li.get_text(" ", strip=True)
        mlen, mp = _LEN_RE.search(text), _PITCH_RE.search(text)
        sector_el = li.select_one('a[href^="/sector/"]')
        sector = sector_el.get_text(" ", strip=True) if sector_el else None
        routes.append(schema.route(
            source_id=a["href"].rsplit("/", 1)[-1],
            name=(rname.get_text(strip=True) if rname else a.get_text(" ", strip=True)),
            grade_value=grade or None,
            # Roman numerals up to V+, French numerals from 6a, aid suffix /A0-/A5,
            # all as the guidebooks write them. Stored verbatim — comparison is
            # judgement and judgement lives downstream.
            grade_system="spanish_hybrid" if grade else None,
            length_m=int(mlen.group(1)) if mlen else None,
            pitches=int(mp.group(1)) if mp else None,
            stars=None,          # the community vote is usually "—"
            bolts_count=None,
            protection=None,     # stated per route on /via/, not in this list
            disciplines=[],      # ditto; schema.route() still derives multi-pitch
            fa=None,
            url=_abs(a["href"]),
            description=(f"Sector: {sector}" if sector else ""),
        ))

    crag = schema.crag(
        SOURCE_ID, item["url"].rsplit("/", 1)[-1], name,
        lat=lat, lon=lon, url=item["url"], country="ES", region=region,
        rock_type=_rock_type(description), aspect=None,
        description=description, routes=routes)
    return {"crags": [crag], "next": []}

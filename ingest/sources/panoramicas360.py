"""panoramicas360.net — Antonio García-Saúco Iglesias ("Pels"), Alicante,
blogging since 2009. 110 long-route reseñas across 21 Alicante crags, ~65
routes on ~14 crags inside the Costa Blanca bbox, 8 of them on Puig Campana,
each written pitch by pitch. The highest-quality prose of the seven Costa
Blanca sources found by the 2026-09-05/06 research.

RIGHTS: all rights reserved to a named individual. Crawl to the private store,
credit the byline on every record, and NEVER download or rehost the images —
only their URLs. Read /permisos/ and email enlacumbre@panoramicas360.net before
anything from here reaches the public site.

Shape: one post = one route. Coordinates exist only in the author's Google
My Maps KML, which is fetched once in plan(); posts with no placemark inherit
their crag's placemark centroid, and a crag with no placemarks at all is pruned
rather than guessed. The `/croquis-escalada/` index is the crag -> routes
grouping (h2 province, h3 crag, then the route links).

The structured "Resumen de la actividad" block is rendered by the theme from
hidden custom fields, so the WordPress REST `content.rendered` does NOT contain
it — the page HTML must be parsed, which is what this adapter does.
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "panoramicas360"
NEEDS_BROWSER = False
DELAY_S = 1.5

BASE = "https://www.panoramicas360.net"
INDEX = f"{BASE}/croquis-escalada/"
KML = "https://www.google.com/maps/d/kml?mid=1q5DEp0THN39RhfET46WpcnumBpE&forcekml=1"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"

# "Vía" states how the line is protected — the source's own word, mapped
# mechanically. Anything else stays None rather than becoming a guess.
_STYLE = {"limpia": (["trad"], None), "semiequipada": (["trad", "sport"], None),
          "equipada": (["sport"], None), "clasica": (["trad"], None)}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c)).strip()


def _kml_points() -> dict[str, tuple[float, float]]:
    """post URL -> (lat, lon), from the author's own My Maps layer."""
    try:
        kml = _get(KML)
    except (TimeoutError, OSError):
        return {}
    pts = {}
    for pm in re.findall(r"<Placemark>(.*?)</Placemark>", kml, re.S):
        mc = re.search(r"<coordinates>\s*(-?[\d.]+),(-?[\d.]+)", pm)
        if not mc:
            continue
        lon, lat = float(mc.group(1)), float(mc.group(2))
        for href in re.findall(r"https?://(?:www\.)?panoramicas360\.net/[^\s\"'<>]+", pm):
            pts[href.rstrip("/").split("#")[0]] = (lat, lon)
    return pts


def _index_groups(html: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(province, crag, [(post_url, title), ...]), ...] from /croquis-escalada/."""
    soup = BeautifulSoup(html, "html.parser")
    groups, province, crag, posts = [], None, None, []
    for el in soup.find_all(["h2", "h3", "a"]):
        if el.name == "h2":
            if crag and posts:
                groups.append((province, crag, posts))
            province = re.sub(r"^Escalada en\s+", "", el.get_text(" ", strip=True))
            crag, posts = None, []
        elif el.name == "h3":
            if crag and posts:
                groups.append((province, crag, posts))
            crag, posts = el.get_text(" ", strip=True), []
        elif el.name == "a" and crag:
            href = (el.get("href") or "").rstrip("/")
            if (href.startswith(BASE) and href != INDEX.rstrip("/")
                    and "/categoria/" not in href and "/croquis-escalada" not in href):
                title = el.get_text(" ", strip=True)
                if title and (href, title) not in posts:
                    posts.append((href, title))
    if crag and posts:
        groups.append((province, crag, posts))
    return groups


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    groups = _index_groups(_get(root or INDEX))
    pts = _kml_points()

    items = []
    for province, crag, posts in groups:
        located = [pts[u] for u, _ in posts if u in pts]
        if not located:
            continue  # no coordinate anywhere for this crag — pruned, never guessed
        clat = sum(p[0] for p in located) / len(located)
        clon = sum(p[1] for p in located) / len(located)
        if not geo.contains(bbox, clat, clon):
            continue
        for url, title in posts:
            lat, lon = pts.get(url, (clat, clon))
            items.append({"kind": "post", "url": url, "name": title, "crag": crag,
                          "region": province, "lat": lat, "lon": lon})
    return items


def fetch(item: dict, session=None) -> str:
    return _get(urllib.parse.quote(item["url"], safe=":/"))


def _properties(soup: BeautifulSoup) -> dict[str, str]:
    """The theme renders the summary block twice (mobile + desktop); first wins."""
    out = {}
    txts = soup.select(".route-properties__txt")
    vals = soup.select(".route-properties__value")
    for t, v in zip(txts, vals):
        key = _norm(t.get_text(" ", strip=True))
        if key and key not in out:
            out[key] = v.get_text(" ", strip=True)
    return out


_NUM_RE = re.compile(r"([\d.]+)")


def _int(s: str | None) -> int | None:
    if not s:
        return None
    m = _NUM_RE.search(s.replace(".", ""))
    return int(m.group(1)) if m else None


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    if not geo.contains(bbox, item.get("lat"), item.get("lon")):
        return {"crags": [], "next": []}
    soup = BeautifulSoup(html, "html.parser")
    props = _properties(soup)

    title = soup.h1.get_text(" ", strip=True) if soup.h1 else item["name"]
    # Two title shapes on this blog:
    #   "Escalada en el Puig Campana. Vía Ángel Cerrillo 450 m, IV+/V"
    #   "Vía Bong-Bong (140 m, V) · Penya d'Alacant"
    name = re.sub(r"^Escalada en (?:el |la |los |las )?[^.]*\.\s*", "", title)
    name = re.sub(r"\s*[\(\[]\s*\d+\s*m\b.*$", "", name)   # "(140 m, V) · sector"
    name = re.sub(r"\s+\d+\s*m\s*[,·].*$", "", name)       # "450 m, IV+/V"
    name = name.strip(" ·-–—(,.") or title

    grade = props.get("dificultad")
    style = props.get("via")
    disciplines, protection = list(_STYLE.get(_norm(style or ""), ([], None)))
    if grade and re.search(r"/A[0-9e]", grade, re.I):
        disciplines = disciplines + ["aid"]

    prose = []
    for h in soup.select("h2, h3"):
        label = h.get_text(" ", strip=True)
        if _norm(label) in ("resumen de la actividad",):
            continue
        body = []
        for sib in h.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            t = sib.get_text(" ", strip=True)
            if t:
                body.append(t)
        if body:
            prose.append(f"{label}: {' '.join(body)}")
    for key in ("duracion", "desnivel"):
        if props.get(key):
            prose.append(f"{key}: {props[key]}")
    for img in soup.select("img[src]"):
        src = img["src"]
        if re.search(r"croquis|rese|topo", src, re.I):
            prose.append(f"topo: {src}")          # URL only — never download
    for a in soup.select('a[href*="wikiloc.com"]'):
        prose.append(f"gps_track: {a['href']}")

    route = schema.route(
        source_id=item["url"].rsplit("/", 1)[-1], name=name,
        grade_value=grade or None,
        # The author mixes Spanish Roman and French freely ("V (un paso 6a+)")
        # — stored exactly as written, with no system claimed.
        grade_system=None,
        length_m=_int(props.get("longitud")),
        pitches=_int(props.get("no largos") or props.get("n largos")),
        stars=None, bolts_count=None, protection=protection,
        disciplines=disciplines, fa=None, url=item["url"],
        description="\n".join(prose))

    crag = schema.crag(
        SOURCE_ID, _norm(item["crag"]).replace(" ", "-"), item["crag"],
        lat=item["lat"], lon=item["lon"], url=item["url"], country="ES",
        region=item.get("region"), rock_type=None, aspect=None,
        description=f"Reseña por Antonio García-Saúco ('Pels'), panoramicas360.net",
        routes=[route])
    return {"crags": [crag], "next": []}

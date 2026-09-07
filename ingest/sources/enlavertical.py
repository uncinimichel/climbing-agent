"""enlavertical.com — the País Valencià community guide, found by the
2026-09-05/06 Costa Blanca research: 107 escuelas / 325 sectors / 3,830 routes
region-wide, ~30 escuelas and ~500-600 routes inside the Costa Blanca bbox,
25 of them on Puig Campana. Its unique value is the per-pitch Spanish reseña
plus equipment/descent/gear notes that UKC and theCrag do not carry.

LICENCE CAVEAT — the site has NO terms page, no aviso legal and no licence
statement anywhere (/pages/aviso_legal and /pages/condiciones both 404).
Content is user-contributed under no declared rights. robots.txt permits the
`view` pages this adapter uses, so crawling into the private store is fine, but
NOTHING from here may reach the public site before contacto@enlavertical.com
says yes. Every crag and route therefore keeps its contributor credit
("Reseñado por") so that ask can name the people it is really addressed to.

Robots disallows a long list of helper endpoints (/escuelas/sectoresjson,
/escuelas/gradosviassector, /*/listado*, /sectors/listadoxml, /users/*) — this
adapter touches none of them; everything needed is in the `view` HTML.

Encoding: the site declares iso-8859-1 but its database holds a mix — some
strings are latin-1, others are UTF-8 bytes stored as latin-1 ("clÃ¡sica").
_fix() repairs the second kind and leaves the first alone, per extracted
string, because a whole-page guess gets one of the two wrong either way.

Geography: sectors are the unit — each sector page embeds its own lat_cent /
lon_cent, its own approach and its own rock type, so a sector is an independent
place with a full record (no inheritance) and the escuela is the grouping
header, carried as `region` and as access context.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "enlavertical"
NEEDS_BROWSER = False
DELAY_S = 1.5

BASE = "https://www.enlavertical.com"
SPAIN = f"{BASE}/pais/view/73"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("iso-8859-1")  # declared charset; _fix repairs the rest
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _fix(s: str) -> str:
    """Repair UTF-8 bytes that were stored as latin-1 ("clÃ¡sica" -> "clásica").
    Leaves genuine latin-1 ("Espolón") untouched, because that round-trip fails."""
    if "Ã" in s or "Â" in s:
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def _text(el) -> str:
    return _fix(el.get_text(" ", strip=True)) if el else ""


_COORD_RE = re.compile(r"var\s+lat_cent\s*=\s*(-?[\d.]+)\s*;\s*var\s+lon_cent\s*=\s*(-?[\d.]+)")
_ASPECT = {"norte": "N", "sur": "S", "este": "E", "oeste": "W",
           "noreste": "NE", "noroeste": "NW", "nordeste": "NE",
           "sudeste": "SE", "sureste": "SE", "sudoeste": "SW", "suroeste": "SW"}
_ROCK = {"caliza": "limestone", "granito": "granite", "conglomerado": "conglomerate",
         "arenisca": "sandstone", "cuarcita": "quartzite", "esquisto": "schist",
         "gneis": "gneiss", "basalto": "basalt", "pizarra": "slate"}
_STYLE = {"clasica": ["trad"], "deportiva": ["sport"], "mixta": ["trad", "sport"],
          "artificial": ["aid"], "psicobloc": ["deepwatersolo"]}


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c))


def _coords(html: str) -> tuple[float | None, float | None]:
    m = _COORD_RE.search(html)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def _escuela_items(html: str, region: str | None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select('a[href*="/escuelas/view/"]'):
        m = re.search(r"/escuelas/view/(\d+)", a["href"])
        name = _text(a)
        if not m or not name or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        items.append({"kind": "escuela", "id": m.group(1), "name": name,
                      "region": region, "url": f"{BASE}/escuelas/view/{m.group(1)}"})
    return items


# The site names the autonomous communities in their own languages ("Pais
# Valencià", "Catalunya", "Euskadi") while Nominatim answers in Castilian
# ("Comunidad Valenciana"), so a string match on the name alone misses. The ISO
# 3166-2 code Nominatim also returns is the stable join key.
_ISO_ALIASES = {
    "ES-VC": {"pais valencia", "comunidad valenciana", "comunitat valenciana"},
    "ES-CT": {"catalunya", "cataluna"},
    "ES-PV": {"euskadi", "pais vasco"},
    "ES-IB": {"illes balears", "islas baleares", "baleares"},
    "ES-AN": {"andalucia"}, "ES-GA": {"galicia"}, "ES-AR": {"aragon"},
    "ES-CN": {"canarias"}, "ES-CB": {"cantabria"},
    "ES-CL": {"castilla y leon"}, "ES-CM": {"castilla-la mancha", "castilla la mancha"},
    "ES-EX": {"extremadura"}, "ES-MD": {"madrid", "comunidad de madrid"},
    "ES-MC": {"murcia", "region de murcia"}, "ES-NC": {"navarra"},
    "ES-RI": {"la rioja", "rioja"}, "ES-AS": {"asturias"},
}


def _province_id(bbox: geo.Bbox) -> tuple[str | None, str | None]:
    """Nominatim region -> the id in the site's own province <select>."""
    lat, lon = geo.center(bbox)
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=5"
        "&accept-language=es",
        headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            addr = json.load(resp).get("address") or {}
    except (TimeoutError, OSError, ValueError):
        return None, None
    want = _norm(addr.get("state") or addr.get("region") or "")
    aliases = _ISO_ALIASES.get(addr.get("ISO3166-2-lvl4") or "", set()) | ({want} if want else set())
    if not aliases:
        return None, None
    soup = BeautifulSoup(_get(SPAIN), "html.parser")
    sel = soup.select_one("#selectProvincias") or soup.select_one('select[name="data[provincias]"]')
    for opt in (sel.select("option") if sel else []):
        label = _text(opt)
        if not opt.get("value") or not label:
            continue
        n = _norm(label)
        if n in aliases or any(n == a or n in a or a in n for a in aliases):
            return opt["value"], label
    return None, None


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    if root:
        url = root if root.startswith("http") else BASE + root
        if "/escuelas/view/" in url:
            return [{"kind": "escuela", "id": url.rsplit("/", 1)[-1], "name": url,
                     "region": None, "url": url}]
        return _escuela_items(_get(url), None)

    pid, label = _province_id(bbox)
    if not pid:
        raise RuntimeError("could not resolve an enlavertical province for this bbox — "
                           "pass --root https://www.enlavertical.com/provincias/view/<id>")
    return _escuela_items(_get(f"{BASE}/provincias/view/{pid}"), label)


def fetch(item: dict, session=None) -> str:
    return _get(item["url"])


def _venue_context(soup: BeautifulSoup) -> str:
    """The escuela's own access prose, carried onto each sector so every sector
    record stands alone (sectors are independent places — no inheritance)."""
    out = []
    for h in soup.select("h2, h3, strong, b"):
        label = _text(h)
        if not label:
            continue
        low = _norm(label)
        if any(k in low for k in ("como llegar", "aproximacion", "agua", "donde dormir",
                                  "pueblo mas cercano", "epoca", "restriccion")):
            nxt = h.find_next(["p", "div", "td"])
            body = _text(nxt)
            if body:
                out.append(f"{label}: {body}")
    return "\n".join(out)


def parse(item: dict, html: str, bbox: geo.Bbox) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    lat, lon = _coords(html)

    if item["kind"] == "escuela":
        # Prune the whole venue on its own point; its sectors sit within a few
        # hundred metres and are re-checked on their own coordinates below.
        if lat is not None and not geo.contains(bbox, lat, lon):
            return {"crags": [], "next": []}
        venue = _text(soup.h1).split("/")[-1].strip() or item.get("name")
        context = _venue_context(soup)
        nxt, seen = [], set()
        for a in soup.select('a[href*="/sectors/view/"]'):
            m = re.search(r"/sectors/view/(\d+)", a["href"])
            name = _text(a)
            if not m or not name or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            nxt.append({"kind": "sector", "id": m.group(1), "name": name,
                        "venue": venue, "region": item.get("region"),
                        "context": context,
                        "url": f"{BASE}/sectors/view/{m.group(1)}"})
        return {"crags": [], "next": nxt}

    # --- sector: the independent place ---------------------------------------
    if not geo.contains(bbox, lat, lon):
        return {"crags": [], "next": []}

    body = _fix(soup.get_text(" ", strip=True))
    routes, aspects = [], []
    for tr in soup.select("tr"):
        a = tr.select_one('a[href*="/vias/view/"]')
        if not a:
            continue
        m = re.search(r"/vias/view/(\d+)", a["href"])
        if not m:
            continue
        cells = [_text(c) for c in tr.select("td")]
        if len(cells) < 5:
            continue
        name, grade, style, orient, pitches = cells[0], cells[1], cells[2], cells[3], cells[4]
        if orient:
            aspects.append(_ASPECT.get(_norm(orient), None))
        disciplines = list(_STYLE.get(_norm(style), []))
        if grade and re.search(r"/A[0-9e]", grade, re.I):
            disciplines.append("aid")
        routes.append(schema.route(
            source_id=m.group(1), name=name,
            grade_value=grade or None,
            grade_system="spanish_hybrid" if grade else None,
            length_m=None,                      # stated on the vía page, not the table
            pitches=int(pitches) if pitches.isdigit() else None,
            stars=None, bolts_count=None, protection=None,
            disciplines=disciplines, fa=None,
            url=f"{BASE}/vias/view/{m.group(1)}",
            description=(f"Orientación: {orient}" if orient else ""),
        ))

    # Aspect is a crag attribute (2026-09-05 ruling): take it only when every
    # route on the sector agrees, otherwise leave it unstated.
    aspect = aspects[0] if aspects and len(set(aspects)) == 1 and aspects[0] else None
    rock = next((code for es, code in _ROCK.items() if es in _norm(body)), None)

    name = _text(soup.h1).split("/")[-1].strip() or item.get("name") or "?"
    venue = item.get("venue")
    crag = schema.crag(
        SOURCE_ID, item["id"],
        f"{venue} — {name}" if venue and _norm(venue) != _norm(name) else name,
        lat=lat, lon=lon, url=item["url"], country="ES",
        region=item.get("region"), rock_type=rock, aspect=aspect,
        description="\n".join(x for x in (item.get("context"), _sector_prose(soup)) if x),
        routes=routes)
    return {"crags": [crag], "next": []}


def _sector_prose(soup: BeautifulSoup) -> str:
    out = []
    for h in soup.select("h2, h3, strong, b"):
        label = _text(h)
        low = _norm(label)
        if any(k in low for k in ("aproximacion", "tiempo", "tipo de roca",
                                  "descripcion", "resenado por")):
            nxt = h.find_next(["p", "div", "td"])
            body = _text(nxt)
            if body:
                out.append(f"{label}: {body}")
    return "\n".join(out)

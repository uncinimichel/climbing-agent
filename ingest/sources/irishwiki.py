"""Irish Climbing Wiki (wiki.climbing.ie) — the volunteer-run Irish route
database and de-facto new-routes register for the Mournes (found by the
2026-08-13 deep research: all 30 Co. Down crags with full route lists, e.g.
Lower Cove ~99 routes). MediaWiki 1.35 with an OPEN api.php; no robots.txt
(404), no license/TOS pages. Scraped politely over PLAIN HTTP — port 443
refuses connections (verified live); raw stays in the private store as with
every source. Courtesy contact: admin@climbing.ie (flagged to Michel).

Geography: wiki pages carry no machine coordinates, so the bbox is satisfied
by COUNTY MEMBERSHIP — bbox center -> Nominatim county ("County Down") ->
the matching county section of the Irish_Climbing_Wiki index page -> that
section's crag links (same coarse-membership tradeoff as climbook, documented
there). Crags get lat/lon null — never guessed.

Route extraction is mechanical best-effort over the RENDERED page (API
action=parse: stable HTML fragment): a route is a <b>Name</b> whose following
text opens with grade/length tokens ("30m HVS 5a"); UK adjectival grades get
system uk_adjectival_tech, anything else stays verbatim with system null.
Bold section headings (Approach, Descent…) carry no grade and are skipped.
Prose blocks are kept verbatim as route descriptions — the LLM phase's food.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "irishwiki"
NEEDS_BROWSER = False
DELAY_S = 2.0  # small volunteer server — extra polite

API = "http://wiki.climbing.ie/api.php"
INDEX_PAGE = "Irish_Climbing_Wiki"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project; contact uncini.michel@gmail.com)"

# UK/Irish adjectival grade at the start of a route block. Ordered longest-first.
GRADE_RE = re.compile(
    r"\b(E\d+(?:/\d+)?(?: [3-7][abc][+]?)?|XS|HVS(?: [3-7][abc][+]?)?|"
    r"VS(?: [3-7][abc][+]?)?|HS(?: [3-7][abc][+]?)?|MS|VD(?:iff)?|"
    r"Hard Severe|Mild Severe|Severe|Diff|Moderate|"
    r"S(?: [3-7][abc][+]?)?|D\b|M\b|f?[3-8][abc]?\+?|A\d)\b")
LEN_RE = re.compile(r"\b(\d{1,3})\s*m\b")


def _api(params: dict) -> dict:
    q = dict(params, format="json")
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                 headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _county_from_bbox(bbox: geo.Bbox) -> str:
    lat, lon = geo.center(bbox)
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=8"
        "&accept-language=en",
        headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        a = json.load(resp).get("address") or {}
    county = a.get("county") or a.get("historic") or a.get("state_district")
    if not county:
        raise RuntimeError("could not resolve a county for this bbox — pass --root '<index section name>'")
    return county


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    county = root or _county_from_bbox(bbox)          # e.g. "County Down"
    short = county.replace("County", "").strip()      # index sections say "Co. Down"
    sections = _api({"action": "parse", "page": INDEX_PAGE, "prop": "sections"})
    # exact "Co. X" match — a loose substring match sent "Down" to the
    # "Donegal PDF guidebook DOWNloads" section (0 links), found live 2026-08-13
    want = re.compile(rf"^co\.?\s*{re.escape(short)}\s*$", re.I)
    sec = next((s for s in sections["parse"]["sections"] if want.match(s["line"].strip())), None)
    if not sec:
        raise RuntimeError(f"no index section matching {county!r} on {INDEX_PAGE}")
    links = _api({"action": "parse", "page": INDEX_PAGE, "prop": "links",
                  "section": sec["index"]})
    items = []
    for l in links["parse"]["links"]:
        title = l.get("*") or ""
        if l.get("ns") != 0 or not title or "exists" not in l:
            continue
        items.append({"kind": "crag", "id": title, "name": title.replace("_", " "),
                      "region": short, "country": "Northern Ireland" if short in
                      ("Down", "Antrim", "Derry", "Londonderry", "Armagh", "Tyrone", "Fermanagh")
                      else "Ireland",
                      "url": f"http://wiki.climbing.ie/index.php?title={urllib.parse.quote(title)}"})
    return items


def fetch(item: dict, session=None) -> dict:
    return _api({"action": "parse", "page": item["id"], "prop": "text"})


def parse(item: dict, payload: dict, bbox: geo.Bbox) -> dict:
    html = ((payload.get("parse") or {}).get("text") or {}).get("*") or ""
    soup = BeautifulSoup(html, "html.parser")
    # walk bold elements; a bold is a route when its following text starts with
    # grade/length tokens within the first ~100 chars
    routes = []
    bolds = soup.find_all("b")
    intro = ""
    if bolds:
        first_block = _text_between(soup, None, bolds[0])
        intro = first_block[:700]
    for i, b in enumerate(bolds):
        raw_name = b.get_text(" ", strip=True)
        if not raw_name or len(raw_name) > 80:
            continue
        stars = raw_name.count("*")
        name = raw_name.replace("*", "").strip(" .")
        block = _text_between(soup, b, bolds[i + 1] if i + 1 < len(bolds) else None)
        head = block[:110]
        gm, lm = GRADE_RE.search(head), LEN_RE.search(head)
        if not gm and not lm:
            continue  # a heading (Approach/Descent), not a route
        grade = gm.group(1).strip() if gm else None
        system = "uk_adjectival_tech" if grade and re.match(r"^(E\d|XS|HVS|VS|HS|MS|VD|S|D|M|Hard|Mild|Severe|Diff|Moderate)", grade) else None
        routes.append(schema.route(
            f"{item['id']}#{len(routes)+1}", name,
            grade_value=grade, grade_system=system,
            length_m=int(lm.group(1)) if lm else None,
            stars=stars or None,
            disciplines=["trad"],   # the wiki is the trad register; bouldering lives on tor pages with font grades kept verbatim
            url=item["url"],
            description=block[:800],
        ))
    c = schema.crag(
        SOURCE_ID, item["id"], item["name"],
        lat=None, lon=None,  # wiki pages carry no machine coords — never guessed
        url=item["url"], country=item.get("country"), region=item.get("region"),
        description=intro,
        routes=routes,
    )
    return {"crags": [c] if routes else [], "next": []}


def _text_between(soup, start, end) -> str:
    """Rendered text strictly between two nodes (document order)."""
    out = []
    started = start is None
    for el in soup.descendants:
        if el is start:
            started = True
            continue
        if el is end:
            break
        if started and isinstance(el, str):
            parent = el.parent.name if el.parent else ""
            if parent not in ("script", "style"):
                out.append(el)
    return re.sub(r"\s+", " ", "".join(out)).strip()

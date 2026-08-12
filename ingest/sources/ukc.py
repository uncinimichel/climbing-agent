"""UKClimbing source — best UK/Ireland coverage, real pitch-by-pitch prose.

Discovery (found 2026-08-11 by reading UKC's own map frontend,
assets/logbooks/map/crag_search.js): their site API
`api.ukclimbing.com/site/logbook/v1/crag_search/?location=<lat>,<lng>&
distance=<km>` returns every crag around a point — id, slug, name, osy/osx
(lat/lon), nroutes, county/country, rocktype. Cloudflare 403s plain HTTP but
clears a real browser NAVIGATION to the URL (fetch() from page JS dies on
CORS instead — navigation is the one path that works), so plan() rides the
same BrowserSession the crag pages use. Scraped with Michel's permission;
raw stays out of the public repo.

Crag pages themselves are parsed by the proven corpus/tools/ukc_client.py;
mapping harvested from the superseded PR #1 adapter.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "corpus" / "tools"))
import ukc_client as uc  # noqa: E402

from .. import geo, schema  # noqa: E402

SOURCE_ID = "ukc"
NEEDS_BROWSER = True
DELAY_S = 2.0

API = "https://api.ukclimbing.com/site/logbook/v1/crag_search/"
MAX_DISTANCE_KM = 100  # crag_search's practical ceiling; bigger boxes lose the edges

DISCIPLINE_MAP = {
    "trad": "trad", "sport": "sport", "alpine": "alpine",
    "winter": "mixed", "ice": "ice", "aid": "aid", "scramble": "scrambling",
    "top rope": "tr", "solo": "trad",
    # live labels are "Bouldering"/"Boulder Circuit", not "Boulder" (the
    # harvested map's guess — caught 2026-08-12 when 533 Fair Head boulder
    # problems mapped to nothing); keep "boulder" too, belt and braces
    "boulder": "bouldering", "bouldering": "bouldering",
    "boulder circuit": "bouldering",
}


def plan(bbox: geo.Bbox, session=None, root=None) -> list[dict]:
    lat, lon = geo.center(bbox)
    km = min(max(1, round(geo.covering_radius_m(bbox) / 1000) + 1), MAX_DISTANCE_KM)
    html = session.fetch(f"{API}?location={lat},{lon}&distance={km}", wait_ms=2000)
    data = _json_from_navigation(html)
    if not data.get("success"):
        raise RuntimeError(f"ukc crag_search failed: {str(data)[:300]}")
    items = []
    for c in data.get("results") or []:
        if not geo.contains(bbox, c.get("osy"), c.get("osx")):
            continue  # circle covering the box; trim the corners
        items.append({"kind": "crag", "id": c["slug"], "name": _text(c["name"]),
                      "lat": c.get("osy"), "lon": c.get("osx"),
                      "nroutes": c.get("nroutes"),
                      "country": _text(c.get("country_name")),
                      "region": _text(c.get("county_name")),
                      "rock_type": _rock(_text(c.get("rocktype_name"))),
                      "aspect": _text(c.get("aspect_name")) or None})
    return items


# UKC rocktype_name -> corpus taxonomy rock_type code. Lowercase + strip any
# "(hard)/(soft)" qualifier covers most; the rest are aliases. Unmappable
# values (Artificial, UNKNOWN, …) become None — an enum field never carries a
# raw source string (taxonomy IS the schema, Michel 2026-08-12).
ROCK_ALIASES = {"grit": "gritstone", "mica schist": "schist",
                "volcanic tuff": "volcanic", "tuff": "volcanic"}


def _rock(v):
    if not v:
        return None
    s = re.sub(r"\s*\(.*\)$", "", v.strip().lower())
    s = ROCK_ALIASES.get(s, s)
    return s if s in schema.ROCK_TYPES else None


def _text(v):
    """crag_search strings arrive double-HTML-encoded ('Marconi&amp;#039;s
    Cove', seen live 2026-08-11) — unescape twice."""
    import html
    return html.unescape(html.unescape(v)) if isinstance(v, str) else v


def _json_from_navigation(html: str) -> dict:
    """Navigating a browser to a JSON endpoint wraps the body in Chromium's
    <pre> viewer — unwrap it. A 'Just a moment…' title means Cloudflare kept
    the challenge up; surface that instead of a JSON parse error."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", html, re.S)
    text = m.group(1) if m else re.sub(r"<[^>]+>", "", html)
    text = text.strip()
    if not text.startswith("{"):
        if "moment" in html.lower() or "cloudflare" in html.lower():
            raise RuntimeError("ukc crag_search blocked by Cloudflare challenge")
        raise RuntimeError(f"ukc crag_search returned non-JSON: {text[:200]!r}")
    return json.loads(text)


def fetch(item: dict, session=None) -> str:
    # store the client's parsed dict as the payload: it IS the page's own
    # table_data, so it's faithful; the HTML itself is megabytes of ads
    return uc.fetch_crag(session, f"https://www.ukclimbing.com/logbook/crags/{item['id']}/")


def parse(item: dict, payload: dict, bbox: geo.Bbox) -> dict:
    routes = [_route(r) for r in payload.get("routes") or []]
    c = schema.crag(
        SOURCE_ID, item["id"], item["name"],
        lat=item.get("lat"), lon=item.get("lon"), url=payload.get("url"),
        country=item.get("country"), region=item.get("region"),
        rock_type=item.get("rock_type"), aspect=item.get("aspect"),
        routes=routes,
    )
    return {"crags": [c] if routes else [], "next": []}


def _route(r: dict) -> dict:
    adj, tech = r.get("adjectival_grade"), r.get("tech_grade")
    value = " ".join(x for x in (adj, tech) if x) or None
    pitches = int(r["pitches"]) if r.get("pitches") else None
    stars = int(r["stars"]) if r.get("stars") not in (None, "") else None
    disciplines = []
    d = DISCIPLINE_MAP.get((r.get("discipline_label") or "").strip().lower())
    if d:
        disciplines.append(d)
    return schema.route(
        r["id"], r["name"],
        grade_value=value, grade_system="uk_adjectival_tech" if adj else "ukc_other",
        length_m=r.get("length_m"), pitches=pitches, stars=stars,
        disciplines=disciplines, url=r.get("url"),
        description=r.get("description") or "",
    )

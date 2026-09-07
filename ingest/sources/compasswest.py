"""Compass West (compasswest.co.uk) — Rowland Edwards' school, in Finestrat
since 1986; the only substantial ENGLISH-language topo set for the Costa
Blanca. 14 crag blocks on /topos/ plus a few article PDFs.

RIGHTS: the site has no terms, no privacy page and no copyright notice, and the
PDFs carry no licence text. "Free Topos" implies distribution intent, but this
is a named author's guidebook work — crawl to the private store, and email
info@compasswest.co.uk for permission and credit before anything reaches the
public site. /shop/ and /product/* (the paid guides) are never fetched.

WHAT THIS ADAPTER CAN AND CANNOT DO. The route data on this site lives inside
topo IMAGES, not in the PDF text layer: new-campana.pdf extracts 19.8k
characters of excellent access and history prose and not one grade token
(verified live 2026-09-07). So this adapter emits crag records with the
verbatim PDF text as `description` and the topo URLs alongside, and extracts
routes only where a PDF genuinely carries a text route list. Crags with zero
routes here are the honest answer, not a parser bug — the route lines need the
LLM/vision path over the topo images, which is a separate phase.

Geography: the site states no coordinates at all (only Puig Campana has an
in-PDF Garmin reference), so CRAG_TABLE below is hand-entered from the mapping
document and IS the bbox filter. Hand-entered coordinates are marked as such so
nothing downstream mistakes them for source-stated facts.
"""
from __future__ import annotations

import io
import re
import time
import urllib.request

from bs4 import BeautifulSoup

from .. import geo, schema

SOURCE_ID = "compasswest"
NEEDS_BROWSER = False
DELAY_S = 2.0  # the site asks for a 2s crawl delay

BASE = "http://www.compasswest.co.uk"
TOPOS = f"{BASE}/topos/"
UA = "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent; polite, personal project)"

# Hand-entered from ingest/research/costa-blanca/mappings/compasswest.md — the
# site publishes no coordinates. Approximate crag centres, good to ~500 m:
# enough to place a crag in or out of a bbox, never precise enough to navigate.
CRAG_TABLE = {
    "puig campana": (38.5896, -0.2170),
    "bolulla": (38.6797, -0.1150),
    "dos hermanos": (38.6350, -0.1822),
    "lomo de leon": (38.6470, -0.2360),
    "haunted walls": (38.6560, -0.2270),
    "penya roc": (38.6350, -0.1822),
    "toix sea cliffs": (38.6300, 0.0700),
    "guadalest upper & lower buttress": (38.6790, -0.1980),
    "aguja del pilar": (38.6560, -0.2300),
    "pleasure domes": (38.6600, -0.2200),
    "olta realet menor – n face catsellets": (38.6275, -0.1563),
    "sella": (38.6300, -0.2600),
}

_GRADE_RE = re.compile(
    r"\b(E[1-9]\s?[1-7][abc]|E[1-9]|XS|HVS|MVS|VS|HS|VD|MVD|S\b|"
    r"[4-9][abc]\+?|[4-9]\+)\b")


def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _fix_url(href: str) -> str:
    # the site emits some hrefs with a doubled slash before wp-content
    return re.sub(r"(?<!:)//wp-content", "/wp-content", href)


def plan(bbox: geo.Bbox, session=None, root: str | None = None) -> list[dict]:
    html = _get_bytes(root or TOPOS).decode("utf-8", "replace")
    soup = BeautifulSoup(html, "html.parser")

    items = []
    for h in soup.select("h1, h2, h3, h4"):
        name = h.get_text(" ", strip=True)
        key = _norm(name)
        if key not in CRAG_TABLE:
            continue
        lat, lon = CRAG_TABLE[key]
        if not geo.contains(bbox, lat, lon):
            continue
        # the PDFs for this crag: anchors until the next heading
        pdfs = []
        for sib in h.find_all_next():
            if sib.name in ("h1", "h2", "h3", "h4"):
                break
            if sib.name == "a" and (sib.get("href") or "").lower().endswith(".pdf"):
                pdfs.append(_fix_url(sib["href"]))
        if not pdfs:
            continue
        items.append({"kind": "crag", "id": re.sub(r"[^a-z0-9]+", "-", key).strip("-"),
                      "name": name, "url": TOPOS, "lat": lat, "lon": lon,
                      "pdfs": sorted(dict.fromkeys(pdfs))})
    return items


def fetch(item: dict, session=None) -> dict:
    """All of a crag's PDFs in one unit of work, so the crag record is complete
    when it is emitted (the runner emits one crag per fetch)."""
    from pypdf import PdfReader
    out = {}
    for url in item["pdfs"]:
        try:
            raw = _get_bytes(url)
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:                        # a scanned or broken PDF
            text = ""
            out[url] = {"text": "", "error": f"{type(e).__name__}: {e}"}
            continue
        out[url] = {"text": text, "pages": len(reader.pages)}
        time.sleep(DELAY_S)
    return out


def parse(item: dict, payload: dict, bbox: geo.Bbox) -> dict:
    if not geo.contains(bbox, item["lat"], item["lon"]):
        return {"crags": [], "next": []}

    prose = []
    for url, doc in payload.items():
        text = (doc or {}).get("text") or ""
        prose.append(f"[{url}]\n{text}" if text else f"[{url}] (no text layer — topo images only)")

    # Routes are deliberately NOT extracted. Tried and rejected 2026-09-07: a
    # grade-token regex over this text layer returns pitch fragments and first-
    # ascent prose ("1. 40m 1V.", "First complete ascent. R. Edwards") rather
    # than routes, because the route lists live in the topo IMAGES and only the
    # surrounding narrative is in the text layer. Emitting those would put
    # fiction in the record, so this source contributes crag metadata plus
    # verbatim prose, and its routes wait for the LLM/vision phase over the
    # topo images — which is exactly what the stored PDF text and URLs enable.
    description = ("Coordinates hand-entered from the Compass West mapping doc — "
                   "the site states none. Route lists are in the topo images, "
                   "not this text.\n" + "\n\n".join(prose))
    crag = schema.crag(
        SOURCE_ID, item["id"], item["name"],
        lat=item["lat"], lon=item["lon"], url=item["url"], country="ES",
        region="Alicante", rock_type="limestone", aspect=None,
        description=description, routes=[])
    return {"crags": [crag], "next": []}

"""UKClimbing (UKC) crag scraper — no public API (confirmed in ingestion-plan.md);
pages fetched via headless browser (browser_fetch.py) since Cloudflare actively
challenges plain HTTP clients. Scraping is done with Michel's direct permission
from UKC — see the decision log in knowledge/roadmap/ingestion-plan.md.

Route data comes from two places on a crag page, cross-referenced by row id
(verified live against real crag pages 2026-07-06 — not guessed):
  1. An embedded `table_data = [...]` JS array — the structured fields UKC's
     own table widget uses: id, name, slug, buttress_id, techgrade, stars,
     height (m), pitches (!), desc (often pitch-by-pitch prose).
  2. The rendered <tr> markup — the adjectival grade text ("VS", "E1"...) and
     the discipline label (the type icon's `title` attribute, e.g. "Trad")
     are NOT in table_data; UKC's internal numeric `grade`/`gradetype` codes
     aren't published anywhere, so these are read straight from the HTML
     rather than guessed at from a reverse-engineered lookup table.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from browser_fetch import BrowserSession


def _extract_table_data(html: str) -> list[dict]:
    """`table_data = [ ... ];` — a balanced-bracket scan (not a naive regex)
    because route descriptions contain literal `[`/`]`/quotes."""
    start = html.index("table_data = [") + len("table_data = ")
    depth = 0
    in_str = False
    esc = False
    quote = ""
    i = start
    while i < len(html):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        else:
            if c in "\"'":
                in_str = True
                quote = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
        i += 1
    return json.loads(html[start:i])


def _extract_row_display(html: str) -> dict[int, dict]:
    """Per-route id -> {adjectival grade text, discipline label}."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[int, dict] = {}
    for tr in soup.select("tr[id]"):
        try:
            row_id = int(tr["id"])
        except (KeyError, ValueError):
            continue
        grade_cell = tr.select_one("td.datatable_column_grade span")
        adjectival = grade_cell.contents[0].strip() if grade_cell and grade_cell.contents else None
        type_icon = tr.select_one("td.datatable_column_type i")
        discipline = type_icon.get("title") if type_icon else None
        out[row_id] = {"adjectival": adjectival, "discipline": discipline}
    return out


def _extract_sectors(html: str) -> dict[int, str]:
    return {
        int(bid): name.strip()
        for bid, name in re.findall(r'id="buttress_(\d+)">.*?<h5>([^<]*)</h5>', html, re.S)
    }


def fetch_crag(session: BrowserSession, url: str) -> dict:
    """One crag page -> {url, routes: [...]}. Each route dict is mechanical
    fields only (no LLM inference) — ready for the multi-pitch trad/alpine
    filter and the route-schema mapping."""
    html = session.fetch(url)
    table_data = _extract_table_data(html)
    display = _extract_row_display(html)
    sectors = _extract_sectors(html)

    routes = []
    for r in table_data:
        d = display.get(r["id"], {})
        routes.append(
            {
                "id": r["id"],
                "name": r["name"],
                "url": url.rstrip("/") + "/" + r["slug"],
                "sector_id": r["buttress_id"],
                "sector_name": sectors.get(r["buttress_id"]),
                "adjectival_grade": d.get("adjectival"),
                "tech_grade": r.get("techgrade"),
                "discipline_label": d.get("discipline"),
                "stars": r.get("stars"),
                "length_m": r.get("height") or None,
                "pitches": r.get("pitches") or None,
                "description": r.get("desc") or None,
            }
        )
    return {"url": url, "routes": routes}


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.ukclimbing.com/logbook/crags/fair_head-17029/"
    with BrowserSession() as session:
        crag = fetch_crag(session, url)
    print(f"{len(crag['routes'])} routes at {url}")
    for r in crag["routes"][:5]:
        print(" ", r)

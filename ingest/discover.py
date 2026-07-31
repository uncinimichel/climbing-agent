#!/usr/bin/env python3
"""Region discovery — draw a bbox, find climbing in it, land drafts.

The "Discover more" engine behind the Studio map: given a drawn/selected region
it reverse-geocodes the box for a human region name + admin breadcrumb, then runs
discovery across sources and saves whatever it finds as `status: draft` in the
S3-keyed holding pen (deduped by the unique key). Local + synchronous here; the
Studio runs it on a background thread (AWS/Lambda later — decision deferred).

Two engines, both worldwide-capable:
  • OpenBeta — seeded by the geocoded region name (rich where it has data ≈ US).
  • SerpAPI web search — Google for "<region> trad multi-pitch climbing", then an
    LLM reads the results and extracts candidate crags/routes. This is the only
    engine that finds lines in *no* database, and it works anywhere. GDPR: we keep
    place + route, never the person (CONVENTIONS.md).

Dependency-free (stdlib urllib); the LLM extract goes through the `claude` CLI
(same reason as ingest/tag.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "ingest" / "sources"))
sys.path.insert(0, str(ROOT / "corpus" / "tools"))
from drafts import DraftStore  # noqa: E402
from store import Store, slug  # noqa: E402

UA = "climbing-agent-discover/0.1 (+https://github.com/uncinimichel/climbing-agent)"


def reverse_geocode(lat: float, lon: float) -> dict:
    """bbox centre → admin place (country/region). This is the *administrative*
    breadcrumb (Nominatim/OSM) — 'Spain · Huesca' — not climbing crag names."""
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    a = d.get("address", {})
    country = a.get("country")
    state = a.get("state") or a.get("region")
    county = a.get("county") or a.get("state_district")
    town = a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
    # search on the most LOCAL name (a valley/town beats a whole state) but keep
    # the fuller admin chain for the breadcrumb
    name = town or county or state or d.get("name") or "this region"
    return {"country": country, "region": state, "name": name,
            "breadcrumb": [x for x in (country, state, county) if x],
            "display": d.get("display_name")}


def serp_search(query: str, key: str, num: int = 10, gl: str | None = None) -> list[dict]:
    p = {"engine": "google", "q": query, "api_key": key, "num": num}
    if gl:
        p["gl"] = gl
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(p)
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.load(r)
    return [{"title": o.get("title"), "link": o.get("link"), "snippet": o.get("snippet")}
            for o in d.get("organic_results", [])]


_EXTRACT = """You are finding trad / alpine MULTI-PITCH climbing in a region from web search results.

Region: {region}

From ONLY the results below, list the distinct climbing CRAGS/areas and any named ROUTES you
can identify there. Prefer trad, alpine and big-wall multi-pitch; IGNORE sport-only crags,
bouldering, gyms, shops and guide companies. Never invent — only what the text supports.

Output ONLY a JSON array, each object EXACTLY:
{{"crag": "<crag/area name>", "routes": [{{"name": "<route>", "grade": "<grade or null>"}}],
  "source_url": "<the best url>", "confidence": "high|medium|low"}}
If nothing climbing-relevant is present, output [].

Results:
{results}
"""


def extract_crags(region: str, results: list[dict]) -> list[dict]:
    if not results:
        return []
    block = "\n".join(f"- {r['title']}\n  {r['link']}\n  {r.get('snippet') or ''}" for r in results)
    # Sonnet, not Haiku: extracting crag/route names from terse, messy search
    # snippets is a judgement task Haiku is unreliable at (it returns [] on thin
    # text). Discovery is per-region (few calls), so the cost is fine.
    proc = subprocess.run(
        ["claude", "-p", _EXTRACT.format(region=region, results=block),
         "--model", "sonnet", "--output-format", "json"],
        capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    payload = json.loads(proc.stdout)
    text = (payload.get("result") or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.startswith("json") else text
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _candidate_to_routes(geo: dict, crag: dict) -> list[dict]:
    """One extracted crag → draft route dicts for the holding pen. Coordinates
    are the region centroid (approximate — flagged for the curator to place)."""
    out = []
    cname = crag.get("crag") or "Unknown crag"
    for rt in crag.get("routes") or []:
        name = (rt.get("name") or "").strip()
        if not name:
            continue
        ext = f"{slug(cname)}:{slug(name)}"      # the unique key — dedups re-discovery
        out.append({
            "name": name,
            "original_grade": rt.get("grade") or None,
            "grade_system_code": None,
            "status": "draft", "tagged_by": "source",
            "needs_field_check": True,
            "curation_notes": f"web-discovered in {geo['name']} (confidence: {crag.get('confidence','?')}) — verify & place the pin",
            "tags": {"disciplines": ["trad", "multi-pitch"], "features": [], "character": []},
            "external_refs": [{"source_id": "serp-social", "external_id": ext,
                               "url": crag.get("source_url")}],
        })
    return out


def discover_candidates(bbox: list[float], on_progress=None, max_queries: int = 2) -> dict:
    """The read-only half: geocode → SerpAPI search → LLM-extract. Returns
    {region, center:[lat,lon], crags:[{crag, routes, source_url, confidence, lat, lon}]}.
    No persistence — the caller decides where drafts land (the Studio writes them
    into the curated record as drafts; the CLI uses the holding pen)."""
    s, w, n, e = bbox
    clat, clon = round((s + n) / 2, 5), round((w + e) / 2, 5)
    prog = (lambda m: on_progress(m)) if on_progress else (lambda m: None)

    geo = reverse_geocode(clat, clon)
    prog(f"region: {geo['display'] or geo['name']}")

    candidates: list[dict] = []
    key = os.environ.get("SERPAPI_KEY")
    if key:
        for q in [f'"{geo["name"]}" trad multi-pitch climbing routes',
                  f'{geo["name"]} classic multipitch trad climbing crag'][:max_queries]:
            prog(f"searching: {q}")
            try:
                found = extract_crags(geo["name"], serp_search(q, key))
                candidates += found
                prog(f"  found {len(found)} crag candidate(s)")
            except Exception as ex:  # one query failing must not kill the job
                prog(f"  ! query failed: {ex}")
    else:
        prog("no SERPAPI_KEY set — skipping web search")

    seen, uniq = set(), []
    for c in candidates:                      # dedup crags by slug (LLM repeats across queries)
        k = slug(c.get("crag") or "")
        if k and k not in seen:
            seen.add(k)
            c["lat"], c["lon"] = clat, clon    # approx: region centroid (curator places precisely)
            uniq.append(c)
    return {"region": geo, "center": [clat, clon], "crags": uniq}


def discover_region(bbox: list[float], on_progress=None, dry_run: bool = False,
                    max_queries: int = 2) -> dict:
    """CLI path: discover + land drafts in the S3 holding pen (deduped)."""
    got = discover_candidates(bbox, on_progress, max_queries)
    geo, prog = got["region"], (on_progress or (lambda m: None))
    store = Store()
    ds = DraftStore(store)
    existing = {tuple(x.get("external_id") for x in r.get("external_refs", []))
                for r in store.routes.values()}
    saved, skipped, crags, pins = 0, 0, [], []
    for c in got["crags"]:
        routes = _candidate_to_routes(geo, c)
        if not routes:
            continue
        crags.append(c.get("crag"))
        for route in routes:
            ext = route["external_refs"][0]["external_id"]
            if (ext,) in existing:                 # unique-key dedup — never re-add
                skipped += 1
                continue
            route["lat"], route["lon"] = c["lat"], c["lon"]   # approx: region centroid
            route["area_id"] = None
            route["id"] = abs(hash(ext)) % (10 ** 8)   # deterministic-ish holding-pen id
            if not dry_run:
                try:
                    ds.save(route, geo["breadcrumb"] + [c.get("crag") or "unknown"])
                    saved += 1
                except Exception as ex:
                    prog(f"  ! {route['name']}: {ex}")
            else:
                saved += 1
            pins.append({"name": route["name"], "grade": route.get("original_grade"),
                         "crag": c.get("crag"), "lat": route["lat"], "lon": route["lon"],
                         "status": "draft", "url": c.get("source_url"), "key": ext})

    prog(f"done · {len(crags)} crags, {saved} draft routes"
         + (f", {skipped} already known (deduped)" if skipped else ""))
    return {"region": geo, "crags": crags, "drafts": saved, "deduped": skipped,
            "pins": pins, "dry_run": dry_run}


if __name__ == "__main__":
    # quick manual test: a bbox in the Spanish Pyrenees (Bujaruelo / Ordesa)
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--bbox", default="42.60,-0.15,42.72,0.05", help="south,west,north,east")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    bbox = [float(x) for x in a.bbox.split(",")]
    out = discover_region(bbox, on_progress=lambda m: print(" ·", m), dry_run=a.dry_run)
    print(json.dumps({k: v for k, v in out.items() if k != "region"}, indent=2))
    print("region:", out["region"]["display"])

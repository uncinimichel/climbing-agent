"""Canonical-key storage — every crawl and curated output lands under the SAME
S3 record key scheme (Michel, 2026-08-12): <country>/<region>/<crag>/<route>.json,
always exactly 4 slug parts, slugs byte-identical to the record store's
(store.slug is imported, not copied). What can't honestly fill all 4 parts is
NOT keyed by guesswork — it goes to _flagged/ and the report, for Michel.

    python -m ingest keyed <run-id>

writes into the run dir:
    keyed/crawl/<source>/<country>/<region>/<crag>/_crag.json   crag meta+enrichment
    keyed/crawl/<source>/<country>/<region>/<crag>/<route>.json one file per route
    keyed/curated/<country>/<region>/<crag>/...                 same, from llm-curated/
    keyed/_flagged/<source>/<crag-slug>.json                    couldn't build a full key
    keyed/report.json                                           written/flagged/collisions

The `crawl/<source>/` and `curated/` prefixes are namespaces (like the record's
`_ingest/`); the 4-part canonical key after them never changes shape. Syncing
keyed/ to the S3 bucket is the separate explicit upload step.

Country/region resolution ladder (mechanical, in order):
  1. the source's own field — country normalized via geocoding-locale fix
     (Nominatim answers in page locale: climbook's "Italia" -> "Italy" via a
     reverse geocode in English, cached per ~10km cell)
  2. reverse geocode of the crag's coords (Nominatim, accept-language=en,
     zoom=5) — real coordinates, so mechanical, not guesswork
  3. FLAG — no coords and no stated region (nothing to derive from)
OpenBeta's region is a deep path ("Sardegna / Gallura / …") — the FIRST
segment is the admin region, the rest is sub-area detail (kept inside the
file, not in the key). Route-name slug collisions within a crag get a
"-<source_id>" suffix (key still 4 parts) and are reported.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "corpus" / "tools"))
from store import slug  # noqa: E402 — byte-identical keys with the record store

from .runstore import Run, _atomic_write

_geo_cache: dict[tuple, dict] = {}

# The record store's own country vocabulary (corpus/record/<country>/ dirs) is
# the anchor: it treats UK home nations as countries (northern-ireland/, not
# united-kingdom/) — a stated country already in this vocabulary is NEVER
# rewritten by geocoding (which would say "United Kingdom" and break parity
# with the existing record keys).
_RECORD_DIR = Path(__file__).resolve().parent.parent / "corpus" / "record"
CANONICAL_COUNTRIES = frozenset(
    d.name for d in _RECORD_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")
) if _RECORD_DIR.exists() else frozenset()


def _reverse_en(lat: float, lon: float) -> dict:
    cell = (round(lat, 1), round(lon, 1))  # ~10km — one lookup per cluster
    if cell not in _geo_cache:
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=5"
            f"&accept-language=en",
            headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            _geo_cache[cell] = json.load(resp).get("address") or {}
        time.sleep(1.0)  # Nominatim politeness
    return _geo_cache[cell]


def _region_slug(region: str) -> str:
    """Region slugs strip a leading Co./County prefix — UKC says "Co. Antrim",
    geocoders say "County Antrim", the record's hand-picked dir is "antrim";
    this one mechanical rule converges all three."""
    s = slug(region)
    return re.sub(r"^(county-|co-)", "", s) or s


def _reverse_county(lat: float, lon: float) -> str | None:
    """zoom-5 answers stop at state level; county needs its own lookup."""
    cell = ("county", round(lat, 1), round(lon, 1))
    if cell not in _geo_cache:
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=8"
            f"&accept-language=en",
            headers={"User-Agent": "climbing-agent-ingest/0.1 (uncini.michel@gmail.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            _geo_cache[cell] = json.load(resp).get("address") or {}
        time.sleep(1.0)
    a = _geo_cache[cell]
    # NI counties come back under 'historic' ("County Antrim") — they're
    # historic divisions in OSM, verified live 2026-08-12
    return a.get("county") or a.get("historic") or a.get("state_district") or a.get("city")


def _resolve_key_parts(crag: dict) -> tuple[str | None, str | None, list[str]]:
    """(country, region, notes). None means unresolvable -> caller flags."""
    notes = []
    country, region = crag.get("country"), crag.get("region")
    if region and " / " in region:
        notes.append(f"region path truncated to admin region: {region!r}")
        region = region.split(" / ")[0]
    has_coords = crag.get("lat") is not None and crag.get("lon") is not None

    if has_coords and (not country or not region):
        addr = _reverse_en(crag["lat"], crag["lon"])
        geo_state = addr.get("state") or addr.get("region")
        if not country and addr.get("country"):
            # home-nations promotion: if the geocoded STATE is itself a
            # record-canonical country (Northern Ireland, Scotland…), it is
            # the country — that keeps theCrag-geocoded crags keying
            # identically to UKC's stated "Northern Ireland"
            if geo_state and slug(geo_state) in CANONICAL_COUNTRIES:
                country = geo_state
                region = region or addr.get("county") or _reverse_county(crag["lat"], crag["lon"])
                notes.append("country from reverse geocode (home-nation state promoted)")
            else:
                country = addr["country"]
                notes.append("country from reverse geocode")
        if not region and geo_state:
            region = geo_state
            notes.append("region from reverse geocode")
    elif country and has_coords:
        addr = _reverse_en(crag["lat"], crag["lon"])
        # locale fix: sources answering in their own language ("Italia") must
        # key identically to English-named sources ("Italy") — but a stated
        # country already in the record's vocabulary (northern-ireland!) wins
        # over the geocoder's coarser answer ("United Kingdom")
        en = addr.get("country")
        if en and slug(country) not in CANONICAL_COUNTRIES and slug(en) != slug(country):
            notes.append(f"country localized {country!r} -> {en!r}")
            country = en
        # consistency: the source's stated region vs where its own coords land.
        # OpenBeta serves crags whose path says Sardegna but whose lat/lng sit
        # in a Marche bbox (found live 2026-08-12) — two source-stated facts
        # disagreeing is exactly what gets FLAGGED to Michel, never silently
        # resolved. The stated region keeps the key; the conflict goes upstairs.
        # (geo_region == the stated country is just the admin-level echo of the
        # home-nations convention — Co. Antrim vs "Northern Ireland" — not a conflict.)
        geo_region = addr.get("state") or addr.get("region")
        if (region and geo_region and slug(geo_region) != slug(region)
                and slug(geo_region) != slug(country)):
            notes.append(f"CONFLICT: stated region {region!r} but coords geocode to {geo_region!r}")
    if country and not has_coords:
        country = _COUNTRY_EN.get(slug(country), country)
    return country, region, notes


# tiny locale map for coordinate-less sources (climbook) — extend as sources grow;
# anything not here and not geocodable keys under its native name (still 4 parts)
_COUNTRY_EN = {"italia": "Italy", "espana": "Spain", "france": "France",
               "deutschland": "Germany", "osterreich": "Austria", "suisse": "Switzerland"}


def _write_crag(base: Path, flagged_root: Path, crag: dict, routes: list[dict],
                report: dict, source_label: str, used_dirs: set) -> None:
    country, region, notes = _resolve_key_parts(crag)
    name_slug = slug(crag["name"])
    if not country or not region:
        d = flagged_root / source_label
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / f"{name_slug}.json", crag)
        report["flagged"].append({"source": source_label, "crag": crag["name"],
                                  "why": f"missing {'country' if not country else ''}{'/' if not country and not region else ''}{'region' if not region else ''}",
                                  "notes": notes})
        return
    crag_dir = base / slug(country) / _region_slug(region) / name_slug
    if str(crag_dir) in used_dirs:
        # two distinct crags resolving to one directory would silently
        # intermix routes and overwrite _crag.json — same policy as route
        # collisions: disambiguate with the source id, still 4 key parts, report
        suffixed = f"{name_slug}-{slug(str(crag.get('source_id') or 'dup'))}"[:64]
        report["collisions"].append({"source": source_label, "crag": crag["name"],
                                     "kind": "crag-dir", "keyed_as": suffixed})
        crag_dir = crag_dir.with_name(suffixed)
    used_dirs.add(str(crag_dir))
    crag_dir.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in crag.items() if k != "routes"}
    meta["_key_notes"] = notes
    _atomic_write(crag_dir / "_crag.json", meta)
    report["written"] += 1  # _crag.json counts — crag-metadata sources (falesia.it) write no route files
    if notes:
        report["key_notes"].append({"source": source_label, "crag": crag["name"], "notes": notes})
    conflicts = [n for n in notes if n.startswith("CONFLICT")]
    if conflicts:
        report["conflicts"].append({"source": source_label, "crag": crag["name"],
                                    "keyed_under": f"{slug(country)}/{_region_slug(region)}",
                                    "detail": conflicts})
    used = {}
    for r in routes:
        rs = slug(r.get("name") or "route")
        if rs in used:
            sid = slug(str(r.get("source_id") or r.get("refs", [{}])[0].get("source_id") or "dup"))
            rs = f"{rs}-{sid}"[:64]
            report["collisions"].append({"source": source_label, "crag": crag["name"],
                                         "route": r.get("name"), "keyed_as": rs})
        used[rs] = True
        _atomic_write(crag_dir / f"{rs}.json", r)
        report["written"] += 1


def key_run(run_id: str) -> dict:
    run = Run.load(run_id)
    report = {"run_id": run_id, "written": 0, "flagged": [], "conflicts": [],
              "collisions": [], "key_notes": []}

    flagged_root = run.dir / "keyed" / "_flagged"
    used_dirs: set = set()
    src_dir = run.dir / "enriched"
    if not src_dir.exists() or not any(src_dir.glob("*.json")):
        src_dir = run.dir / "parsed"
    for f in sorted(src_dir.glob("*.json")):
        inv = json.loads(f.read_text())
        if inv.get("kind") == "chatter":
            continue
        for c in inv.get("crags") or []:
            _write_crag(run.dir / "keyed" / "crawl" / f.stem, flagged_root,
                        c, c.get("routes") or [], report, f.stem, used_dirs)

    curated = run.dir / "llm-curated" / "inventory.json"
    if curated.exists():
        inv = json.loads(curated.read_text())
        for c in inv.get("crags") or []:
            _write_crag(run.dir / "keyed" / "curated", flagged_root,
                        c, c.get("routes") or [], report, "curated", used_dirs)

    _atomic_write(run.dir / "keyed" / "report.json", report)
    run.log(f"keyed: {report['written']} files, {len(report['flagged'])} flagged, "
            f"{len(report['collisions'])} slug collisions")
    return report

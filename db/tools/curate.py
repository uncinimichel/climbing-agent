#!/usr/bin/env python3
"""Curation Studio — the localhost admin that turns drafts into curated rows.

Record-first (decision #39, supersedes #34's Postgres): this app reads AND
WRITES the JSON record under db/record/ through store.py — one self-contained
document per route, validated against schemas generated from the taxonomy
files. db/corpus.json stays a derived export (build_corpus.py), not the store.
Governance (#32) is enforced here and by the store's schema: publishing flips
tagged_by → 'human' (a publish row may never stay 'llm').

Run:  ../../agent/.venv/bin/uvicorn curate:app --port 8890   (from db/tools/)
  or: agent/.venv/bin/python db/tools/curate.py              (from repo root)

Localhost only, single editor, no auth (same stance as the #33 trips admin).
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from store import store

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UI = HERE / "curate_ui.html"
ENRICH_CACHE = ROOT / "db" / "enrichment-cache.json"
UPLOAD_DIR = ROOT / "db" / "uploads"          # staging area; the site build copies these out
TAX_VALUES_OUT = ROOT / "knowledge" / "data" / "taxonomy-values.json"

S = store()

app = FastAPI(title="Curation Studio")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

from topo_api import router as _topo_router  # noqa: E402 — drawn-topo endpoints (decision #37)
app.include_router(_topo_router)

# The Studio has no auth BY DESIGN (loopback-only). This guard closes the two
# holes that design leaves open (sec review 17 Jul #6): DNS-rebinding (a
# hostile page resolving its own domain to 127.0.0.1 — caught by the Host
# check) and cross-site "simple" POSTs driving mutations (caught by the
# Origin check; browsers always attach Origin to cross-site POSTs).
_OK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "db", "studio"}


@app.middleware("http")
async def _local_only(request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host not in _OK_HOSTS:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Studio answers localhost only"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        from urllib.parse import urlparse
        if (urlparse(origin).hostname or "").lower() not in _OK_HOSTS:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "cross-origin writes are not allowed"}, status_code=403)
    return await call_next(request)


MAX_UPLOAD_BYTES = 30 * 1024 * 1024   # crag photos are big; 30MB is still sane

_enrich = {"mtime": None, "data": {}}


def enrich_cache() -> dict:
    """enrichment-cache.json, re-read only when the file changes."""
    try:
        mt = ENRICH_CACHE.stat().st_mtime
    except FileNotFoundError:
        return {}
    if _enrich["mtime"] != mt:
        _enrich.update(mtime=mt, data=json.loads(ENRICH_CACHE.read_text()))
    return _enrich["data"]

# fields PATCH may write on route — everything a curator verifies or fills
PATCHABLE = {
    "name", "length_m", "pitches_count", "incline_code", "grade_system_code",
    "original_grade", "trad_grade", "tech_grade", "data_grade",
    "protection_code", "protection_style", "belays", "rack", "rope",
    "approach_time_min", "approach_difficulty",
    "descent_method", "descent_abseils", "descent_notes",
    "elevation_m", "sun_window_code", "wind_exposed", "best_season", "stars",
    "intro_html", "approach_html", "pitch_info_html", "curation_notes",
    "escapable", "commitment_code",
}
TAG_KEYS = ("disciplines", "features", "character")
# the pieces of a route document the API serves under their own (differently
# shaped) keys — everything else in the file is a plain route column
EMBEDDED = {"tags", "hazards", "pitches", "guidebooks", "references", "parkings",
            "climatology", "external_refs", "first_ascents", "provenance"}

# typed PATCH fields → validated server-side with a clear 422 instead of the
# raw 500 a curator used to get for typing "ninety" into length m
NUMERIC_PATCH = {"length_m", "pitches_count", "approach_time_min", "elevation_m",
                 "descent_abseils", "approach_difficulty", "stars", "data_grade"}
BOOL_PATCH = {"wind_exposed", "escapable"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tag_count(key: str, code: str) -> int:
    return sum(code in (r.get("tags") or {}).get(key, []) for r in S.routes.values())


def _field_count(field: str, code: str) -> int:
    return sum(r.get(field) == code for r in S.routes.values())


# Studio-managed vocabularies (decision #35): family → (taxonomies.json key,
# editable meta columns, usage counter). Adding/editing values here IS the
# taxonomy write path; every write persists taxonomies.json and re-exports
# taxonomy-values.json (the AI tagger reads it). The 105 SQL re-seed is gone
# with Postgres (#39).
TAXONOMY = {
    "discipline": ("discipline", ["meaning"], lambda c: _tag_count("disciplines", c)),
    "feature": ("feature", ["meaning"], lambda c: _tag_count("features", c)),
    "character": ("character", ["meaning"], lambda c: _tag_count("character", c)),
    "hazard": ("hazard", ["kind", "meaning", "safety_critical", "feeds"],
               lambda c: sum(any(h["hazard_code"] == c for h in r.get("hazards", []))
                             for r in S.routes.values())),
    "rock": ("rock_type", ["friction_dry", "seeps", "fragile_when_wet", "notes"],
             lambda c: _field_count("rock_code", c)
             + sum(a.get("rock_code") == c for a in S.areas.values())),
    "sun_window": ("sun_window", ["meaning"], lambda c: _field_count("sun_window_code", c)),
    "protection": ("protection_grade", ["meaning", "sort_order"],
                   lambda c: _field_count("protection_code", c)),
}


# Per-system grade shapes (Michel: "grade should be known so no free text — and say
# which scale"). Strict where the scale is well-defined; systems without a pattern
# accept any non-empty token but the SYSTEM itself is always required.
GRADE_PATTERNS = {
    "BAS":  r"^(M|D|VD|HVD|MS|S|HS|MVS|VS|HVS|E\d{1,2})(\s\d[abc])?$",
    "FS":   r"^f?\d[abc]\+?$",
    "YDS":  r"^5\.\d{1,2}[abcd]?[+-]?$",
    "UIAA": r"^(I{1,3}|IV|V|VI{0,3}|VII|VIII|IX|X|XI|XII)[+-]?$",
    "V":    r"^V(B|\d{1,2})\+?$",
    "Font": r"^\d[ABCabc]\+?$",
    "EW":   r"^\d{1,2}$",
    "WI":   r"^WI\d\+?$",
    "AI":   r"^AI\d\+?$",
    "M":    r"^M\d{1,2}\+?$",
    "A":    r"^A[0-5]\+?$",
    "C":    r"^C[0-5]\+?$",
    "ALP":  r"^(F|PD|AD|D|TD|ED[1-4]?)[+-]?$",
    "SCO":  r"^(I{1,3}|IV|V|VI|VII|VIII|IX|X|XI)\s*,?\s*\d{1,2}$",
}


def grade_problem(system: str | None, value: str | None) -> str | None:
    """None if (system, value) is acceptable; else a human-readable problem."""
    if not value:
        return "no grade"
    if not system:
        return "grade has no system — pick the scale it is in"
    pat = GRADE_PATTERNS.get(system)
    if pat and not re.match(pat, value.strip()):
        return f"'{value}' does not look like a {system} grade"
    return None


def resync_taxonomy_files():
    """Regenerate knowledge/data/taxonomy-values.json from the record — same
    shape the Postgres exporter produced, because ai_tag.py and the docs read
    it. Synchronous now: it is one in-memory pass, not a psql round-trip."""
    families = {}
    for fam, (key, cols, usage) in TAXONOMY.items():
        # the served file counts ROUTE usage only (export_taxonomy.py's shape);
        # the Studio's own delete guard additionally counts areas for rock
        count = (lambda c: _field_count("rock_code", c)) if fam == "rock" else usage
        families[fam] = [
            {"code": t["code"], **{c: t.get(c) for c in cols}, "usage": count(t["code"])}
            for t in sorted(S.tax[key], key=lambda t: t["code"])]
    TAX_VALUES_OUT.write_text(json.dumps(
        {"generated": date.today().isoformat(),
         "note": "Live enum values exported from the JSON record (decision #39). Semantic "
                 "definitions & tagging rules: taxonomy.md. Managed via the Curation "
                 "Studio's Taxonomy page.",
         "families": families}, ensure_ascii=False, indent=1) + "\n")


def get_route(rid: int) -> dict:
    r = S.routes.get(rid)
    if not r:
        raise HTTPException(404)
    return r


def save_route(r: dict):
    """Persist through the store; its schema is the old DB constraint set, so a
    violation surfaces as a curator-readable 422, not a 500."""
    try:
        S.save_route(r)
    except ValueError as e:
        raise HTTPException(422, str(e))


def agg_tags(r: dict) -> dict:
    tags = {key: sorted((r.get("tags") or {}).get(key, [])) for key in TAG_KEYS}
    tags["hazards"] = sorted(h["hazard_code"] for h in r.get("hazards", []))
    return tags


def parking_rows(r: dict) -> list[dict]:
    rows = [{"id": pk.get("id"), "label": pk.get("label"), "ord": pk.get("ord"),
             "lat": pk.get("lat"), "lon": pk.get("lon")} for pk in r.get("parkings", [])]
    return sorted(rows, key=lambda p: (p["ord"] or 0, p["id"] or 0))


@app.get("/", response_class=HTMLResponse)
def index():
    return UI.read_text()


@app.get("/api/enums")
def enums():
    codes = lambda key: sorted(t["code"] for t in S.tax[key])  # noqa: E731
    out = {key: codes(table) for key, table in
           [("features", "feature"), ("character", "character"), ("hazards", "hazard"),
            ("disciplines", "discipline"), ("incline", "incline"),
            ("sun_window", "sun_window"), ("rock", "rock_type")]}
    # meanings ride along where the UI shows them (Michel: PG/PG-13 are not
    # guesses — Erickson's G/PG/PG-13/R/X seriousness scale; say what each means)
    out["protection"] = [{"code": p["code"], "meaning": p.get("meaning")}
                         for p in sorted(S.tax["protection_grade"],
                                         key=lambda p: p.get("sort_order") or 0)]
    out["grade_systems"] = [{"code": g["code"], "name": g.get("name"), "region": g.get("region")}
                            for g in sorted(S.grades["systems"], key=lambda g: g["code"])]
    ladder = {}
    for c in sorted(S.grades["conversions"],
                    key=lambda c: (c["grade_system_code"], c["data_grade"])):
        ladder.setdefault(c["grade_system_code"], []).append(c["original_grade"])
    out["grade_ladder"] = ladder
    out["grade_patterns"] = GRADE_PATTERNS
    out["protection_style"] = ["gear", "bolted", "mixed", "none"]
    out["belays"] = ["gear", "bolted", "mixed"]
    out["descent_method"] = ["walk-off", "abseil", "lower-off"]
    return out


@app.get("/api/queue")
def queue(status: str = "draft", q: str = "", crag: str = ""):
    rows, ql = [], q.lower()
    for r in S.routes.values():
        toks = S.areas.get(r["area_id"], {}).get("path_tokens", [])
        if status != "all" and r["status"] != status:
            continue
        # match the route name or ANY level of the location path (country,
        # region, crag, sector) — token[3] alone missed "Antrim" or "Italy"
        if ql and ql not in r["name"].lower() and ql not in " ".join(toks).lower():
            continue
        if crag and (len(toks) < 3 or toks[2] != crag):
            continue
        rows.append({
            "id": r["id"], "name": r["name"], "status": r["status"],
            "tagged_by": r["tagged_by"], "needs_field_check": r.get("needs_field_check"),
            "original_grade": r.get("original_grade"), "length_m": r.get("length_m"),
            "pitches_count": r.get("pitches_count"), "stars": r.get("stars"),
            "has_season": r.get("best_season") is not None,
            "has_intro": r.get("intro_html") is not None,
            "n_pitches_rows": len(r.get("pitches") or []),
            "path_tokens": toks,
        })
    rows.sort(key=lambda x: (x["path_tokens"], x["name"]))
    counts = {}
    for r in S.routes.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    counts["field_check"] = sum(1 for r in S.routes.values() if r.get("needs_field_check"))
    return {"rows": rows, "counts": counts}


@app.get("/api/map")
def map_points():
    """Every route with its location path and status — feeds the drill-down
    aggregates AND the map. Routes without their own coordinates fall back to
    the nearest ancestor area that has one (approx=true); lat/lon may be null."""
    out = []
    for r in sorted(S.routes.values(), key=lambda r: r["id"]):
        lat, lon = r.get("lat"), r.get("lon")
        approx = lat is None
        if approx:
            for a in S.area_chain(r["area_id"]):
                if a.get("lat") is not None:
                    lat, lon = a["lat"], a["lon"]
                    break
        out.append({"id": r["id"], "name": r["name"], "status": r["status"],
                    "original_grade": r.get("original_grade"),
                    "path_tokens": S.areas.get(r["area_id"], {}).get("path_tokens", []),
                    "lat": lat, "lon": lon, "approx": approx})
    return out


@app.get("/api/route/{rid}")
def route_detail(rid: int):
    r = get_route(rid)
    ar = S.areas[r["area_id"]]
    out = {k: v for k, v in r.items() if k not in EMBEDDED}
    out["path_tokens"] = ar["path_tokens"]
    # eff_* mirror the old resolved views: area-chain inheritance for the badge
    # row (the route's OWN field is shown in its editable fact tile)
    out["eff_rock_code"] = ar.get("eff_rock_code")
    out["eff_aspect"] = ar.get("eff_aspect")
    out["eff_grade_context"] = ar.get("eff_grade_context")
    out["eff_timezone"] = r.get("timezone") or ar.get("eff_timezone")
    out["parkings"] = parking_rows(r)
    out["grade_warning"] = grade_problem(r.get("grade_system_code"), r.get("original_grade"))
    out["tags"] = agg_tags(r)
    out["pitch_rows"] = [
        {"number": p.get("number"), "length_m": p.get("length_m"),
         "grade_system_code": p.get("grade_system_code"),
         "original_grade": p.get("original_grade"), "description": p.get("description")}
        for p in sorted(r.get("pitches") or [], key=lambda p: p.get("number") or 0)]
    out["refs"] = [{"source_id": x.get("source_id"), "external_id": x.get("external_id"),
                    "url": x.get("url")} for x in r.get("external_refs") or []]
    out["guidebooks"] = [
        {"id": g.get("id"), "isbn": g.get("isbn"), "title": g.get("title"),
         "rrp": g.get("rrp"), "img_url": g.get("img_url"), "link": g.get("link"),
         "kind": g.get("kind"), "page": g.get("page"), "description": g.get("description")}
        for g in sorted(r.get("guidebooks") or [], key=lambda g: g.get("title") or "")]
    out["references"] = [{"id": x.get("id"), "prefix": x.get("prefix"),
                          "text": x.get("text"), "url": x.get("url")}
                         for x in sorted(r.get("references") or [],
                                         key=lambda x: x.get("id") or 0)]
    out["climatology"] = sorted(r.get("climatology") or [], key=lambda m: m["month"])
    # AI receipt from the enrichment cache (keyed mp-<id>)
    out["receipt"] = None
    mp = next((x for x in out["refs"] if x["source_id"] == "multipitch"), None)
    if mp:
        out["receipt"] = enrich_cache().get(f"mp-{mp['external_id']}")
    return out


@app.patch("/api/route/{rid}")
def patch_route(rid: int, body: dict):
    fields = {k: v for k, v in body.items() if k in PATCHABLE}
    tags = body.get("tags") or {}
    has_coords = "lat" in body or "lon" in body
    if not fields and not tags and not has_coords:
        raise HTTPException(400, "nothing patchable in body")
    for k, v in list(fields.items()):
        if v is None:
            continue
        if k in NUMERIC_PATCH:
            try:
                fields[k] = int(v)
            except (TypeError, ValueError):
                raise HTTPException(422, f"{k.replace('_', ' ')} must be a whole number — got '{v}'")
        elif k in BOOL_PATCH and not isinstance(v, bool):
            fields[k] = str(v).lower() in ("true", "yes", "1")
    r = copy.deepcopy(get_route(rid))
    if has_coords:
        try:
            lat, lon = float(body.get("lat")), float(body.get("lon"))
        except (TypeError, ValueError):
            raise HTTPException(422, "lat and lon must both be numbers (decimal degrees)")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(422, "lat/lon out of range")
        r["lat"], r["lon"] = lat, lon
    r.update(fields)
    warning = None
    if {"original_grade", "grade_system_code"} & set(fields):
        warning = grade_problem(r.get("grade_system_code"), r.get("original_grade"))
    for key, values in tags.items():
        if key in TAG_KEYS:
            r.setdefault("tags", {})[key] = sorted(dict.fromkeys(values))
        elif key == "hazards":
            # keep the real evidence of hazards that stay; only NEW codes get
            # the curator stamp — tag saves must never erase source provenance
            prior = {h["hazard_code"]: h for h in r.get("hazards", [])}
            r["hazards"] = [
                {"hazard_code": v,
                 "evidence_span": (prior.get(v) or {}).get("evidence_span")
                 or "curator verified (Curation Studio)",
                 "source_url": (prior.get(v) or {}).get("source_url")}
                for v in sorted(dict.fromkeys(values))]
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "gradeWarning": warning}


@app.put("/api/route/{rid}/parkings")
def put_parkings(rid: int, body: list[dict]):
    """Replace the route's parking spots: [{label, lat, lon}] — multiple pins, ordered."""
    r = copy.deepcopy(get_route(rid))
    rows = []
    for i, pk in enumerate(body, 1):
        if pk.get("lat") is None or pk.get("lon") is None:
            continue
        try:
            lat, lon = float(pk["lat"]), float(pk["lon"])
        except (TypeError, ValueError):
            raise HTTPException(422, "parking lat/lon must be numbers")
        rows.append({"id": i, "label": (pk.get("label") or "parking").strip() or "parking",
                     "ord": i, "lat": lat, "lon": lon})
    r["parkings"] = rows
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "parkings": len(body)}


@app.put("/api/route/{rid}/pitches")
def put_pitches(rid: int, body: list[dict]):
    r = copy.deepcopy(get_route(rid))
    r["pitches"] = [
        {"number": p["number"], "length_m": p.get("length_m"),
         "grade_system_code": p.get("grade_system_code"),
         "original_grade": p.get("original_grade"),
         "description": p.get("description"), "bolts_count": p.get("bolts_count")}
        for p in body if p.get("number")]
    r["pitches_count"] = len(body) or None
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "pitches": len(body)}


IMAGE_KINDS = {"tile_image", "map_img", "topo"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@app.post("/api/route/{rid}/image/{kind}")
async def upload_image(rid: int, kind: str, file: UploadFile = File(...)):
    """Store an image in db/uploads/ and point the route's image blob at it.
    Existing keys (alt, attribution…) are preserved; only url changes."""
    if kind not in IMAGE_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(IMAGE_KINDS)}")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in IMAGE_EXTS:
        raise HTTPException(422, f"image files only ({', '.join(sorted(IMAGE_EXTS))})")
    r = copy.deepcopy(get_route(rid))
    dest = UPLOAD_DIR / f"route-{rid}"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{kind}{ext}"
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"image too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)")
    path.write_bytes(data)
    url = f"/uploads/route-{rid}/{kind}{ext}"
    r[kind] = {**(r.get(kind) or {}), "url": url}
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "url": url}


@app.get("/api/sources")
def sources():
    return [{"id": s["id"], "name": s.get("name")}
            for s in sorted(S.tax["source"], key=lambda s: s["id"])]


@app.post("/api/route/{rid}/refs")
def add_ref(rid: int, body: dict):
    """Attach a source link (external_ref) to a route — one per source."""
    sid, url = (body.get("source_id") or "").strip(), (body.get("url") or "").strip()
    if not sid or not url:
        raise HTTPException(422, "source_id and url are both required")
    if sid not in {s["id"] for s in S.tax["source"]}:
        raise HTTPException(422, f"unknown source '{sid}'")
    ext = (body.get("external_id") or url).strip()
    # the old UNIQUE (source_id, external_id): one route per source page
    for other in S.routes.values():
        if other["id"] != rid and any(
                x["source_id"] == sid and x["external_id"] == ext
                for x in other.get("external_refs") or []):
            raise HTTPException(409, f"that {sid} page is already linked to another route")
    r = copy.deepcopy(get_route(rid))
    refs = [x for x in r.get("external_refs") or [] if x["source_id"] != sid]
    refs.append({"source_id": sid, "external_id": ext, "url": url})
    r["external_refs"] = sorted(refs, key=lambda x: x["source_id"])
    r["last_update"] = now()
    save_route(r)
    return {"ok": True}


@app.delete("/api/route/{rid}/refs/{source_id}")
def del_ref(rid: int, source_id: str):
    r = copy.deepcopy(get_route(rid))
    refs = r.get("external_refs") or []
    kept = [x for x in refs if x["source_id"] != source_id]
    if len(kept) == len(refs):
        raise HTTPException(404)
    r["external_refs"] = kept
    r["last_update"] = now()
    save_route(r)
    return {"ok": True}


REF_PREFIXES = {"Video", "Travel", "Article", "Info", "Tides", "Access", "Accommodation"}


@app.put("/api/route/{rid}/references")
def put_references(rid: int, body: list[dict]):
    """Replace the route's outbound reference links. Text is stored verbatim;
    the prefix is parsed metadata (mp-field-mapping.md) — never invented."""
    r = copy.deepcopy(get_route(rid))
    next_id = max((x.get("id") or 0 for rr in S.routes.values()
                   for x in rr.get("references") or []), default=0) + 1
    rows = []
    for ref in body:
        text, url = (ref.get("text") or "").strip(), (ref.get("url") or "").strip()
        if not text or not url:
            continue
        head = text.split(":", 1)[0].strip() if ":" in text else ""
        rows.append({"id": next_id, "route_id": rid,
                     "prefix": head if head in REF_PREFIXES else None,
                     "text": text, "url": url})
        next_id += 1
    r["references"] = rows
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "references": len(rows)}


@app.put("/api/route/{rid}/guidebooks")
def put_guidebooks(rid: int, body: list[dict]):
    """Replace the route's guidebook links; guidebook identity is shared across
    routes and deduped on isbn (else title) — edits here update every copy."""
    r = copy.deepcopy(get_route(rid))
    # the shared registry is implicit now: every embedded copy, indexed
    by_isbn, by_title, max_id = {}, {}, 0
    for rr in S.routes.values():
        for g in rr.get("guidebooks") or []:
            max_id = max(max_id, g.get("id") or 0)
            if g.get("isbn"):
                by_isbn.setdefault(g["isbn"], g.get("id"))
            if g.get("title"):
                by_title.setdefault(g["title"], g.get("id"))
    rows, shared = [], {}
    for g in body:
        title = (g.get("title") or "").strip()
        if not title:
            continue
        isbn = (str(g["isbn"]).strip() or None) if g.get("isbn") else None
        kind = "pdf" if (g.get("kind") or "").lower() == "pdf" else "guidebook"
        gid = (by_isbn.get(isbn) if isbn else None) or by_title.get(title)
        if gid is None:
            max_id += 1
            gid = max_id
        meta = {"isbn": isbn, "title": title, "rrp": g.get("rrp") or None,
                "img_url": g.get("img_url") or None, "link": g.get("link") or None,
                "kind": kind}
        shared[gid] = meta
        rows.append({"id": gid, **meta, "page": g.get("page") or None,
                     "description": g.get("description") or None})
    r["guidebooks"] = rows
    r["last_update"] = now()
    save_route(r)
    for rr in list(S.routes.values()):     # propagate shared metadata edits
        if rr["id"] == rid or not any(
                g.get("id") in shared for g in rr.get("guidebooks") or []):
            continue
        rr2 = copy.deepcopy(rr)
        for g in rr2["guidebooks"]:
            if g.get("id") in shared:
                g.update(shared[g["id"]])
        save_route(rr2)
    return {"ok": True, "guidebooks": len(rows)}


@app.post("/api/route/{rid}/publish")
def publish(rid: int):
    r = copy.deepcopy(get_route(rid))
    problem = grade_problem(r.get("grade_system_code"), r.get("original_grade"))
    if problem:
        raise HTTPException(422, f"grade check: {problem}")
    if r.get("needs_field_check"):
        raise HTTPException(422, "flagged 🥾 needs field check — clear the flag "
                                 "(⌘F) once verified, then publish")
    r["status"], r["tagged_by"] = "publish", "human"
    r["curated_at"] = r["last_update"] = now()
    save_route(r)
    return {"ok": True, "status": "publish"}


@app.post("/api/route/{rid}/status/{new}")
def set_status(rid: int, new: str):
    if new not in ("draft", "quarantined"):
        raise HTTPException(422, "status must be draft or quarantined")
    r = copy.deepcopy(get_route(rid))
    r["status"] = new
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "status": new}


@app.post("/api/route/{rid}/fieldcheck")
def fieldcheck(rid: int):
    r = copy.deepcopy(get_route(rid))
    r["needs_field_check"] = not r.get("needs_field_check")
    r["last_update"] = now()
    save_route(r)
    return {"ok": True, "needs_field_check": r["needs_field_check"]}


@app.get("/api/taxonomy")
def taxonomy():
    out = {}
    for fam, (key, cols, usage) in TAXONOMY.items():
        out[fam] = [{"code": t["code"], **{c: t.get(c) for c in cols},
                     "usage": usage(t["code"])}
                    for t in sorted(S.tax[key], key=lambda t: t["code"])]
    return out


@app.post("/api/taxonomy/{family}")
def taxonomy_add(family: str, body: dict):
    if family not in TAXONOMY:
        raise HTTPException(404, f"unknown family {family}")
    key, cols, _ = TAXONOMY[family]
    code = (body.get("code") or "").strip()
    if not code or len(code) > 40 or any(ch.isspace() for ch in code) \
            or any(ch in code for ch in "'\"<>\\;`"):
        raise HTTPException(422, "code must be one token (≤40 chars, no quotes/angle brackets)")
    if family == "hazard" and body.get("kind") not in ("route", "objective"):
        raise HTTPException(422, "hazard needs kind: route | objective")
    if "meaning" in cols and not (body.get("meaning") or "").strip():
        raise HTTPException(422, "a new value needs a meaning — it feeds the AI tagger")
    meta = {c: body.get(c) for c in cols if body.get(c) is not None}
    if family == "hazard":
        meta.setdefault("safety_critical", False)
    if any(t["code"] == code for t in S.tax[key]):
        raise HTTPException(409, f"{code} already exists in {family}")
    S.tax[key].append({"code": code, **meta})
    S.tax[key].sort(key=lambda t: t["code"])
    S.save_taxonomies()
    resync_taxonomy_files()
    return {"ok": True, "family": family, "code": code}


@app.patch("/api/taxonomy/{family}/{code}")
def taxonomy_edit(family: str, code: str, body: dict):
    if family not in TAXONOMY:
        raise HTTPException(404, f"unknown family {family}")
    key, cols, _ = TAXONOMY[family]
    meta = {c: body[c] for c in cols if c in body}
    if not meta:
        raise HTTPException(400, "nothing editable in body")
    row = next((t for t in S.tax[key] if t["code"] == code), None)
    if not row:
        raise HTTPException(404, f"{code} not in {family}")
    row.update(meta)
    S.save_taxonomies()
    resync_taxonomy_files()
    return {"ok": True}


@app.delete("/api/taxonomy/{family}/{code}")
def taxonomy_delete(family: str, code: str):
    if family not in TAXONOMY:
        raise HTTPException(404, f"unknown family {family}")
    key, _, usage = TAXONOMY[family]
    row = next((t for t in S.tax[key] if t["code"] == code), None)
    if not row:
        raise HTTPException(404, f"{code} not in {family}")
    n = usage(code)
    if n:
        raise HTTPException(409, f"{code} is used by {n} routes — retag them first")
    S.tax[key].remove(row)
    S.save_taxonomies()
    resync_taxonomy_files()
    return {"ok": True}


@app.post("/api/export")
def export():
    """Regenerate the committed corpus.json export from the record."""
    p = subprocess.run([sys.executable, str(HERE / "build_corpus.py")],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise HTTPException(500, p.stderr[-800:])
    return {"ok": True, "out": p.stdout.strip()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8890)

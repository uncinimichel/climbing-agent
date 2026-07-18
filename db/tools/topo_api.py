"""Topo endpoints for the Curation Studio (decision #37) — included by
curate.py, so drawing topos happens in the same tool, same route picker,
same filters as all other curation.

Model: a topos.json entry = the crag photo (credit + license mandatory;
non-owned photos need a permission note — only owned/permissioned photos may
ever reach a booklet) + a drawable canvas over it; each line = one route's
line/pitches/descent as NORMALIZED 0-1 fractions of the oriented image
(tech review 17 Jul 2026: EXIF orientation is baked at upload and dims come
from the server, so there is exactly one coordinate space; fractions survive
image re-derivation and match the OSM `wikimedia_commons:path` convention
for future export). Descent = a list of labelled segments
[{path, label, anchor, labelPosition}] — multi-pitch's richer shape.

Lines are keyed by route NAME + area (the record's natural key, #39); the
integer ids the UI addresses are assigned by the store at load and stay put.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import images
from store import store

ROOT = Path(__file__).resolve().parents[2]
TOPO_DIR = ROOT / "db" / "uploads" / "topos" / "studio"

S = store()

router = APIRouter()
TOPO_DIR.mkdir(parents=True, exist_ok=True)


def _line_route(ln: dict) -> dict | None:
    return S.find_route(ln["route_name"], ln.get("route_area"))


def _get_topo(topo_id: int) -> dict:
    t = S.topo(topo_id)
    if not t:
        raise HTTPException(404, "no such topo")
    return t


@router.get("/api/route/{rid}/topoinfo")
def route_topoinfo(rid: int):
    """Everything the route card's topo section needs: the topos available in
    this route's area (crag + sibling sectors), flagged with whether this
    route already has a line on them."""
    r = S.routes.get(rid)
    a = r and S.areas.get(r["area_id"])
    if not a:
        raise HTTPException(404, "no such route")
    # the topo neighbourhood = the route's CRAG (its own area, or the parent
    # when the route sits in a sector) + that crag's sectors — never the whole
    # region, or every crag in the Mournes would offer its photos here
    crag = (a.get("parent_id") or a["id"]) if a.get("kind") == "sector" else a["id"]
    hood = {crag} | {c["id"] for c in S.areas.values() if c.get("parent_id") == crag}
    topos = []
    for t in S.topos:
        if t.get("area_id") not in hood:
            continue
        drawn = {rr["id"] for ln in t.get("lines", []) if (rr := _line_route(ln))}
        topos.append({"id": t["id"], "title": t.get("title"), "status": t.get("status"),
                      "belay_size": t.get("belay_size"), "uri": t["uri"],
                      "width_px": t.get("width_px"), "height_px": t.get("height_px"),
                      "credit": t.get("credit"), "license": t.get("license"),
                      "lines": len(t.get("lines", [])), "has_route": rid in drawn})
    topos.sort(key=lambda t: (t["has_route"], t["id"]), reverse=True)
    return {"area_id": a["id"], "topos": topos}


@router.get("/api/topo/{topo_id}")
def topo_detail(topo_id: int):
    t = _get_topo(topo_id)
    lines = []
    for ln in t.get("lines", []):
        r = _line_route(ln)
        if not r:                        # a line for a renamed/removed route — lint's job
            continue
        lines.append({"route_id": r["id"], "route_name": r["name"], "line": ln.get("line"),
                      "pitches": ln.get("pitches"), "descent": ln.get("descent")})
    lines.sort(key=lambda x: x["route_name"])
    return {"id": t["id"], "title": t.get("title"), "status": t.get("status"),
            "belay_size": t.get("belay_size"), "area_id": t.get("area_id"),
            "uri": t["uri"], "width_px": t.get("width_px"), "height_px": t.get("height_px"),
            "credit": t.get("credit"), "license": t.get("license"), "lines": lines}


@router.post("/api/topomedia")
async def upload_topo_photo(file: UploadFile = File(...), area_id: int = Form(...),
                            credit: str = Form(...), license: str = Form("owned"),
                            permission_note: str = Form(""), title: str = Form("")):
    if license not in ("owned", "permission", "cc"):
        raise HTTPException(400, "license must be owned|permission|cc")
    if license != "owned" and not permission_note.strip():
        raise HTTPException(400, "non-owned photos need a permission note (who granted it, when)")
    ext = (Path(file.filename or "x.jpg").suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "jpg/png/webp only")
    area = S.areas.get(area_id)
    if not area:
        raise HTTPException(404, "no such area")
    # photos co-locate with their crag (decision #40): …/crag/media/<file>
    prefix, _ = S.crag_prefix(area_id)
    dest = S.dir / prefix / "media" / f"a{area_id}-{int(time.time())}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    MAX = 30 * 1024 * 1024
    data = await file.read(MAX + 1)
    if len(data) > MAX:
        raise HTTPException(413, "photo too large (max 30MB)")
    dest.write_bytes(data)
    try:   # bake EXIF orientation; the server's oriented dims ARE the coordinate space
        w, h = images.normalize(dest)
        images.derive(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "could not read that image — is it a valid photo?")
    tid = S.new_topo_id()
    S.topos.append({
        "id": tid, "area_id": area_id, "area_name": area["name"],
        "title": title or area["name"], "status": "draft", "belay_size": 24,
        "kind": "crag_photo", "uri": f"record/{prefix}/media/{dest.name}",
        "width_px": w, "height_px": h, "credit": credit, "license": license,
        "permission_note": permission_note or None, "taken_at": None, "lines": []})
    S.save_topos()
    return {"topo_id": tid}


@router.delete("/api/topo/{topo_id}")
def delete_topo(topo_id: int):
    """Remove a bad/typo'd upload: the topo entry, its lines, and the files."""
    t = _get_topo(topo_id)
    S.topos.remove(t)
    S.save_topos()
    # uris: 'record/…' = co-located under db/record (decision #40);
    # 'uploads/…' = the legacy staging tree
    f = (S.dir / t["uri"].removeprefix("record/")) if t["uri"].startswith("record/") \
        else ROOT / "db" / t["uri"]
    for p in [f, *images.variant_paths(f).values()]:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    return {"ok": True}


class TopoPatch(BaseModel):
    title: str | None = None
    belay_size: int | None = None
    status: str | None = None


@router.put("/api/topo/{topo_id}")
def patch_topo(topo_id: int, p: TopoPatch):
    if p.status is not None and p.status not in ("draft", "publish"):
        raise HTTPException(400, "status must be draft|publish")
    t = S.topo(topo_id)
    if t:                                # old UPDATE … was a silent no-op on a bad id
        if p.title is not None:
            t["title"] = p.title
        if p.belay_size is not None:
            t["belay_size"] = p.belay_size
        if p.status is not None:
            t["status"] = p.status
        S.save_topos()
    return {"ok": True}


class LineBody(BaseModel):
    line: list
    pitches: list | None = None
    descent: list | None = None


@router.put("/api/topo/{topo_id}/line/{route_id}")
def put_line(topo_id: int, route_id: int, body: LineBody):
    if len(body.line) < 2:
        raise HTTPException(400, "a line needs at least 2 points")
    t = _get_topo(topo_id)
    r = S.routes.get(route_id)
    if not r:
        raise HTTPException(404, "no such route")
    ln = next((ln for ln in t.get("lines", [])
               if (rr := _line_route(ln)) and rr["id"] == route_id), None)
    if not ln:
        ln = {"route_name": r["name"],
              "route_area": S.areas.get(r["area_id"], {}).get("name"),
              "source_id": None}
        t.setdefault("lines", []).append(ln)
    ln["line"] = body.line
    ln["pitches"] = body.pitches or []
    ln["descent"] = body.descent if body.descent else None
    S.save_topos()
    return {"ok": True}


@router.delete("/api/topo/{topo_id}/line/{route_id}")
def del_line(topo_id: int, route_id: int):
    t = _get_topo(topo_id)
    t["lines"] = [ln for ln in t.get("lines", [])
                  if not ((rr := _line_route(ln)) and rr["id"] == route_id)]
    S.save_topos()
    return {"ok": True}

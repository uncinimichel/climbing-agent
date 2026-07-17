"""Topo endpoints for the Curation Studio (decision #37) — included by
curate.py, so drawing topos happens in the same tool, same route picker,
same filters as all other curation.

Model: media = the crag photo (credit + license mandatory; non-owned photos
need a permission note — only owned/permissioned photos may ever reach a
booklet); topo = a drawable canvas over one photo; topo_line = one route's
line/pitches/descent as NORMALIZED 0-1 fractions of the oriented image
(tech review 17 Jul 2026: EXIF orientation is baked at upload and dims come
from the server, so there is exactly one coordinate space; fractions survive
image re-derivation and match the OSM `wikimedia_commons:path` convention
for future export). Descent = a list of labelled segments
[{path, label, anchor, labelPosition}] — multi-pitch's richer shape.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import psycopg
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import images

ROOT = Path(__file__).resolve().parents[2]
TOPO_DIR = ROOT / "db" / "uploads" / "topos" / "studio"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")

router = APIRouter()
TOPO_DIR.mkdir(parents=True, exist_ok=True)


def q(sql, args=()):
    with psycopg.connect(DSN, row_factory=psycopg.rows.dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else []


@router.get("/api/route/{rid}/topoinfo")
def route_topoinfo(rid: int):
    """Everything the route card's topo section needs: the topos available in
    this route's area (crag + sibling sectors), flagged with whether this
    route already has a line on them."""
    # the topo neighbourhood = the route's CRAG (its own area, or the parent
    # when the route sits in a sector) + that crag's sectors — never the whole
    # region, or every crag in the Mournes would offer its photos here
    area = q("""SELECT a.id,
                       CASE WHEN a.kind = 'sector' THEN coalesce(a.parent_id, a.id)
                            ELSE a.id END AS crag_id
                FROM route r JOIN area a ON a.id = r.area_id WHERE r.id = %s""", (rid,))
    if not area:
        raise HTTPException(404, "no such route")
    crag = area[0]["crag_id"]
    topos = q("""
        SELECT t.id, t.title, t.status, t.belay_size, m.uri, m.width_px, m.height_px,
               m.credit, m.license,
               (SELECT count(*) FROM topo_line l WHERE l.topo_id = t.id) AS lines,
               EXISTS (SELECT 1 FROM topo_line l WHERE l.topo_id = t.id AND l.route_id = %s) AS has_route
        FROM topo t JOIN media m ON m.id = t.media_id
        WHERE t.area_id = %s
           OR t.area_id IN (SELECT c.id FROM area c WHERE c.parent_id = %s)
        ORDER BY has_route DESC, t.id DESC""", (rid, crag, crag))
    return {"area_id": area[0]["id"], "topos": topos}


@router.get("/api/topo/{topo_id}")
def topo_detail(topo_id: int):
    tt = q("""SELECT t.id, t.title, t.status, t.belay_size, t.area_id,
                     m.uri, m.width_px, m.height_px, m.credit, m.license
              FROM topo t JOIN media m ON m.id = t.media_id WHERE t.id = %s""", (topo_id,))
    if not tt:
        raise HTTPException(404, "no such topo")
    lines = q("""SELECT l.route_id, r.name AS route_name, l.line, l.pitches, l.descent
                 FROM topo_line l JOIN route r ON r.id = l.route_id
                 WHERE l.topo_id = %s ORDER BY r.name""", (topo_id,))
    return {**tt[0], "lines": lines}


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
    dest = TOPO_DIR / f"a{area_id}-{int(time.time())}{ext}"
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
    uri = f"uploads/topos/studio/{dest.name}"
    media = q("""INSERT INTO media (area_id, kind, uri, width_px, height_px, credit, license, permission_note)
                 VALUES (%s, 'crag_photo', %s, %s, %s, %s, %s, nullif(%s, ''))
                 RETURNING id""", (area_id, uri, w, h, credit, license, permission_note))
    topo = q("""INSERT INTO topo (media_id, area_id, title)
                VALUES (%s, %s, coalesce(nullif(%s, ''), (SELECT name FROM area WHERE id = %s)))
                RETURNING id""", (media[0]["id"], area_id, title, area_id))
    return {"topo_id": topo[0]["id"]}


@router.delete("/api/topo/{topo_id}")
def delete_topo(topo_id: int):
    """Remove a bad/typo'd upload: the topo, its media row, and the files."""
    rows = q("""DELETE FROM topo t USING media m WHERE t.id = %s AND m.id = t.media_id
                RETURNING m.id AS media_id, m.uri""", (topo_id,))
    if not rows:
        raise HTTPException(404, "no such topo")
    q("DELETE FROM media WHERE id = %s RETURNING id", (rows[0]["media_id"],))
    f = ROOT / rows[0]["uri"]
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
    q("""UPDATE topo SET title = coalesce(%s, title), belay_size = coalesce(%s, belay_size),
         status = coalesce(%s, status), updated_at = now() WHERE id = %s RETURNING id""",
      (p.title, p.belay_size, p.status, topo_id))
    return {"ok": True}


class LineBody(BaseModel):
    line: list
    pitches: list | None = None
    descent: list | None = None


@router.put("/api/topo/{topo_id}/line/{route_id}")
def put_line(topo_id: int, route_id: int, body: LineBody):
    if len(body.line) < 2:
        raise HTTPException(400, "a line needs at least 2 points")
    q("""INSERT INTO topo_line (topo_id, route_id, line, pitches, descent)
         VALUES (%s, %s, %s, %s, %s)
         ON CONFLICT (topo_id, route_id) DO UPDATE
           SET line = excluded.line, pitches = excluded.pitches,
               descent = excluded.descent, updated_at = now()
         RETURNING topo_id""",
      (topo_id, route_id, json.dumps(body.line), json.dumps(body.pitches or []),
       json.dumps(body.descent) if body.descent else None))
    return {"ok": True}


@router.delete("/api/topo/{topo_id}/line/{route_id}")
def del_line(topo_id: int, route_id: int):
    q("DELETE FROM topo_line WHERE topo_id = %s AND route_id = %s RETURNING topo_id",
      (topo_id, route_id))
    return {"ok": True}

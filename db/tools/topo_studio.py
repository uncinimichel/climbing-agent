#!/usr/bin/env python3
"""Topo Studio — draw route lines over crag photos, stored as data (decision #37).

The drawing model is multi-pitch.com's proven one (its 38 topos import
losslessly via import_mp_topos.py): a media row is the photo, each route's
line/pitches/descent live in topo_line as pixel coordinates on the original
image, and rendering happens at draw time so every topo shares one visual
language. Rights are enforced at upload: no photo enters without credit +
license (only owned/permissioned photos may ever reach a booklet).

Run:  agent/.venv/bin/python db/tools/topo_studio.py        (from repo root)
then open http://localhost:8891

Localhost only, single editor, no auth — same stance as the Curation Studio
(curate.py, port 8890). Kept as a separate app/file so it can't collide with
in-flight Studio work; merge later if it earns it.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UI = HERE / "topo_ui.html"
UPLOAD_DIR = ROOT / "db" / "uploads"
TOPO_DIR = UPLOAD_DIR / "topos" / "studio"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")

app = FastAPI(title="Topo Studio")
TOPO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def q(sql, args=()):
    with psycopg.connect(DSN, row_factory=psycopg.rows.dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        if cur.description:
            return cur.fetchall()
        return []


@app.get("/", response_class=HTMLResponse)
def home():
    return UI.read_text()


@app.get("/api/areas")
def areas():
    """Crags/sectors that have routes, with route + topo counts."""
    return q("""
        SELECT a.id, a.name, a.kind,
               coalesce(p.name, '') AS parent,
               (SELECT count(*) FROM route r WHERE r.area_id = a.id
                   OR r.area_id IN (SELECT c.id FROM area c WHERE c.parent_id = a.id)) AS routes,
               (SELECT count(*) FROM topo t WHERE t.area_id = a.id
                   OR t.area_id IN (SELECT c.id FROM area c WHERE c.parent_id = a.id)) AS topos
        FROM area a LEFT JOIN area p ON p.id = a.parent_id
        WHERE a.kind IN ('crag', 'sector')
          AND EXISTS (SELECT 1 FROM route r WHERE r.area_id = a.id
                      OR r.area_id IN (SELECT c.id FROM area c WHERE c.parent_id = a.id))
        ORDER BY parent, a.name""")


@app.get("/api/area/{area_id}/routes")
def area_routes(area_id: int):
    return q("""
        SELECT r.id, r.name, r.original_grade AS grade, r.pitches_count, r.length_m,
               a.name AS sector
        FROM route r JOIN area a ON a.id = r.area_id
        WHERE r.area_id = %s OR a.parent_id = %s
        ORDER BY coalesce(r.left_right_index, 32767), r.name""", (area_id, area_id))


@app.get("/api/area/{area_id}/topos")
def area_topos(area_id: int):
    return q("""
        SELECT t.id, t.title, t.status, m.uri, m.width_px, m.height_px, m.credit, m.license,
               (SELECT count(*) FROM topo_line l WHERE l.topo_id = t.id) AS lines
        FROM topo t JOIN media m ON m.id = t.media_id
        WHERE t.area_id = %s OR t.area_id IN (SELECT c.id FROM area c WHERE c.parent_id = %s)
        ORDER BY t.id DESC""", (area_id, area_id))


@app.get("/api/topo/{topo_id}")
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


@app.get("/api/route/{route_id}/pitches")
def route_pitches(route_id: int):
    """Prefill for pitch markers: the route's real pitch grades/lengths."""
    return q("""SELECT number, original_grade AS grade, length_m
                FROM pitch WHERE route_id = %s ORDER BY number""", (route_id,))


@app.post("/api/media")
async def upload(file: UploadFile = File(...), area_id: int = Form(...),
                 credit: str = Form(...), license: str = Form("owned"),
                 permission_note: str = Form(""), title: str = Form(""),
                 width: int = Form(...), height: int = Form(...)):
    if license not in ("owned", "permission", "cc"):
        raise HTTPException(400, "license must be owned|permission|cc")
    if license != "owned" and not permission_note.strip():
        raise HTTPException(400, "non-owned photos need a permission_note (who granted it, when)")
    ext = (Path(file.filename or "x.jpg").suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "jpg/png/webp only")
    dest = TOPO_DIR / f"a{area_id}-{int(time.time())}{ext}"
    dest.write_bytes(await file.read())
    uri = f"uploads/topos/studio/{dest.name}"
    media = q("""INSERT INTO media (area_id, kind, uri, width_px, height_px, credit, license, permission_note)
                 VALUES (%s, 'crag_photo', %s, %s, %s, %s, %s, nullif(%s, ''))
                 RETURNING id""", (area_id, uri, width, height, credit, license, permission_note))
    topo = q("""INSERT INTO topo (media_id, area_id, title) VALUES (%s, %s, nullif(%s, ''))
                RETURNING id""", (media[0]["id"], area_id, title))
    return {"topo_id": topo[0]["id"]}


class TopoPatch(BaseModel):
    title: str | None = None
    belay_size: int | None = None
    status: str | None = None


@app.put("/api/topo/{topo_id}")
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


@app.put("/api/topo/{topo_id}/line/{route_id}")
def put_line(topo_id: int, route_id: int, body: LineBody):
    import json as _json
    if len(body.line) < 2:
        raise HTTPException(400, "a line needs at least 2 points")
    q("""INSERT INTO topo_line (topo_id, route_id, line, pitches, descent)
         VALUES (%s, %s, %s, %s, %s)
         ON CONFLICT (topo_id, route_id) DO UPDATE
           SET line = excluded.line, pitches = excluded.pitches,
               descent = excluded.descent, updated_at = now()
         RETURNING topo_id""",
      (topo_id, route_id, _json.dumps(body.line),
       _json.dumps(body.pitches or []),
       _json.dumps(body.descent) if body.descent else None))
    return {"ok": True}


@app.delete("/api/topo/{topo_id}/line/{route_id}")
def del_line(topo_id: int, route_id: int):
    q("DELETE FROM topo_line WHERE topo_id = %s AND route_id = %s RETURNING topo_id",
      (topo_id, route_id))
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8891)

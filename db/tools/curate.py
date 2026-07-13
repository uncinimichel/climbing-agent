#!/usr/bin/env python3
"""Curation Studio — the localhost admin that turns drafts into curated rows.

Postgres-first (decision #34): this app reads AND WRITES the climbing schema
directly; db/corpus.json is a derived export (build_corpus.py), not the store.
Governance (#32) is enforced here and by the DB constraint: publishing flips
tagged_by → 'human' (a publish row may never stay 'llm').

Run:  ../../agent/.venv/bin/uvicorn curate:app --port 8890   (from db/tools/)
  or: agent/.venv/bin/python db/tools/curate.py              (from repo root)

Localhost only, single editor, no auth (same stance as the #33 trips admin).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UI = HERE / "curate_ui.html"
ENRICH_CACHE = ROOT / "db" / "enrichment-cache.json"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")

app = FastAPI(title="Curation Studio")

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
TAG_TABLES = {
    "disciplines": ("route_discipline", "discipline_code"),
    "features": ("route_feature", "feature_code"),
    "character": ("route_character", "character_code"),
}


def db():
    return psycopg.connect(DSN, row_factory=dict_row, options="-c search_path=climbing,public")


def agg_tags(cur, rid: int) -> dict:
    tags = {}
    for key, (table, col) in TAG_TABLES.items():
        cur.execute(f"SELECT {col} AS c FROM {table} WHERE route_id = %s ORDER BY 1", (rid,))
        tags[key] = [x["c"] for x in cur.fetchall()]
    cur.execute("SELECT hazard_code AS c, evidence_span, source_url FROM route_hazard "
                "WHERE route_id = %s ORDER BY 1", (rid,))
    tags["hazards"] = [x["c"] for x in cur.fetchall()]
    return tags


@app.get("/", response_class=HTMLResponse)
def index():
    return UI.read_text()


@app.get("/api/enums")
def enums():
    with db() as conn, conn.cursor() as cur:
        out = {}
        for key, table in [("features", "feature"), ("character", "character"),
                           ("hazards", "hazard"), ("disciplines", "discipline"),
                           ("incline", "incline"), ("sun_window", "sun_window"),
                           ("protection", "protection_grade"), ("rock", "rock_type")]:
            cur.execute(f"SELECT code FROM {table} ORDER BY code")
            out[key] = [x["code"] for x in cur.fetchall()]
        out["protection_style"] = ["gear", "bolted", "mixed", "none"]
        out["belays"] = ["gear", "bolted", "mixed"]
        out["descent_method"] = ["walk-off", "abseil", "lower-off"]
        return out


@app.get("/api/queue")
def queue(status: str = "draft", q: str = "", crag: str = ""):
    where, params = ["r.status = %s"], [status]
    if q:
        where.append("(r.name ILIKE %s OR ar.path_tokens[3] ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    if crag:
        where.append("ar.path_tokens[3] = %s")
        params.append(crag)
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT r.id, r.name, r.status, r.tagged_by, r.needs_field_check,
                   r.original_grade, r.length_m, r.pitches_count, r.stars,
                   r.best_season IS NOT NULL AS has_season,
                   r.intro_html IS NOT NULL AS has_intro,
                   (SELECT count(*) FROM pitch p WHERE p.route_id = r.id) AS n_pitches_rows,
                   ar.path_tokens
            FROM route r JOIN area_resolved ar ON ar.id = r.area_id
            WHERE {' AND '.join(where)}
            ORDER BY ar.path_tokens, r.name""", params)
        rows = cur.fetchall()
        cur.execute("SELECT status, count(*) AS n FROM route GROUP BY 1")
        counts = {x["status"]: x["n"] for x in cur.fetchall()}
        cur.execute("SELECT count(*) AS n FROM route WHERE needs_field_check")
        counts["field_check"] = cur.fetchone()["n"]
    return {"rows": rows, "counts": counts}


@app.get("/api/route/{rid}")
def route_detail(rid: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT r.*, ar.path_tokens, ar.eff_rock_code, ar.eff_aspect, ar.eff_grade_context,
                   ST_Y(r.geom::geometry) AS lat, ST_X(r.geom::geometry) AS lon
            FROM route_resolved r JOIN area_resolved ar ON ar.id = r.area_id
            WHERE r.id = %s""", (rid,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
        r.pop("geom", None)
        r["tags"] = agg_tags(cur, rid)
        cur.execute("SELECT number, length_m, grade_system_code, original_grade, description "
                    "FROM pitch WHERE route_id = %s ORDER BY number", (rid,))
        r["pitch_rows"] = cur.fetchall()
        cur.execute("SELECT source_id, external_id, url FROM external_ref "
                    "WHERE entity_type = 'route' AND entity_id = %s", (rid,))
        r["refs"] = cur.fetchall()
        cur.execute("SELECT month, rainy_days, temp_high, temp_low FROM route_climatology "
                    "WHERE route_id = %s ORDER BY month", (rid,))
        r["climatology"] = cur.fetchall()
    # AI receipt from the enrichment cache (keyed mp-<id>)
    r["receipt"] = None
    mp = next((x for x in r["refs"] if x["source_id"] == "multipitch"), None)
    if mp and ENRICH_CACHE.exists():
        r["receipt"] = json.loads(ENRICH_CACHE.read_text()).get(f"mp-{mp['external_id']}")
    return r


@app.patch("/api/route/{rid}")
def patch_route(rid: int, body: dict):
    fields = {k: v for k, v in body.items() if k in PATCHABLE}
    tags = body.get("tags") or {}
    if not fields and not tags:
        raise HTTPException(400, "nothing patchable in body")
    with db() as conn, conn.cursor() as cur:
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            cur.execute(f"UPDATE route SET {sets}, last_update = now() WHERE id = %s RETURNING id",
                        [*fields.values(), rid])
            if not cur.fetchone():
                raise HTTPException(404)
        for key, values in tags.items():
            if key in TAG_TABLES:
                table, col = TAG_TABLES[key]
                cur.execute(f"DELETE FROM {table} WHERE route_id = %s", (rid,))
                for v in values:
                    cur.execute(f"INSERT INTO {table} (route_id, {col}) VALUES (%s, %s) "
                                "ON CONFLICT DO NOTHING", (rid, v))
            elif key == "hazards":
                cur.execute("DELETE FROM route_hazard WHERE route_id = %s", (rid,))
                for v in values:
                    cur.execute(
                        "INSERT INTO route_hazard (route_id, hazard_code, evidence_span) "
                        "VALUES (%s, %s, 'curator verified (Curation Studio)') "
                        "ON CONFLICT DO NOTHING", (rid, v))
        conn.commit()
    return {"ok": True}


@app.put("/api/route/{rid}/pitches")
def put_pitches(rid: int, body: list[dict]):
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM pitch WHERE route_id = %s", (rid,))
        for p in body:
            if not p.get("number"):
                continue
            cur.execute(
                """INSERT INTO pitch (route_id, number, length_m, grade_system_code,
                                      original_grade, description)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (rid, p["number"], p.get("length_m"), p.get("grade_system_code"),
                 p.get("original_grade"), p.get("description")))
        cur.execute("UPDATE route SET pitches_count = %s, last_update = now() WHERE id = %s",
                    (len(body) or None, rid))
        conn.commit()
    return {"ok": True, "pitches": len(body)}


@app.post("/api/route/{rid}/publish")
def publish(rid: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, original_grade FROM route WHERE id = %s", (rid,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
        if not r["original_grade"]:
            raise HTTPException(422, "no grade — a curated route needs one")
        cur.execute("""UPDATE route SET status = 'publish', tagged_by = 'human',
                       curated_at = now(), needs_field_check = false, last_update = now()
                       WHERE id = %s""", (rid,))
        conn.commit()
    return {"ok": True, "status": "publish"}


@app.post("/api/route/{rid}/status/{new}")
def set_status(rid: int, new: str):
    if new not in ("draft", "quarantined"):
        raise HTTPException(422, "status must be draft or quarantined")
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE route SET status = %s, last_update = now() WHERE id = %s RETURNING id",
                    (new, rid))
        if not cur.fetchone():
            raise HTTPException(404)
        conn.commit()
    return {"ok": True, "status": new}


@app.post("/api/route/{rid}/fieldcheck")
def fieldcheck(rid: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE route SET needs_field_check = NOT needs_field_check,
                       last_update = now() WHERE id = %s RETURNING needs_field_check""", (rid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404)
        conn.commit()
    return {"ok": True, "needs_field_check": row["needs_field_check"]}


@app.post("/api/export")
def export():
    """Regenerate the committed corpus.json export from Postgres."""
    p = subprocess.run([sys.executable, str(HERE / "build_corpus.py")],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise HTTPException(500, p.stderr[-800:])
    return {"ok": True, "out": p.stdout.strip()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8890)

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
import re
import subprocess
import sys
import threading
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
TAG_TABLES = {
    "disciplines": ("route_discipline", "discipline_code"),
    "features": ("route_feature", "feature_code"),
    "character": ("route_character", "character_code"),
}

# Studio-managed vocabularies (decision #35): family → (table, editable meta columns,
# usage-count SQL). Adding/editing values here IS the taxonomy write path; every write
# re-exports 105_taxonomy_extensions.sql + taxonomy-values.json via export_taxonomy.py.
TAXONOMY = {
    "discipline": ("discipline", ["meaning"],
                   "SELECT count(*) FROM route_discipline j WHERE j.discipline_code = t.code"),
    "feature": ("feature", ["meaning"],
                "SELECT count(*) FROM route_feature j WHERE j.feature_code = t.code"),
    "character": ("character", ["meaning"],
                  "SELECT count(*) FROM route_character j WHERE j.character_code = t.code"),
    "hazard": ("hazard", ["kind", "meaning", "safety_critical", "feeds"],
               "SELECT count(*) FROM route_hazard j WHERE j.hazard_code = t.code"),
    "rock": ("rock_type", ["friction_dry", "seeps", "fragile_when_wet", "notes"],
             "SELECT (SELECT count(*) FROM route r WHERE r.rock_code = t.code) + "
             "(SELECT count(*) FROM area a WHERE a.rock_code = t.code)"),
    "sun_window": ("sun_window", ["meaning"],
                   "SELECT count(*) FROM route r WHERE r.sun_window_code = t.code"),
    "protection": ("protection_grade", ["meaning", "sort_order"],
                   "SELECT count(*) FROM route r WHERE r.protection_code = t.code"),
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
    """Regenerate 105_taxonomy_extensions.sql + taxonomy-values.json (best effort,
    fire-and-forget — the write already committed; the files just mirror it)."""
    def run():
        try:
            subprocess.run([sys.executable, str(HERE / "export_taxonomy.py")],
                           capture_output=True, timeout=60)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


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
                           ("rock", "rock_type")]:
            cur.execute(f"SELECT code FROM {table} ORDER BY code")
            out[key] = [x["code"] for x in cur.fetchall()]
        # meanings ride along where the UI shows them (Michel: PG/PG-13 are not
        # guesses — Erickson's G/PG/PG-13/R/X seriousness scale; say what each means)
        cur.execute("SELECT code, meaning FROM protection_grade ORDER BY sort_order")
        out["protection"] = cur.fetchall()
        cur.execute("SELECT code, name, region FROM grade_system ORDER BY code")
        out["grade_systems"] = cur.fetchall()
        cur.execute("SELECT grade_system_code AS sys, original_grade AS g "
                    "FROM grade_conversion ORDER BY grade_system_code, data_grade")
        ladder = {}
        for x in cur.fetchall():
            ladder.setdefault(x["sys"], []).append(x["g"])
        out["grade_ladder"] = ladder
        out["grade_patterns"] = GRADE_PATTERNS
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
        cur.execute("""SELECT id, label, ord, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
                       FROM route_parking WHERE route_id = %s ORDER BY ord, id""", (rid,))
        r["parkings"] = cur.fetchall()
        r["grade_warning"] = grade_problem(r.get("grade_system_code"), r.get("original_grade"))
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
    if mp:
        r["receipt"] = enrich_cache().get(f"mp-{mp['external_id']}")
    return r


@app.patch("/api/route/{rid}")
def patch_route(rid: int, body: dict):
    fields = {k: v for k, v in body.items() if k in PATCHABLE}
    tags = body.get("tags") or {}
    if not fields and not tags:
        raise HTTPException(400, "nothing patchable in body")
    warning = None
    with db() as conn, conn.cursor() as cur:
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            cur.execute(f"UPDATE route SET {sets}, last_update = now() WHERE id = %s RETURNING id",
                        [*fields.values(), rid])
            if not cur.fetchone():
                raise HTTPException(404)
        if {"original_grade", "grade_system_code"} & set(fields):
            cur.execute("SELECT grade_system_code, original_grade FROM route WHERE id = %s", (rid,))
            g = cur.fetchone()
            warning = grade_problem(g["grade_system_code"], g["original_grade"])
        for key, values in tags.items():
            if key in TAG_TABLES:
                table, col = TAG_TABLES[key]
                cur.execute(f"DELETE FROM {table} WHERE route_id = %s", (rid,))
                for v in values:
                    cur.execute(f"INSERT INTO {table} (route_id, {col}) VALUES (%s, %s) "
                                "ON CONFLICT DO NOTHING", (rid, v))
            elif key == "hazards":
                # keep the real evidence of hazards that stay; only NEW codes get
                # the curator stamp — tag saves must never erase source provenance
                cur.execute("SELECT hazard_code, evidence_span, source_url "
                            "FROM route_hazard WHERE route_id = %s", (rid,))
                prior = {x["hazard_code"]: x for x in cur.fetchall()}
                cur.execute("DELETE FROM route_hazard WHERE route_id = %s", (rid,))
                for v in values:
                    old = prior.get(v)
                    cur.execute(
                        "INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (rid, v,
                         (old and old["evidence_span"]) or "curator verified (Curation Studio)",
                         old and old["source_url"]))
        conn.commit()
    return {"ok": True, "gradeWarning": warning}


@app.put("/api/route/{rid}/parkings")
def put_parkings(rid: int, body: list[dict]):
    """Replace the route's parking spots: [{label, lat, lon}] — multiple pins, ordered."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM route_parking WHERE route_id = %s", (rid,))
        for i, pk in enumerate(body, 1):
            if pk.get("lat") is None or pk.get("lon") is None:
                continue
            cur.execute(
                """INSERT INTO route_parking (route_id, label, geom, ord)
                   VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)""",
                (rid, (pk.get("label") or "parking").strip() or "parking",
                 float(pk["lon"]), float(pk["lat"]), i))
        cur.execute("UPDATE route SET last_update = now() WHERE id = %s", (rid,))
        conn.commit()
    return {"ok": True, "parkings": len(body)}


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
        cur.execute("SELECT name, original_grade, grade_system_code, needs_field_check "
                    "FROM route WHERE id = %s", (rid,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
        problem = grade_problem(r["grade_system_code"], r["original_grade"])
        if problem:
            raise HTTPException(422, f"grade check: {problem}")
        if r["needs_field_check"]:
            raise HTTPException(422, "flagged 🥾 needs field check — clear the flag "
                                     "(⌘F) once verified, then publish")
        cur.execute("""UPDATE route SET status = 'publish', tagged_by = 'human',
                       curated_at = now(), last_update = now()
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


@app.get("/api/taxonomy")
def taxonomy():
    out = {}
    with db() as conn, conn.cursor() as cur:
        for fam, (table, cols, usage_q) in TAXONOMY.items():
            cur.execute(f"SELECT code, {', '.join(cols)}, ({usage_q}) AS usage "
                        f"FROM {table} t ORDER BY code")
            out[fam] = cur.fetchall()
    return out


@app.post("/api/taxonomy/{family}")
def taxonomy_add(family: str, body: dict):
    if family not in TAXONOMY:
        raise HTTPException(404, f"unknown family {family}")
    table, cols, _ = TAXONOMY[family]
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
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE code = %s", (code,))
        if cur.fetchone():
            raise HTTPException(409, f"{code} already exists in {family}")
        cur.execute(
            f"INSERT INTO {table} (code{''.join(', ' + c for c in meta)}) "
            f"VALUES (%s{', %s' * len(meta)})", [code, *meta.values()])
        conn.commit()
    resync_taxonomy_files()
    return {"ok": True, "family": family, "code": code}


@app.patch("/api/taxonomy/{family}/{code}")
def taxonomy_edit(family: str, code: str, body: dict):
    if family not in TAXONOMY:
        raise HTTPException(404, f"unknown family {family}")
    table, cols, _ = TAXONOMY[family]
    meta = {c: body[c] for c in cols if c in body}
    if not meta:
        raise HTTPException(400, "nothing editable in body")
    with db() as conn, conn.cursor() as cur:
        sets = ", ".join(f"{c} = %s" for c in meta)
        cur.execute(f"UPDATE {table} SET {sets} WHERE code = %s RETURNING code",
                    [*meta.values(), code])
        if not cur.fetchone():
            raise HTTPException(404, f"{code} not in {family}")
        conn.commit()
    resync_taxonomy_files()
    return {"ok": True}


@app.delete("/api/taxonomy/{family}/{code}")
def taxonomy_delete(family: str, code: str):
    if family not in TAXONOMY:
        raise HTTPException(404, f"unknown family {family}")
    table, _, usage_q = TAXONOMY[family]
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT ({usage_q}) AS n FROM {table} t WHERE t.code = %s", (code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"{code} not in {family}")
        if row["n"]:
            raise HTTPException(409, f"{code} is used by {row['n']} routes — retag them first")
        cur.execute(f"DELETE FROM {table} WHERE code = %s", (code,))
        conn.commit()
    resync_taxonomy_files()
    return {"ok": True}


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

#!/usr/bin/env python3
"""Export db/corpus.json from Postgres — the committed backup of the corpus DB.

Postgres-first (decision #34, supersedes this file's original seed-merging role):
the climbing schema is the WORKING STORE — the Curation Studio (curate.py) edits it,
the crawler inserts into it, ingest_corpus.py restores into it. This script is the
other direction: a faithful, git-diffable EXPORT of every area and route (draft,
publish and quarantined alike), so

  - corpus.json stays the committed backup (repo-as-database ethos, #2) —
    `apply.sh && ingest_corpus.py` rebuilds the DB from it losslessly,
  - the Corpus Inspector and the trip pipeline (#27 pending switch) read one file,
  - every curation session shows up as a reviewable git diff.

Governance fields (#32) ride along: status · source · taggedBy · tagProv ·
curationNotes · needsFieldCheck. Prose rides along too: intro / approach /
pitchInfo + structured pitches[].

Dependency-free (stdlib; talks to Postgres via psql / docker exec):
    python3 db/tools/build_corpus.py
"""
import json
import re
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "db" / "corpus.json"
# A deployed copy under knowledge/ (the only tree GitHub Pages serves), so the
# corpus is fetchable by the Corpus Inspector and clickable from the data map.
DEPLOY_OUT = ROOT / "knowledge" / "data" / "corpus.json"
DB_DSN = "postgresql://climbing:climbing@localhost:5432/climbing"
DB_CONTAINER = "climbing-db"          # docker exec fallback if no local psql
TAXONOMY_REF = "knowledge/data/tag-spec.json"


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


AREAS_Q = r"""
SELECT json_agg(a ORDER BY a.path_tokens) FROM (
  SELECT ar.id AS pg_id, ar.name, ar.kind, ar.path_tokens,
         ar.eff_grade_context, a.grade_context, a.rock_code, a.aspect,
         ST_Y(a.geom::geometry) AS lat, ST_X(a.geom::geometry) AS lon,
         p.name AS parent_name
  FROM area_resolved ar
  JOIN area a ON a.id = ar.id
  LEFT JOIN area p ON p.id = ar.parent_id
) a;"""

ROUTES_Q = r"""
SELECT json_agg(r ORDER BY r.path_tokens, r.name) FROM (
  SELECT rr.id AS pg_id, rr.name, rr.status, rr.tagged_by, rr.tag_prov,
    rr.curation_notes, rr.needs_field_check, rr.curated_at, rr.path_tokens,
    rr.length_m, rr.pitches_count, rr.incline_code, rr.data_grade,
    rr.grade_system_code, rr.original_grade, rr.trad_grade, rr.tech_grade,
    rr.protection_code, rr.protection_style, rr.belays, rr.rack, rr.rope,
    rr.approach_time_min, rr.approach_difficulty,
    rr.descent_method, rr.descent_abseils, rr.descent_notes,
    rr.elevation_m, rr.sun_window_code, rr.wind_exposed, rr.best_season, rr.stars,
    rr.intro_html, rr.approach_html, rr.pitch_info_html,
    (SELECT name FROM area WHERE id = rr.area_id) AS area_name,
    ST_Y(rr.geom::geometry) AS lat, ST_X(rr.geom::geometry) AS lon,
    ST_Y(rr.parking::geometry) AS parking_lat, ST_X(rr.parking::geometry) AS parking_lon,
    (SELECT array_agg(discipline_code ORDER BY discipline_code) FROM route_discipline d WHERE d.route_id = rr.id) AS disciplines,
    (SELECT array_agg(feature_code ORDER BY feature_code) FROM route_feature f WHERE f.route_id = rr.id) AS features,
    (SELECT array_agg(character_code ORDER BY character_code) FROM route_character c WHERE c.route_id = rr.id) AS "character",
    (SELECT array_agg(hazard_code ORDER BY hazard_code) FROM route_hazard h WHERE h.route_id = rr.id) AS hazards,
    (SELECT json_agg(json_build_object('number', number, 'length', length_m,
        'gradeSys', grade_system_code, 'grade', original_grade,
        'description', description) ORDER BY number)
        FROM pitch p WHERE p.route_id = rr.id) AS pitch_rows,
    (SELECT json_agg(json_build_object('month', month, 'rainyDays', rainy_days,
        'tempHigh', temp_high, 'tempLow', temp_low) ORDER BY month)
        FROM route_climatology w WHERE w.route_id = rr.id) AS climatology,
    (SELECT json_agg(json_build_object('source', source_id, 'id', external_id, 'url', url))
        FROM external_ref e WHERE e.entity_type = 'route' AND e.entity_id = rr.id) AS refs
  FROM route_resolved rr
) r;"""


def pg_json(query: str):
    for cmd in (["psql", DB_DSN, "-tAc", query],
                ["docker", "exec", DB_CONTAINER, "psql", "-U", "climbing",
                 "-d", "climbing", "-tAc", query]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout.strip())
        except Exception:
            continue
    return None


def export_area(a: dict) -> dict:
    toks = a["path_tokens"] or [a["name"]]
    return {
        "id": slug(a["name"]), "name": a["name"], "kind": a["kind"],
        "parent": slug(a["parent_name"]) if a.get("parent_name") else None,
        "country": toks[0] if len(toks) > 1 else None,
        "region": toks[1] if len(toks) > 2 else None,
        "geoLocation": [round(a["lat"], 4), round(a["lon"], 4)] if a.get("lat") is not None else None,
        "rock": a.get("rock_code"), "aspect": a.get("aspect"),
        "gradeContext": a.get("grade_context"),
        "status": "draft", "source": "postgres",
    }


def export_route(r: dict) -> dict:
    mp_ref = next((x for x in (r.get("refs") or []) if x["source"] == "multipitch"), None)
    rid = f"mp-{mp_ref['id']}" if mp_ref else r["pg_id"]
    out = {
        "id": rid, "pgId": r["pg_id"], "area": slug(r["area_name"]), "name": r["name"],
        "status": r["status"], "taggedBy": r["tagged_by"],
        "source": "curated" if r["tagged_by"] == "human" else
                  ("multi-pitch.com" if mp_ref else "crawler"),
        "dataGrade": r.get("data_grade"),
        "originalGrade": r.get("original_grade"), "gradeSys": r.get("grade_system_code"),
        "tradGrade": r.get("trad_grade"), "techGrade": r.get("tech_grade"),
        "length": r.get("length_m"), "pitches": r.get("pitches_count"),
        "incline": r.get("incline_code"),
        "protection": r.get("protection_code"), "protectionStyle": r.get("protection_style"),
        "belays": r.get("belays"), "rack": r.get("rack"), "rope": r.get("rope"),
        "approachTime": r.get("approach_time_min"),
        "approachDifficulty": r.get("approach_difficulty"),
        "descentMethod": r.get("descent_method"), "descentNotes": r.get("descent_notes"),
        "elevation": r.get("elevation_m"), "sunWindow": r.get("sun_window_code"),
        "bestSeason": r.get("best_season"), "stars": r.get("stars"),
        "disciplines": r.get("disciplines") or [], "features": r.get("features") or [],
        "character": r.get("character") or [], "hazards": r.get("hazards") or [],
        "climatology": r.get("climatology") or [],
        "description": r.get("intro_html"), "approach": r.get("approach_html"),
        "pitchInfo": r.get("pitch_info_html"), "pitchRows": r.get("pitch_rows") or [],
        "geoLocation": [round(r["lat"], 4), round(r["lon"], 4)] if r.get("lat") is not None else None,
        "parking": [round(r["parking_lat"], 6), round(r["parking_lon"], 6)] if r.get("parking_lat") is not None else None,
        "refs": r.get("refs") or [],
    }
    if r.get("tag_prov"):
        out["tagProv"] = r["tag_prov"]
    if r.get("curation_notes"):
        out["curationNotes"] = r["curation_notes"]
    if r.get("needs_field_check"):
        out["needsFieldCheck"] = True
    if r.get("curated_at"):
        out["curatedAt"] = str(r["curated_at"])[:10]
    return out


def build():
    areas_raw = pg_json(AREAS_Q)
    routes_raw = pg_json(ROUTES_Q)
    if not areas_raw or not routes_raw:
        sys.exit("[error] Postgres unreachable (colima start && cd db && docker-compose up -d) "
                 "— corpus.json left untouched (it IS the backup)")

    areas = [export_area(a) for a in areas_raw]
    routes = [export_route(r) for r in routes_raw]

    # area status: publish if a human-published route hangs under it — mirrors
    # the old curated-area semantics
    pub_chains = set()
    for r, raw in zip(routes, routes_raw):
        if r["status"] == "publish":
            for tok in raw["path_tokens"] or []:
                pub_chains.add(slug(tok))
    for a in areas:
        if a["id"] in pub_chains:
            a["status"], a["source"] = "publish", "curated"

    pub_a = sum(a["status"] == "publish" for a in areas)
    by_status = {}
    for r in routes:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    llm_r = sum(r["taggedBy"] == "llm" for r in routes)
    fc = sum(1 for r in routes if r.get("needsFieldCheck"))

    corpus = {
        "schemaVersion": "2.0",
        "generated": date.today().isoformat(),
        "note": "EXPORT of the Postgres corpus DB (decision #34: Postgres-first — edit via "
                "the Curation Studio, not this file; restore via db/tools/ingest_corpus.py). "
                "Governance (#32): suggestions/ranking may only use status:publish + "
                "taggedBy:human rows.",
        "taxonomyRef": TAXONOMY_REF,
        "counts": {"areas": len(areas), "areasCurated": pub_a,
                   "routes": len(routes),
                   "routesCurated": by_status.get("publish", 0),
                   "routesSeeded": by_status.get("draft", 0),
                   "routesQuarantined": by_status.get("quarantined", 0),
                   "routesLlmTagged": llm_r, "routesFieldCheck": fc},
        "areas": areas,
        "routes": routes,
    }
    payload = json.dumps(corpus, ensure_ascii=False, indent=2, default=str) + "\n"
    OUT.write_text(payload)
    DEPLOY_OUT.write_text(payload)          # served copy for the site
    print(f"exported {OUT.relative_to(ROOT)} + {DEPLOY_OUT.relative_to(ROOT)} — "
          f"{len(areas)} areas ({pub_a} curated), {len(routes)} routes "
          f"({by_status.get('publish', 0)} curated, {by_status.get('draft', 0)} draft, "
          f"{by_status.get('quarantined', 0)} quarantined, {llm_r} llm-tagged, {fc} field-check)")


if __name__ == "__main__":
    build()

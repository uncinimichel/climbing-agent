#!/usr/bin/env python3
"""Export the COMPLETE corpus from Postgres into the JSON record (decision #39:
JSON in git+S3 is the source of truth; databases are disposable tools).

Layout written under corpus/record/:
    taxonomies.json        every vocabulary with its metadata (enums-with-meaning)
    grades.json            grade systems, ladders, conversions
    sources.json           the source registry
    areas.json             the area tree (all columns, parent by id)
    routes/NNNN-slug.json  one self-contained document per route: every route
                           column + tags(+hazard evidence) + pitches +
                           guidebooks + references + parkings + climatology +
                           external refs + first ascents + provenance
    topos.json             photos + drawn lines (media/topo/topo_line),
                           keyed naturally (uri, route name+area)
    crawl-frontier.json    ARCHIVE ONLY — the crawler's work queue is
                           disposable runtime state, captured so nothing is
                           lost at the Postgres retirement, never authoritative

Deterministic output (sorted keys, stable ordering) so git diffs are honest.
Run:  agent/.venv/bin/python corpus/tools/export_record.py
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
REC = ROOT / "corpus" / "record"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")

TAX_TABLES = ["discipline", "feature", "character", "hazard", "rock_type",
              "sun_window", "protection_grade", "incline", "commitment_grade",
              "ascent_style", "source"]


def jsonable(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, memoryview):
        return v.hex()
    return v


def rows(cur, sql, args=()):
    cur.execute(sql, args)
    return [{k: jsonable(v) for k, v in r.items()} for r in cur.fetchall()]


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return path


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "route").lower()).strip("-")[:48]


def main():
    with psycopg.connect(DSN, row_factory=dict_row,
                         options="-c search_path=climbing,public") as conn, conn.cursor() as cur:
        # taxonomies (each table's full metadata) --------------------------------
        tax = {t: rows(cur, f"SELECT * FROM {t} ORDER BY 1") for t in TAX_TABLES}
        dump(REC / "taxonomies.json", {"schema": 1, "taxonomies": tax})

        grades = {
            "systems": rows(cur, "SELECT * FROM grade_system ORDER BY code"),
            "conversions": rows(cur, "SELECT * FROM grade_conversion ORDER BY 1, 2"),
        }
        dump(REC / "grades.json", {"schema": 1, **grades})

        areas = rows(cur, "SELECT *, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
                          "FROM area ORDER BY id")
        for a in areas:
            a.pop("geom", None)
        arefs = rows(cur, "SELECT * FROM area_reference ORDER BY id")
        dump(REC / "areas.json", {"schema": 1, "areas": areas, "references": arefs})

        # routes: one self-contained document each -------------------------------
        routes = rows(cur, "SELECT *, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
                           "FROM route ORDER BY id")
        rdir = REC / "routes"
        if rdir.exists():
            for old in rdir.glob("*.json"):
                old.unlink()
        for r in routes:
            r.pop("geom", None)
            rid = r["id"]
            r["tags"] = {
                "disciplines": [x["discipline_code"] for x in rows(cur,
                    "SELECT discipline_code FROM route_discipline WHERE route_id=%s ORDER BY 1", (rid,))],
                "features": [x["feature_code"] for x in rows(cur,
                    "SELECT feature_code FROM route_feature WHERE route_id=%s ORDER BY 1", (rid,))],
                "character": [x["character_code"] for x in rows(cur,
                    "SELECT character_code FROM route_character WHERE route_id=%s ORDER BY 1", (rid,))],
            }
            r["hazards"] = rows(cur, "SELECT hazard_code, evidence_span, source_url "
                                     "FROM route_hazard WHERE route_id=%s ORDER BY 1", (rid,))
            r["pitches"] = rows(cur, "SELECT number, length_m, original_grade, grade_system_code, "
                                     "description, bolts_count FROM pitch WHERE route_id=%s ORDER BY number", (rid,))
            r["guidebooks"] = rows(cur, """SELECT g.*, rg.page FROM route_guidebook rg
                                           JOIN guidebook g ON g.id = rg.guidebook_id
                                           WHERE rg.route_id=%s ORDER BY g.title""", (rid,))
            r["references"] = rows(cur, "SELECT * FROM route_reference WHERE route_id=%s ORDER BY id", (rid,))
            r["parkings"] = rows(cur, "SELECT * FROM route_parking WHERE route_id=%s ORDER BY id", (rid,))
            r["climatology"] = rows(cur, "SELECT month, rainy_days, temp_high, temp_low "
                                         "FROM route_climatology WHERE route_id=%s ORDER BY month", (rid,))
            r["external_refs"] = rows(cur, "SELECT source_id, external_id, url FROM external_ref "
                                           "WHERE entity_type='route' AND entity_id=%s ORDER BY source_id", (rid,))
            r["first_ascents"] = rows(cur, "SELECT * FROM first_ascent WHERE route_id=%s", (rid,))
            r["provenance"] = rows(cur, "SELECT field, source_id, source_url, span, confidence "
                                        "FROM provenance WHERE route_id=%s ORDER BY id", (rid,))
            dump(rdir / f"{rid:04d}-{slug(r['name'])}.json", r)

        # area external refs ride with areas? external_ref also holds area rows --
        aext = rows(cur, "SELECT * FROM external_ref WHERE entity_type <> 'route' "
                         "ORDER BY entity_type, entity_id, source_id")
        if aext:
            dump(REC / "external-refs-nonroute.json", {"schema": 1, "refs": aext})

        # crawl frontier: archived, never authoritative --------------------------
        cf = rows(cur, "SELECT * FROM crawl_frontier ORDER BY id")
        dump(REC / "crawl-frontier.json",
             {"schema": 1, "note": "ARCHIVE of disposable crawler state at Postgres retirement",
              "frontier": cf})

    # topos.json via the existing exporter (natural keys, includes credits) ------
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).with_name("export_topos.py"))], check=True)
    (REC / "topos.json").write_text((ROOT / "corpus" / "topos.json").read_text())

    n = len(list((REC / "routes").glob("*.json")))
    total_kb = sum(f.stat().st_size for f in REC.rglob("*.json")) // 1024
    print(f"record written: {n} route files + taxonomies/grades/areas/topos ({total_kb}KB total)")


if __name__ == "__main__":
    main()

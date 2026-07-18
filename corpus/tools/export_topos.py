#!/usr/bin/env python3
"""Export the topo layer (media / topo / topo_line) to db/topos.json.

corpus.json (build_corpus.py) carries routes/areas/pitches/taxonomies but not
the drawn topos; together the two files are the COMPLETE record (decision #39:
the record lives as JSON in S3, Postgres is a disposable local working copy).
Keyed by natural identifiers (media uri, route name+area) so import is
idempotent and survives databases whose serial ids differ.

Run:  agent/.venv/bin/python corpus/tools/export_topos.py
"""
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "corpus" / "topos.json"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT t.id AS topo_id, t.title, t.status, t.belay_size,
                   a.name AS area_name,
                   m.uri, m.kind, m.width_px, m.height_px, m.credit, m.license,
                   m.permission_note, m.taken_at
            FROM topo t
            JOIN media m ON m.id = t.media_id
            LEFT JOIN area a ON a.id = t.area_id
            ORDER BY t.id""")
        topos = cur.fetchall()
        out = []
        for t in topos:
            cur.execute("""
                SELECT r.name AS route_name, ra.name AS route_area,
                       l.line, l.pitches, l.descent, l.source_id
                FROM topo_line l
                JOIN route r ON r.id = l.route_id
                LEFT JOIN area ra ON ra.id = r.area_id
                WHERE l.topo_id = %s ORDER BY r.name""", (t["topo_id"],))
            lines = cur.fetchall()
            rec = {k: v for k, v in t.items() if k != "topo_id"}
            rec["taken_at"] = str(rec["taken_at"]) if rec.get("taken_at") else None
            rec["lines"] = lines
            out.append(rec)
    OUT.write_text(json.dumps({"schema": 1, "topos": out}, ensure_ascii=False, indent=1))
    n_lines = sum(len(t["lines"]) for t in out)
    print(f"wrote {OUT.name}: {len(out)} topos, {n_lines} route lines "
          f"({OUT.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    sys.exit(main())

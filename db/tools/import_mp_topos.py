#!/usr/bin/env python3
"""Seed the topo layer from multi-pitch.com's existing hand-drawn topos.

Dan's site already holds ~38 complete topoData records (photo + route line +
per-pitch belay/label positions + descent path) — all owned content. This
copies each base photo into db/uploads/topos/mp/ and lands the geometry as
media / topo / topo_line rows, matching routes via external_ref
(source 'multipitch'). Re-runnable: a photo already imported is skipped.

Run:  agent/.venv/bin/python db/tools/import_mp_topos.py
"""
import json
import os
import shutil
import struct
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MP_SITE = Path(os.environ.get("MP_SITE", Path.home() / "dev/multi-pitch/website"))
UPLOADS = ROOT / "db" / "uploads" / "topos" / "mp"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")


def image_size(path: Path):
    """(width, height) for JPEG/PNG without PIL — stdlib header parsing."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    if data[:2] == b"\xff\xd8":                    # JPEG: scan for a SOF marker
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def main():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    climbs_dir = MP_SITE / "data" / "climbs"
    done = skipped = missing_route = missing_img = 0
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        for f in sorted(climbs_dir.glob("*.json")):
            d = json.loads(f.read_text())
            td = d.get("topoData") or {}
            if not (td.get("image") and td.get("route")):
                continue
            climb_id = f.stem
            cur.execute("""SELECT r.id, r.area_id, r.name FROM external_ref x
                           JOIN route r ON r.id = x.entity_id
                           WHERE x.entity_type = 'route' AND x.source_id = 'multipitch'
                             AND x.external_id = %s""", (climb_id,))
            row = cur.fetchone()
            if not row:
                print(f"  [skip] climb {climb_id}: no multipitch external_ref match")
                missing_route += 1
                continue
            src = MP_SITE / td["image"].lstrip("/")
            if not src.exists():
                print(f"  [skip] climb {climb_id}: image missing {src}")
                missing_img += 1
                continue
            dest = UPLOADS / f"{climb_id}-{src.name}"
            uri = f"uploads/topos/mp/{dest.name}"
            cur.execute("SELECT t.id FROM topo t JOIN media m ON m.id = t.media_id WHERE m.uri = %s", (uri,))
            if cur.fetchone():
                skipped += 1
                continue
            size = image_size(src)
            if not size:
                print(f"  [skip] climb {climb_id}: can't read dimensions of {src.name}")
                missing_img += 1
                continue
            shutil.copy2(src, dest)
            cur.execute("""INSERT INTO media (area_id, kind, uri, width_px, height_px, credit, license)
                           VALUES (%s, 'crag_photo', %s, %s, %s, 'Dan Knight / multi-pitch.com', 'owned')
                           RETURNING id""", (row["area_id"], uri, size[0], size[1]))
            media_id = cur.fetchone()["id"]
            cur.execute("""INSERT INTO topo (media_id, area_id, title, belay_size, status)
                           VALUES (%s, %s, %s, %s, 'publish') RETURNING id""",
                        (media_id, row["area_id"], td.get("title") or row["name"],
                         td.get("belaySize") or 24))
            topo_id = cur.fetchone()["id"]
            cur.execute("""INSERT INTO topo_line (topo_id, route_id, line, pitches, descent, source_id)
                           VALUES (%s, %s, %s, %s, %s, 'multipitch')""",
                        (topo_id, row["id"], json.dumps(td["route"]),
                         json.dumps(td.get("pitches") or []),
                         json.dumps(td.get("decent")) if td.get("decent") else None))
            done += 1
            print(f"  [ok]   climb {climb_id}: '{row['name']}' → topo {topo_id} ({size[0]}x{size[1]})")
    print(f"imported {done}, already-there {skipped}, no-route-match {missing_route}, no-image {missing_img}")


if __name__ == "__main__":
    sys.exit(main())

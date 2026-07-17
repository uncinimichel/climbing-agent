#!/usr/bin/env python3
"""One-off (17 Jul 2026, tech review): move topo coordinates to normalized
0-1 fractions of the ORIENTED image.

Why: pixel coords were ambiguous — browser `naturalWidth` space (EXIF-
oriented) vs raw header dims disagreed for rotated photos, and pixels don't
survive image re-derivation. Sequence per topo photo:
  1. bake EXIF orientation into the original (images.normalize) — the one
     unambiguous space,
  2. refresh media.width_px/height_px to the oriented truth,
  3. divide every stored coordinate by those dims.
Idempotent-ish guard: rows whose coords are already all ≤ 1.5 are skipped.
"""
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent))
import images  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")


def norm_xy(pt, w, h):
    if not pt or pt[0] is None or pt[1] is None:
        return pt
    return [round(pt[0] / w, 5), round(pt[1] / h, 5)]


def norm_pts(pts, w, h):
    return [norm_xy(p, w, h) for p in pts]


def norm_descent(d, w, h):
    """Canonical descent = MP's richer shape: a list of labelled segments
    [{path:[[x,y]..], label, anchor, labelPosition}]. Plain point lists (drawn
    by the early Studio editor) are wrapped into a single unlabelled segment."""
    if not d:
        return None
    if isinstance(d[0], list):
        d = [{"path": d, "label": "", "anchor": None, "labelPosition": None}]
    out = []
    for seg in d:
        s = dict(seg)
        s["path"] = norm_pts(s.get("path") or [], w, h)
        for k in ("anchor", "labelPosition"):
            if s.get(k):
                s[k] = norm_xy(s[k], w, h)
        out.append(s)
    return out


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("""SELECT t.id AS topo_id, m.id AS media_id, m.uri,
                              m.width_px, m.height_px
                       FROM topo t JOIN media m ON m.id = t.media_id""")
        topos = cur.fetchall()
        done = skipped = 0
        for t in topos:
            f = ROOT / t["uri"]
            if f.exists():
                w, h = images.normalize(f)
                if (w, h) != (t["width_px"], t["height_px"]):
                    cur.execute("UPDATE media SET width_px=%s, height_px=%s WHERE id=%s",
                                (w, h, t["media_id"]))
                    print(f"  media {t['media_id']}: dims {t['width_px']}x{t['height_px']} → {w}x{h}")
            else:
                w, h = t["width_px"], t["height_px"]
            cur.execute("SELECT route_id, line, pitches, descent FROM topo_line WHERE topo_id=%s",
                        (t["topo_id"],))
            for ln in cur.fetchall():
                pts = ln["line"] or []
                if pts and all(abs(x) <= 1.5 and abs(y) <= 1.5 for x, y in pts):
                    skipped += 1
                    continue
                new_line = norm_pts(pts, w, h)
                new_pitches = []
                for p in (ln["pitches"] or []):
                    p = dict(p)
                    for k in ("belayPosition", "labelPosition"):
                        if p.get(k):
                            p[k] = norm_xy(p[k], w, h)
                    new_pitches.append(p)
                new_desc = norm_descent(ln["descent"], w, h)
                cur.execute("""UPDATE topo_line SET line=%s, pitches=%s, descent=%s,
                               updated_at=now() WHERE topo_id=%s AND route_id=%s""",
                            (json.dumps(new_line), json.dumps(new_pitches),
                             json.dumps(new_desc) if new_desc else None,
                             t["topo_id"], ln["route_id"]))
                done += 1
    print(f"normalized {done} lines, {skipped} already normalized, {len(topos)} topos checked")


if __name__ == "__main__":
    main()

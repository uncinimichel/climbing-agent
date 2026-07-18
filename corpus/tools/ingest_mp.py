#!/usr/bin/env python3
"""Lossless multi-pitch.com ingest — the merge path (knowledge/data/mp-field-mapping.md).

Runs AFTER ingest_corpus.py. That script lands the corpus record (areas, core
fields, hazards, climatology, structured pitches). This one upgrades every
mp-linked route with what only the MP site source has:

  - rock_code + aspect (face) + incline on the route itself
  - guidebooks  → guidebook (kind guidebook|pdf, 029) + route_guidebook
  - references  → route_reference (text verbatim; prefix parsed, may be NULL)
  - image blobs → tile_image (from data.json) / map_img / topo jsonb, kept opaque
  - verbatim prose (intro/approach/pitchInfo) — full HTML, never stripped
  - geom, timezone, and MP's own lastUpdate → route.last_update (the export
    round-trip depends on timestamps surviving; export_mp.py must not invent them)

Normalisations (mp-field-mapping.md §4) live HERE, in code — MP source files are
never hand-edited; the fixes flow back to multi-pitch via export_mp.py as a
reviewable git diff. Rock/incline/aspect values are validated against the LIVE
taxonomy tables, not a hardcoded list.

Governance: MP content is the site owner's own curation, so rows that are
'publish' on multi-pitch.com are stamped tagged_by='human' (the 025 CHECK
requires it). This intentionally freezes them against ingest_corpus re-runs;
ingest_mp itself remains their importer and updates them unconditionally.

Run:  agent/.venv/bin/python corpus/tools/ingest_mp.py [/path/to/multi-pitch]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_mapping  # noqa: E402

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    sys.exit("psycopg missing — run with agent/.venv/bin/python")

MP_REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    os.environ.get("MP_REPO", "/Users/micheluncini/dev/multi-pitch"))
CLIMBS_DIR = MP_REPO / "website" / "data" / "climbs"
DATA_JSON = MP_REPO / "website" / "data" / "data.json"
PAGES_DIR = MP_REPO / "website" / "climbs"
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")

PLACEHOLDER_IDS = {999}                     # template record shaped like a climb
HAZARD_FLAGS = {"abseil": "abseil", "traverse": "traverse", "boat": "boat",
                "tidal": "tidal", "polished": "polished", "loose": "loose",
                "seepage": "seepage", "grassLegdes": "grassLedges"}
# free-text → canonical rock code, applied before the live-taxonomy check
ROCK_FIX = {"qurtzite": "quartzite", "shale & sandstone": "sandstone",
            "rock type": None}              # template placeholder → unknown
REF_PREFIXES = {"Video", "Travel", "Article", "Info", "Tides", "Access", "Accommodation"}
REF_PREFIX_FIX = {"Access Info": "Access", "Accomerdation": "Accommodation"}
CLIMB_ID_RE = re.compile(r'climbIdMeta"\s+content="(\d+)"')


def truthy(v) -> bool:
    """MP hazard flags arrive as true/1/'1'/'true' vs false/None/''/0."""
    return v is True or v == 1 or str(v).strip().lower() in ("1", "true")


def parse_geo(s: str | None):
    try:
        lat, lon = (float(p) for p in s.split(","))
        return lat, lon
    except (AttributeError, ValueError):
        return None, None


def ref_prefix(text: str) -> str | None:
    """Parsed label for a reference; the text itself is stored verbatim."""
    head = text.split(":", 1)[0].strip() if ":" in text else ""
    head = REF_PREFIX_FIX.get(head, head)
    return head if head in REF_PREFIXES else None


def slug_by_id() -> dict[int, str]:
    """MP page slug per climb id, read from the generated pages' climbIdMeta."""
    out = {}
    for page in PAGES_DIR.glob("*/index.html"):
        m = CLIMB_ID_RE.search(page.read_text(errors="ignore"))
        if m:
            out[int(m.group(1))] = page.parent.name
    return out


def load_climbs():
    for f in sorted(CLIMBS_DIR.glob("*.json")):
        if f.stem == "template":
            continue
        c = json.loads(f.read_text()).get("climbData") or {}
        if not c.get("id") or c["id"] in PLACEHOLDER_IDS:
            continue
        yield c


def main():
    if not CLIMBS_DIR.is_dir():
        sys.exit(f"multi-pitch source not found: {CLIMBS_DIR}")
    tile_by_id = {c["id"]: c.get("tileImage")
                  for c in json.loads(DATA_JSON.read_text())["climbs"]}
    slugs = slug_by_id()

    conn = psycopg.connect(DSN, row_factory=dict_row,
                           options="-c search_path=climbing,public")
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM rock_type")
        rock_codes = {r["code"] for r in cur.fetchall()}
        cur.execute("SELECT code FROM incline")
        incline_codes = {r["code"] for r in cur.fetchall()}

    n_done = n_missing = 0
    warnings: list[str] = []
    with conn.cursor() as cur:
        for c in load_climbs():
            mp_id = c["id"]
            cur.execute("""SELECT entity_id AS rid FROM external_ref
                           WHERE entity_type = 'route' AND source_id = 'multipitch'
                             AND external_id = %s""", (str(mp_id),))
            row = cur.fetchone()
            if row:
                rid = row["rid"]
            else:
                # route absent from DB/corpus — create it, but only under an
                # area the corpus already knows (never invent areas)
                crag = next((a["id"] for a in route_mapping._load_corpus().values()
                             if a.get("kind") in ("crag", "sector")
                             and a["name"].strip().lower() == (c.get("cliff") or "").strip().lower()),
                            None)
                if not crag:
                    warnings.append(f"mp-{mp_id} ({c.get('routeName')}): crag "
                                    f"{c.get('cliff')!r} not in corpus areas — skipped")
                    n_missing += 1
                    continue
                area_pg = route_mapping.ensure_area(conn, crag)
                cur.execute(
                    """INSERT INTO route (area_id, name, status) VALUES (%s, %s, 'draft')
                       ON CONFLICT (area_id, name) DO UPDATE SET last_update = now()
                       RETURNING id""", (area_pg, c["routeName"]))
                rid = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO external_ref (entity_type, entity_id, source_id, external_id)
                       VALUES ('route', %s, 'multipitch', %s)
                       ON CONFLICT (source_id, external_id) DO NOTHING""", (rid, str(mp_id)))
                cur.execute("""INSERT INTO route_discipline (route_id, discipline_code)
                               VALUES (%s, 'multi-pitch') ON CONFLICT DO NOTHING""", (rid,))
                warnings.append(f"mp-{mp_id} ({c.get('routeName')}): created new route "
                                f"under corpus crag '{crag}'")
            url = (f"https://multi-pitch.com/climbs/{slugs[mp_id]}/"
                   if mp_id in slugs else "https://multi-pitch.com/")

            # --- normalise (mp-field-mapping.md §4) -------------------------
            rock_raw = (c.get("rock") or "").strip().lower()
            rock = ROCK_FIX.get(rock_raw, rock_raw) or None
            if rock and rock not in rock_codes:
                warnings.append(f"mp-{mp_id}: rock {c.get('rock')!r} not in taxonomy — NULL")
                rock = None
            incline = (c.get("incline") or "").replace("Slsb", "Slab").strip() or None
            if incline and incline not in incline_codes:
                warnings.append(f"mp-{mp_id}: incline {c.get('incline')!r} not canonical — NULL")
                incline = None
            face = c.get("face") if c.get("face") in (
                "N", "NE", "E", "SE", "S", "SW", "W", "NW") else None
            og = c.get("originalGrade")
            og = str(og) if og not in (None, "") else None
            lat, lon = parse_geo(c.get("geoLocation"))
            status = c.get("status") if c.get("status") in ("draft", "publish") else "draft"
            tagged_by = "human" if status == "publish" else None  # keep existing otherwise

            cur.execute(
                """UPDATE route SET
                       rock_code = %(rock)s, aspect = %(face)s, incline_code = %(incline)s,
                       grade_system_code = %(gsys)s, original_grade = %(og)s,
                       trad_grade = %(tg)s, tech_grade = %(teg)s, data_grade = %(dg)s,
                       length_m = %(len)s, pitches_count = %(pit)s,
                       approach_time_min = %(atime)s, approach_difficulty = %(adiff)s,
                       intro_html = %(intro)s, approach_html = %(approach)s,
                       pitch_info_html = %(pitch)s,
                       tile_image = %(tile)s, map_img = %(mapimg)s, topo = %(topo)s,
                       timezone = COALESCE(%(tz)s, timezone),
                       geom = CASE WHEN %(lat)s::float8 IS NOT NULL
                                   THEN ST_SetSRID(ST_MakePoint(%(lon)s::float8,
                                                                %(lat)s::float8), 4326)
                                   ELSE geom END,
                       status = %(status)s,
                       tagged_by = COALESCE(%(tagged)s, tagged_by),
                       last_update = COALESCE(%(lu)s::timestamptz, last_update)
                   WHERE id = %(rid)s""",
                {"rid": rid, "rock": rock, "face": face, "incline": incline,
                 "gsys": c.get("gradeSys"), "og": og,
                 "tg": c.get("tradGrade") or None, "teg": c.get("techGrade") or None,
                 "dg": c.get("dataGrade"), "len": c.get("length"), "pit": c.get("pitches"),
                 "atime": c.get("approachTime"), "adiff": c.get("approachDifficulty"),
                 "intro": c.get("intro") or None, "approach": c.get("approach") or None,
                 "pitch": c.get("pitchInfo") or None,
                 "tile": json.dumps(tile_by_id[mp_id]) if tile_by_id.get(mp_id) else None,
                 "mapimg": json.dumps(c["mapImg"]) if c.get("mapImg") else None,
                 "topo": json.dumps(c["topo"]) if c.get("topo") else None,
                 "tz": c.get("timeZone"), "lat": lat, "lon": lon,
                 "status": status, "tagged": tagged_by, "lu": c.get("lastUpdate")})

            # --- hazards: MP flags are the curated truth for these 8 codes --
            cur.execute("DELETE FROM route_hazard WHERE route_id = %s AND hazard_code = ANY(%s)",
                        (rid, list(HAZARD_FLAGS.values())))
            for flag, code in HAZARD_FLAGS.items():
                if truthy(c.get(flag)):
                    cur.execute(
                        """INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url)
                           VALUES (%s, %s, 'multi-pitch.com curated flag', %s)
                           ON CONFLICT DO NOTHING""", (rid, code, url))

            # --- climatology ------------------------------------------------
            w = c.get("weatherData") or {}
            if any(w.get(k) for k in ("tempH", "tempL", "rainyDays")):
                cur.execute("DELETE FROM route_climatology WHERE route_id = %s", (rid,))
                hi, lo, rd = (w.get("tempH") or [], w.get("tempL") or [],
                              w.get("rainyDays") or [])
                for m in range(12):
                    if m < max(len(hi), len(lo), len(rd)):
                        cur.execute(
                            """INSERT INTO route_climatology
                                   (route_id, month, rainy_days, temp_high, temp_low)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (rid, m + 1,
                             rd[m] if m < len(rd) else None,
                             hi[m] if m < len(hi) else None,
                             lo[m] if m < len(lo) else None))

            # --- guidebooks (dedup on isbn, else title) ----------------------
            cur.execute("DELETE FROM route_guidebook WHERE route_id = %s", (rid,))
            for g in c.get("guideBooks") or []:
                isbn = str(g["isbn"]) if g.get("isbn") else None
                kind = "pdf" if (g.get("type") or "").lower() == "pdf" else "guidebook"
                rrp = str(g["rrp"]) if g.get("rrp") not in (None, "") else None
                if isbn:
                    cur.execute("SELECT id FROM guidebook WHERE isbn = %s", (isbn,))
                else:
                    cur.execute("SELECT id FROM guidebook WHERE title = %s", (g.get("title"),))
                hit = cur.fetchone()
                if hit:
                    gid = hit["id"]
                    cur.execute(
                        """UPDATE guidebook SET title = %s, rrp = %s, img_url = %s,
                                                link = %s, kind = %s WHERE id = %s""",
                        (g.get("title"), rrp, g.get("imgURL"), g.get("link"), kind, gid))
                else:
                    cur.execute(
                        """INSERT INTO guidebook (isbn, title, rrp, img_url, link, kind)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                        (isbn, g.get("title"), rrp, g.get("imgURL"), g.get("link"), kind))
                    gid = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO route_guidebook (route_id, guidebook_id, page, description)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (rid, gid, str(g["pg"]) if g.get("pg") else None, g.get("description")))

            # --- references (text verbatim; prefix is parsed metadata) -------
            cur.execute("DELETE FROM route_reference WHERE route_id = %s", (rid,))
            for ref in c.get("references") or []:
                text, ref_url = (ref.get("text") or "").strip(), (ref.get("url") or "").strip()
                if not text or not ref_url:
                    continue
                cur.execute(
                    """INSERT INTO route_reference (route_id, prefix, text, url)
                       VALUES (%s, %s, %s, %s)""",
                    (rid, ref_prefix(text), text, ref_url))

            cur.execute("UPDATE external_ref SET url = %s WHERE entity_type = 'route' "
                        "AND source_id = 'multipitch' AND external_id = %s", (url, str(mp_id)))
            n_done += 1

    # source data hygiene that lives in the DB, not MP files (' Alicante' etc.)
    with conn.cursor() as cur:
        cur.execute("UPDATE area SET name = trim(name) WHERE name <> trim(name)")
        n_trim = cur.rowcount
    conn.commit()

    for w in warnings:
        print(f"[warn] {w}", file=sys.stderr)
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) AS n, count(rock_code) AS rock, count(aspect) AS face,
                              count(tile_image) AS tile,
                              (SELECT count(*) FROM route_guidebook) AS gb,
                              (SELECT count(*) FROM route_reference) AS refs
                       FROM route r JOIN external_ref x ON x.entity_type = 'route'
                            AND x.entity_id = r.id AND x.source_id = 'multipitch'""")
        s = cur.fetchone()
    print(f"upgraded {n_done} mp routes ({n_missing} missing from DB), "
          f"trimmed {n_trim} area names → mp rows now: {s['n']} total, "
          f"{s['rock']} rock, {s['face']} aspect, {s['tile']} tile image; "
          f"{s['gb']} guidebook links, {s['refs']} references")
    conn.close()


if __name__ == "__main__":
    main()

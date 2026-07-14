#!/usr/bin/env python3
"""Ingest db/corpus.json into Postgres — the Postgres-first switch (decision #34).

Postgres is the working store the Curation Studio edits; corpus.json becomes the
committed EXPORT/BACKUP written by build_corpus.py. This script is the restore /
(re)seed path:

  - every corpus area lands in climbing.area (via route_mapping.ensure_area —
    country→region→crag chains, coords/rock/aspect from the corpus, never invented)
  - every corpus route lands in climbing.route with tags (tagged_by/tag_prov carried),
    hazards (with evidence for safety-critical ones), climatology, and external_ref
  - multi-pitch prose is joined in from db/mp-climbs.json: description → intro_html,
    pitchInfo → pitch_info_html + parsed climbing.pitch rows

IDEMPOTENT and HUMAN-SAFE: upserts key on (area_id, name); a row whose tagged_by is
'human' is never overwritten (curated work always wins over re-ingest).

Run:  python3 db/tools/ingest_corpus.py            # needs the climbing-db container up
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

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "db" / "corpus.json"
ENRICH_CACHE = ROOT / "db" / "enrichment-cache.json"
MP_SNAPSHOT = ROOT / "db" / "mp-climbs.json"
# Michel's own site source — the RICH per-climb record (intro, approach prose,
# pitchInfo with per-pitch markup). Preferred over the flattened snapshot when
# this checkout exists (local-only convenience; the snapshot is the fallback).
MP_SITE_DIR = Path(os.environ.get(
    "MP_SITE_DIR", "/Users/micheluncini/dev/multi-pitch/website/data/climbs"))
DSN = os.environ.get("DATABASE_URL", "postgresql://climbing:climbing@localhost:5432/climbing")

# `<strong class="pitch-title">Pitch 1 –<span class="length">28m</span>
#  <span class="pitchGrade BAS">4c</span></strong> prose…<br>` → structured rows.
# The site source has quirks (`class="pitchGrade""`, \r\n, <br />), so the class
# attr and whitespace are matched loosely.
PITCH_RE = re.compile(
    r'<strong class="pitch-title">\s*Pitch\s+(\d+)\s*[–-]?\s*'
    r'(?:<span class="length">(\d+)\s*m</span>)?\s*'
    r'(?:<span class="pitchGrade\s*([A-Za-z]*)[^>]*>([^<]*)</span>)?\s*</strong>(.*?)'
    r'(?=<strong class="pitch-title">|$)',
    re.S,
)
TAG_STRIP = re.compile(r"<[^>]+>")

INCLINES = {"Slab", "Slab & Vertical", "Vertical", "Vertical & Overhanging", "Overhanging"}


def canon_incline(v: str | None) -> str | None:
    """Strict-or-NULL: fix known typos, else exact enum match, else None (warned)."""
    if not v:
        return None
    v = v.replace("Slsb", "Slab").strip()
    if v in INCLINES:
        return v
    print(f"[warn] incline {v!r} not canonical — stored NULL", file=sys.stderr)
    return None


# canonical grade_system codes keyed by their uppercase form (site classes vary in case)
GRADE_SYSTEMS = {c.upper(): c for c in (
    "BAS", "UIAA", "YDS", "ALP", "FS", "N", "EW", "SX", "BRZ", "V", "Font",
    "WI", "AI", "M", "D", "SCO", "A", "C", "VF", "S")}


def parse_pitches(pitch_html: str) -> list[dict]:
    out = []
    for num, length, sys_code, grade, prose in PITCH_RE.findall(pitch_html or ""):
        sc = GRADE_SYSTEMS.get((sys_code or "").upper())
        out.append({
            "number": int(num),
            "length_m": int(length) if length else None,
            "grade_system_code": sc,
            "original_grade": grade.strip() or None,
            "description": TAG_STRIP.sub("", prose).replace("&nbsp;", " ").strip() or None,
        })
    return out


def upsert_route(cur, area_pg_id: int, r: dict, mp: dict | None) -> int | None:
    """Insert/update one corpus route. Returns the PG id, or None if skipped
    (human-tagged rows are never overwritten)."""
    intro = (mp or {}).get("intro") or (mp or {}).get("description") or r.get("description") or None
    approach = (mp or {}).get("approach") or r.get("approach") or None
    pitch_html = (mp or {}).get("pitchInfo") or r.get("pitchInfo") or None
    ll = r.get("geoLocation") or [None, None]
    cur.execute(
        """
        INSERT INTO route (area_id, name, status, tagged_by, tag_prov,
            length_m, pitches_count, incline_code,
            grade_system_code, original_grade, trad_grade, tech_grade, data_grade,
            protection_code, protection_style, belays,
            approach_time_min, approach_difficulty,
            rack, rope, descent_method, descent_abseils, descent_notes,
            escapable, commitment_code, wind_exposed,
            curation_notes, needs_field_check, curated_at,
            elevation_m, sun_window_code, best_season, stars,
            intro_html, approach_html, pitch_info_html, geom, timezone)
        VALUES (%(area)s, %(name)s, %(status)s, %(tagged_by)s, %(tag_prov)s,
            %(len)s, %(pit)s, %(incline)s,
            %(gsys)s, %(og)s, %(tg)s, %(teg)s, %(dg)s,
            COALESCE(%(prot)s, 'UNSPECIFIED'), %(pstyle)s, %(belays)s,
            %(atime)s, %(adiff)s,
            %(rack)s, %(rope)s, %(descm)s, %(descab)s, %(descn)s,
            %(escap)s, %(commit)s, %(windex)s,
            %(cnotes)s, COALESCE(%(nfc)s, false), %(curated_at)s,
            %(elev)s, %(sun)s, %(season)s, %(stars)s,
            %(intro)s, %(approach)s, %(pitch_html)s,
            CASE WHEN %(lat)s::float8 IS NOT NULL
                 THEN ST_SetSRID(ST_MakePoint(%(lon)s::float8, %(lat)s::float8), 4326) END,
            %(tz)s)
        ON CONFLICT (area_id, name) DO UPDATE SET
            -- a curator's quarantine outlives a stale backup (draft never un-quarantines)
            status = CASE WHEN route.status = 'quarantined' AND EXCLUDED.status = 'draft'
                          THEN route.status ELSE EXCLUDED.status END,
            tagged_by = EXCLUDED.tagged_by,
            tag_prov = EXCLUDED.tag_prov,
            length_m = EXCLUDED.length_m, pitches_count = EXCLUDED.pitches_count,
            incline_code = EXCLUDED.incline_code,
            grade_system_code = EXCLUDED.grade_system_code,
            original_grade = EXCLUDED.original_grade,
            trad_grade = EXCLUDED.trad_grade, tech_grade = EXCLUDED.tech_grade,
            data_grade = EXCLUDED.data_grade,
            protection_code = EXCLUDED.protection_code,
            protection_style = EXCLUDED.protection_style, belays = EXCLUDED.belays,
            rack = EXCLUDED.rack, rope = EXCLUDED.rope,
            descent_method = EXCLUDED.descent_method,
            descent_abseils = EXCLUDED.descent_abseils,
            descent_notes = EXCLUDED.descent_notes,
            escapable = EXCLUDED.escapable, commitment_code = EXCLUDED.commitment_code,
            wind_exposed = EXCLUDED.wind_exposed,
            elevation_m = EXCLUDED.elevation_m,
            sun_window_code = EXCLUDED.sun_window_code,
            best_season = EXCLUDED.best_season, stars = EXCLUDED.stars,
            approach_time_min = EXCLUDED.approach_time_min,
            approach_difficulty = EXCLUDED.approach_difficulty,
            curation_notes = EXCLUDED.curation_notes,
            needs_field_check = EXCLUDED.needs_field_check,
            curated_at = EXCLUDED.curated_at,
            timezone = COALESCE(EXCLUDED.timezone, route.timezone),
            intro_html = COALESCE(EXCLUDED.intro_html, route.intro_html),
            approach_html = COALESCE(EXCLUDED.approach_html, route.approach_html),
            pitch_info_html = COALESCE(EXCLUDED.pitch_info_html, route.pitch_info_html),
            geom = COALESCE(EXCLUDED.geom, route.geom),
            last_update = now()
        WHERE route.tagged_by <> 'human'
        RETURNING id
        """,
        {"area": area_pg_id, "name": r["name"], "status": r["status"],
         "tagged_by": r.get("taggedBy") or "source",
         "tag_prov": json.dumps(r["tagProv"]) if r.get("tagProv") else None,
         "len": r.get("length"), "pit": r.get("pitches"), "incline": canon_incline(r.get("incline")),
         "gsys": r.get("gradeSys"), "og": r.get("originalGrade"),
         "tg": r.get("tradGrade"), "teg": r.get("techGrade"), "dg": r.get("dataGrade"),
         "prot": (r.get("protection") or None) if r.get("protection") != "UNSPECIFIED" else None,
         "pstyle": r.get("protectionStyle"), "belays": r.get("belays"),
         "atime": r.get("approachTime"), "adiff": r.get("approachDifficulty"),
         "rack": r.get("rack"), "rope": r.get("rope"),
         "descm": r.get("descentMethod"), "descab": r.get("descentAbseils"),
         "descn": r.get("descentNotes"),
         "escap": r.get("escapable"), "commit": r.get("commitment"),
         "windex": r.get("windExposed"),
         "cnotes": r.get("curationNotes"), "nfc": r.get("needsFieldCheck"),
         "curated_at": r.get("curatedAt"),
         "elev": r.get("elevation"), "sun": r.get("sunWindow"),
         "season": r.get("bestSeason"), "stars": r.get("stars"),
         "intro": intro, "approach": approach, "pitch_html": pitch_html,
         "lat": ll[0], "lon": ll[1], "tz": (mp or {}).get("timeZone")},
    )
    row = cur.fetchone()
    if not row:      # conflict hit a human-tagged row → protected, skipped
        return None
    rid = row["id"]

    # set-valued facets: replace wholesale (this row is not human-tagged)
    for table, col, values in (
        ("route_discipline", "discipline_code", r.get("disciplines") or []),
        ("route_feature", "feature_code", r.get("features") or []),
        ("route_character", "character_code", r.get("character") or []),
    ):
        cur.execute(f"DELETE FROM {table} WHERE route_id = %s", (rid,))
        for v in values:
            cur.execute(
                f"INSERT INTO {table} (route_id, {col}) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (rid, v))

    cur.execute("DELETE FROM route_hazard WHERE route_id = %s", (rid,))
    hz_ev = r.get("hazardEvidence") or {}
    for hz in r.get("hazards") or []:
        # real evidence rides in the export (hazardEvidence); the generic span is
        # only the fallback for pre-2.1 backups (020 trigger needs SOMETHING)
        ev = hz_ev.get(hz) or {}
        cur.execute(
            """INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url)
               VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (rid, hz, ev.get("span") or "multi-pitch.com source flag",
             ev.get("url") or "https://multi-pitch.com/data/data.json"))

    cur.execute("DELETE FROM route_climatology WHERE route_id = %s", (rid,))
    for m in r.get("climatology") or []:
        cur.execute(
            """INSERT INTO route_climatology (route_id, month, rainy_days, temp_high, temp_low)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (rid, m.get("month"), m.get("rainyDays"), m.get("tempHigh"), m.get("tempLow")))

    pitch_rows = parse_pitches(pitch_html or "") or [
        # restore path: the export's structured pitchRows (curated in the Studio)
        {"number": p.get("number"), "length_m": p.get("length"),
         "grade_system_code": p.get("gradeSys"), "original_grade": p.get("grade"),
         "description": p.get("description")}
        for p in (r.get("pitchRows") or []) if p.get("number")]
    if pitch_rows:
        cur.execute("DELETE FROM pitch WHERE route_id = %s", (rid,))
    for p in pitch_rows:
        cur.execute(
            """INSERT INTO pitch (route_id, number, length_m, grade_system_code,
                                  original_grade, description)
               VALUES (%(rid)s, %(number)s, %(length_m)s, %(grade_system_code)s,
                       %(original_grade)s, %(description)s)
               ON CONFLICT (route_id, number) DO NOTHING""",
            {"rid": rid, **p})

    parkings = r.get("parkings") or []
    if parkings:
        cur.execute("DELETE FROM route_parking WHERE route_id = %s", (rid,))
        for i, pk in enumerate(parkings, 1):
            cur.execute(
                """INSERT INTO route_parking (route_id, label, geom, ord)
                   VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)""",
                (rid, pk.get("label") or "parking", pk["lon"], pk["lat"], i))

    refs = r.get("refs") or ([{"source": "multipitch", "id": str(r["id"])[3:],
                               "url": "https://multi-pitch.com/"}]
                             if str(r["id"]).startswith("mp-") else [])
    for ref in refs:
        cur.execute(
            """INSERT INTO external_ref (entity_type, entity_id, source_id, external_id, url)
               VALUES ('route', %s, %s, %s, %s)
               ON CONFLICT (source_id, external_id) DO NOTHING""",
            (rid, ref["source"], str(ref["id"]), ref.get("url")))
    return rid


def main():
    corpus = json.loads(CORPUS.read_text())
    mp_by_id = {}
    if MP_SNAPSHOT.exists():
        snap = json.loads(MP_SNAPSHOT.read_text())
        mp_by_id = {str(c.get("id")): c for c in snap.get("climbs", snap if isinstance(snap, list) else [])}
    if MP_SITE_DIR.is_dir():
        n_rich = 0
        for i in list(mp_by_id):
            f = MP_SITE_DIR / f"{i}.json"
            if f.exists():
                rich = json.loads(f.read_text()).get("climbData") or {}
                mp_by_id[i] = {**mp_by_id[i], **{k: v for k, v in rich.items() if v}}
                n_rich += 1
        print(f"rich site source: {n_rich}/{len(mp_by_id)} climbs upgraded from {MP_SITE_DIR}")

    conn = psycopg.connect(DSN, row_factory=dict_row)
    n_areas = n_routes = n_skipped = 0

    # 1. the whole area tree (crags without routes included — venues, gazetteer)
    for a in corpus["areas"]:
        route_mapping.ensure_area(conn, a["id"])
        n_areas += 1

    # 2. routes (numeric ids are DB-born curated rows — already here, protected anyway)
    area_memo: dict[str, int] = {}

    def area_pg_id(slug_id):
        if slug_id not in area_memo:
            area_memo[slug_id] = route_mapping.ensure_area(conn, slug_id)
        return area_memo[slug_id]

    with conn.cursor() as cur:
        for r in corpus["routes"]:
            area_pg = area_pg_id(r["area"]) if r.get("area") else None
            if area_pg is None:
                print(f"[warn] {r['id']} has no area — skipped", file=sys.stderr)
                continue
            mp = mp_by_id.get(str(r["id"])[3:]) if str(r["id"]).startswith("mp-") else None
            rid = upsert_route(cur, area_pg, r, mp)
            if rid is None:
                n_skipped += 1
            else:
                n_routes += 1
    conn.commit()

    # 3. apply ai_tag.py's enrichment cache to the DB (the merge the #34 rewrite lost:
    #    ai_tag writes the cache; THIS is what lands it in Postgres). LLM output never
    #    touches a human-tagged row; applied rows are stamped taggedBy:llm + tagProv.
    n_enriched = 0
    if ENRICH_CACHE.exists():
        enrich = json.loads(ENRICH_CACHE.read_text())
        with conn.cursor() as cur:
            for key, e in enrich.items():
                if not key.startswith("mp-") or not isinstance(e, dict):
                    continue
                cur.execute(
                    """SELECT r.id FROM route r JOIN external_ref x
                         ON x.entity_type = 'route' AND x.entity_id = r.id
                       WHERE x.source_id = 'multipitch' AND x.external_id = %s
                         AND r.tagged_by <> 'human'""", (key[3:],))
                row = cur.fetchone()
                if not row:
                    continue
                rid = row["id"]
                for table, col, values in (
                    ("route_feature", "feature_code", e.get("features")),
                    ("route_character", "character_code", e.get("character")),
                    ("route_discipline", "discipline_code", e.get("discipline")),
                ):
                    if not values:
                        continue
                    if table != "route_discipline":   # disciplines are additive
                        cur.execute(f"DELETE FROM {table} WHERE route_id = %s", (rid,))
                    for v in values:
                        cur.execute(f"INSERT INTO {table} (route_id, {col}) VALUES (%s, %s) "
                                    "ON CONFLICT DO NOTHING", (rid, v))
                prov = e.get("_prov") or {}
                cur.execute(
                    """UPDATE route SET
                           protection_code = COALESCE(%s, protection_code),
                           tagged_by = 'llm', tag_prov = %s, last_update = now()
                       WHERE id = %s""",
                    (e.get("protection"),
                     json.dumps({"model": prov.get("model"), "date": prov.get("date")}),
                     rid))
                n_enriched += 1
        conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT status, tagged_by, count(*) AS n FROM route GROUP BY 1, 2 ORDER BY 1, 2")
        summary = ", ".join(f"{x['status']}/{x['tagged_by']}={x['n']}" for x in cur.fetchall())
    print(f"ingested {n_routes} routes ({n_skipped} human-tagged rows protected), "
          f"{n_areas} corpus areas ensured, {n_enriched} enrichment-cache merges → DB now: {summary}")
    conn.close()


if __name__ == "__main__":
    main()

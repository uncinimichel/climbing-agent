"""Shared mechanical mapping logic: the multi-pitch trad/alpine filter, the
db/corpus.json area tree walk (source of area coords/rock/aspect/gradeContext
— decision #27), and the route-schema.md insert for mechanically-fetched
routes. Used by crawl_worker.py's insert_mechanical/discover_children for
every source.
"""
from __future__ import annotations

import json
from pathlib import Path

CORPUS_PATH = Path(__file__).resolve().parents[1] / "corpus.json"
RAW_CACHE_DIR = Path(__file__).resolve().parents[1] / ".raw_cache"

MIN_PITCHES_FOR_MULTIPITCH = 2
MIN_LENGTH_M_FOR_MULTIPITCH = 60
MULTIPITCH_DISCIPLINES = {"trad", "alpine", "big-wall"}

# Free-text rock names → canonical rock_type codes (strict FK). Composites keep
# the primary (first-named) rock; unknowns become NULL — never invented.
ROCK_CANON = {
    "culm sandstone": "sandstone", "volcanic rock": "volcanic",
    "limestone/dolomite": "limestone", "rhyolite/dolerite": "rhyolite",
    "shale & sandstone": "sandstone", "qurtzite": "quartzite", "phonolite": "volcanic",
}
KNOWN_ROCK = {"andesite", "basalt", "chalk", "conglomerate", "dolerite", "dolomite",
              "gabbro", "gneiss", "granite", "gritstone", "limestone", "quartzite",
              "rhyolite", "sandstone", "schist", "slate", "volcanic"}


def canon_rock(r: str | None) -> str | None:
    if not r:
        return None
    k = ROCK_CANON.get(r.strip().lower(), r.strip().lower())
    return k if k in KNOWN_ROCK else None

_corpus_areas_by_id: dict[str, dict] | None = None


def _load_corpus() -> dict[str, dict]:
    global _corpus_areas_by_id
    if _corpus_areas_by_id is None:
        areas = json.loads(CORPUS_PATH.read_text())["areas"]
        _corpus_areas_by_id = {a["id"]: a for a in areas}
    return _corpus_areas_by_id


def passes_multipitch_trad_alpine(pitches: int | None, length_m: int | None, discipline: str | None) -> bool:
    """Structural fields only, no LLM. Bolted anchors/belays/pegs are a
    different field (protectionStyle/belays) and never disqualify a route
    here (taxonomy.md)."""
    is_multipitch = (pitches or 0) >= MIN_PITCHES_FOR_MULTIPITCH or (length_m or 0) >= MIN_LENGTH_M_FOR_MULTIPITCH
    return is_multipitch and (discipline or "").lower() in MULTIPITCH_DISCIPLINES


def ensure_area(conn, corpus_area_id: str) -> int:
    """Resolve a db/corpus.json area id to a Postgres `area.id`, creating the
    country->region->crag chain from corpus.json's own parent links if it
    doesn't exist yet (corpus.json is the curated source of coords/rock/
    aspect/gradeContext — decision #27; nothing here is invented)."""
    corpus = _load_corpus()
    chain, seen = [], set()
    node_id = corpus_area_id
    while node_id:
        if node_id in seen:   # self/circular parent (bad export) — stop, don't hang
            break
        seen.add(node_id)
        node = corpus[node_id]
        chain.append(node)
        node_id = node.get("parent")
    chain.reverse()  # root first

    # Explicit select-then-insert rather than ON CONFLICT(parent_id, name):
    # top-level areas have parent_id IS NULL, and Postgres never treats two
    # NULLs as conflicting, so ON CONFLICT would silently allow duplicate
    # country rows across repeated calls.
    parent_pg_id = None
    with conn.cursor() as cur:
        for node in chain:
            cur.execute(
                "SELECT id FROM area WHERE name = %s AND parent_id IS NOT DISTINCT FROM %s",
                (node["name"], parent_pg_id),
            )
            row = cur.fetchone()
            if row:
                parent_pg_id = row["id"]
                continue
            lat, lng = (node["geoLocation"] or [None, None])
            cur.execute(
                """
                INSERT INTO area (parent_id, name, kind, grade_context, rock_code, aspect, geom)
                VALUES (%s, %s, %s, %s, %s, %s,
                        CASE WHEN %s::float8 IS NOT NULL
                             THEN ST_SetSRID(ST_MakePoint(%s::float8, %s::float8), 4326) END)
                RETURNING id
                """,
                (parent_pg_id, node["name"], node["kind"], node.get("gradeContext"),
                 canon_rock(node.get("rock")), node.get("aspect"), lat, lng, lat),
            )
            parent_pg_id = cur.fetchone()["id"]
    conn.commit()
    return parent_pg_id


def ensure_sector(conn, parent_area_id: int, name: str | None) -> int:
    """A named sector/buttress under a crag (area.kind='sector') — the level
    routes actually hang off, per route-schema.md's sector_id. Falls back to
    the parent crag area when the source gives no sector name."""
    if not name:
        return parent_area_id
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO area (parent_id, name, kind) VALUES (%s, %s, 'sector') ON CONFLICT (parent_id, name) DO NOTHING",
            (parent_area_id, name),
        )
        cur.execute("SELECT id FROM area WHERE parent_id = %s AND name = %s", (parent_area_id, name))
        row = cur.fetchone()
    conn.commit()
    return row["id"] if row else parent_area_id


def save_raw(source_id: str, external_id: str, record: dict) -> str:
    d = RAW_CACHE_DIR / source_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{external_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return str(path)


def upsert_route(conn, area_id: int, source_id: str, external_id: str, url: str, *,
                  name: str, trad_grade: str | None, tech_grade: str | None,
                  discipline: str, stars: int | None, length_m: int | None,
                  pitches: int | None) -> int:
    """Mechanical fields only — status stays 'draft', protection stays
    UNSPECIFIED, no prose (raw description is in the raw cache for the LLM
    tag stage, not written to intro_html, which is generated prose, not a
    scrape dump)."""
    original_grade = " ".join(p for p in (trad_grade, tech_grade) if p) or None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_grade FROM grade_conversion WHERE grade_system_code = 'BAS' AND original_grade = %s",
            (original_grade,),
        )
        row = cur.fetchone()
        data_grade = row["data_grade"] if row else None

        cur.execute(
            """
            INSERT INTO route (area_id, name, status, length_m, pitches_count,
                                grade_system_code, original_grade, trad_grade, tech_grade,
                                data_grade, stars)
            VALUES (%s, %s, 'draft', %s, %s, 'BAS', %s, %s, %s, %s, %s)
            ON CONFLICT (area_id, name) DO UPDATE SET
                length_m = EXCLUDED.length_m, pitches_count = EXCLUDED.pitches_count,
                data_grade = EXCLUDED.data_grade, stars = EXCLUDED.stars, last_update = now()
            RETURNING id
            """,
            (area_id, name, length_m, pitches, original_grade, trad_grade, tech_grade, data_grade, stars),
        )
        route_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO external_ref (entity_type, entity_id, source_id, external_id, url)
            VALUES ('route', %s, %s, %s, %s)
            ON CONFLICT (source_id, external_id) DO NOTHING
            """,
            (route_id, source_id, str(external_id), url),
        )

        for code in {discipline.lower(), "multi-pitch"}:
            cur.execute(
                "INSERT INTO route_discipline (route_id, discipline_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (route_id, code),
            )
    conn.commit()
    return route_id

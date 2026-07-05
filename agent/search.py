"""search_climbs — the retrieval agent's DB layer.

Builds one parameterized SQL query over the climbing schema from validated,
enum-constrained parameters (roadmap Stage 5½, decision #19). The enum lists are
loaded from the DB lookup tables at startup so the tool schema and the taxonomy
can never drift. The LLM never writes SQL; this module does.

Run directly for a no-LLM test pass:  python search.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DEFAULT_DSN = "postgresql://climbing:climbing@localhost:5432/climbing"
MAX_LIMIT = 20


def load_dotenv() -> None:
    """Read repo-root .env (KEY=VALUE lines) without overriding real env vars."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connect() -> psycopg.Connection:
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    return psycopg.connect(dsn, row_factory=dict_row)


def load_enums(conn: psycopg.Connection) -> dict[str, list[str]]:
    """The closed vocabularies, straight from the DB (taxonomy.md's mirror)."""
    enums: dict[str, list[str]] = {}
    with conn.cursor() as cur:
        for key, sql in {
            "rock": "SELECT code FROM climbing.rock_type ORDER BY code",
            "disciplines": "SELECT code FROM climbing.discipline ORDER BY code",
            "features": "SELECT code FROM climbing.feature ORDER BY code",
            "character": "SELECT code FROM climbing.character ORDER BY code",
            "aspect": "SELECT unnest(ARRAY['N','NE','E','SE','S','SW','W','NW'])",
            "sun_window": "SELECT code FROM climbing.sun_window ORDER BY code",
        }.items():
            cur.execute(sql)
            enums[key] = [r[next(iter(r))] for r in cur.fetchall()]
    return enums


def tool_schema(enums: dict[str, list[str]]) -> dict:
    """The search_climbs tool definition, enums injected from the DB."""
    return {
        "name": "search_climbs",
        "description": (
            "Search the curated climbing-route corpus. Call this whenever the user asks to "
            "find routes, crags, or climbing by any attribute (rock type, location, season, "
            "grade, style, aspect). All filters are optional and combine with AND. "
            "Results only include published (curated) routes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rock": {
                    "type": "string",
                    "enum": enums["rock"],
                    "description": "Rock type the route is on.",
                },
                "disciplines": {
                    "type": "array",
                    "items": {"type": "string", "enum": enums["disciplines"]},
                    "description": "Climbing styles the route must ALL have (e.g. ['trad','multi-pitch']).",
                },
                "features": {
                    "type": "array",
                    "items": {"type": "string", "enum": enums["features"]},
                    "description": "Rock features the route must ALL have (e.g. ['crack'], ['corner'], ['tufa']).",
                },
                "character": {
                    "type": "array",
                    "items": {"type": "string", "enum": enums["character"]},
                    "description": "How it climbs — the route must have ALL of these (e.g. ['sustained','pumpy'] for endurance, ['delicate'] for slabby balance climbing).",
                },
                "near": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                        "radius_km": {"type": "number", "description": "Search radius in km (default 150)."},
                    },
                    "required": ["lat", "lon"],
                    "additionalProperties": False,
                    "description": "Geographic filter. Only use coordinates the user gave or clearly implied; ask if unknown.",
                },
                "month": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 12,
                    "description": "Month (1-12) the trip happens; matches the route's best-season window.",
                },
                "max_data_grade": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 7,
                    "description": "Upper difficulty bound on the normalized 1-7 ladder (5 ≈ VS / 5.8 / V+).",
                },
                "aspect": {
                    "type": "string",
                    "enum": enums["aspect"],
                    "description": "Compass direction the route faces (N face = shade, S = sun).",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
            },
            "additionalProperties": False,
        },
    }


def search_climbs(conn: psycopg.Connection, params: dict) -> list[dict]:
    """Validate params against the enums and run the search. Raises ValueError on
    off-dictionary values (the agent loop returns that as an is_error tool result)."""
    enums = load_enums(conn)

    where = ["r.status = 'publish'"]
    args: dict = {}

    rock = params.get("rock")
    if rock is not None:
        if rock not in enums["rock"]:
            raise ValueError(f"unknown rock type {rock!r}; allowed: {enums['rock']}")
        where.append("r.eff_rock_code = %(rock)s")
        args["rock"] = rock

    for facet, table, col in (("disciplines", "route_discipline", "discipline_code"),
                              ("features", "route_feature", "feature_code"),
                              ("character", "route_character", "character_code")):
        for i, val in enumerate(params.get(facet) or []):
            if val not in enums[facet]:
                raise ValueError(f"unknown {facet} value {val!r}; allowed: {enums[facet]}")
            key = f"{facet}{i}"
            where.append(
                f"EXISTS (SELECT 1 FROM climbing.{table} j_{key} "
                f"WHERE j_{key}.route_id = r.id AND j_{key}.{col} = %({key})s)"
            )
            args[key] = val

    near = params.get("near")
    if near is not None:
        args["lat"], args["lon"] = float(near["lat"]), float(near["lon"])
        args["radius_m"] = float(near.get("radius_km", 150)) * 1000
        where.append(
            "ST_DWithin(r.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius_m)s)"
        )

    month = params.get("month")
    if month is not None:
        month = int(month)
        if not 1 <= month <= 12:
            raise ValueError("month must be 1-12")
        where.append("(r.best_season IS NULL OR %(month)s = ANY(r.best_season))")
        args["month"] = month

    max_dg = params.get("max_data_grade")
    if max_dg is not None:
        where.append("r.data_grade <= %(max_dg)s")
        args["max_dg"] = int(max_dg)

    aspect = params.get("aspect")
    if aspect is not None:
        if aspect not in enums["aspect"]:
            raise ValueError(f"unknown aspect {aspect!r}")
        where.append("r.eff_aspect = %(aspect)s")
        args["aspect"] = aspect

    limit = min(int(params.get("limit") or 10), MAX_LIMIT)
    args["limit"] = limit

    distance_sql = (
        "ST_Distance(r.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) / 1000.0"
        if near is not None else "NULL::float"
    )
    climo_join = (
        "LEFT JOIN climbing.route_climatology cl ON cl.route_id = r.id AND cl.month = %(month)s"
        if month is not None else
        "LEFT JOIN climbing.route_climatology cl ON false"
    )

    sql = f"""
        SELECT r.name,
               array_to_string(r.path_tokens, ' > ')          AS location,
               r.eff_grade_context                            AS grade_context,
               r.grade_system_code || ' ' || r.original_grade AS grade,
               r.data_grade,
               r.eff_rock_code                                AS rock,
               rt.notes                                       AS rock_notes,
               rt.seeps, rt.fragile_when_wet,
               r.eff_aspect                                   AS aspect,
               r.sun_window_code                              AS sun_window,
               r.protection_code                              AS protection,
               r.length_m, r.pitches_count, r.elevation_m,
               r.approach_time_min, r.approach_difficulty,
               r.best_season, r.stars,
               ROUND(({distance_sql})::numeric, 1)            AS distance_km,
               cl.rainy_days AS month_rainy_days, cl.temp_high AS month_temp_high,
               r.protection_style, r.belays,
               (SELECT array_agg(rd.discipline_code ORDER BY rd.discipline_code)
                  FROM climbing.route_discipline rd WHERE rd.route_id = r.id) AS disciplines,
               (SELECT array_agg(rf.feature_code ORDER BY rf.feature_code)
                  FROM climbing.route_feature rf WHERE rf.route_id = r.id)    AS features,
               (SELECT array_agg(rc.character_code ORDER BY rc.character_code)
                  FROM climbing.route_character rc WHERE rc.route_id = r.id)  AS character,
               (SELECT json_agg(json_build_object('hazard', rh.hazard_code, 'evidence', rh.evidence_span))
                  FROM climbing.route_hazard rh WHERE rh.route_id = r.id)     AS hazards
        FROM climbing.route_resolved r
        LEFT JOIN climbing.rock_type rt ON rt.code = r.eff_rock_code
        {climo_join}
        WHERE {' AND '.join(where)}
        ORDER BY {'distance_km NULLS LAST,' if near is not None else ''} r.data_grade NULLS LAST, r.stars DESC NULLS LAST
        LIMIT %(limit)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    for row in rows:  # decimals/None → JSON-friendly
        if row.get("distance_km") is not None:
            row["distance_km"] = float(row["distance_km"])
    return rows


if __name__ == "__main__":
    load_dotenv()
    conn = connect()
    tests = [
        ("sandstone in August", {"rock": "sandstone", "month": 8}),
        ("trad multi-pitch within 700km of London, ≤VS", {
            "disciplines": ["trad", "multi-pitch"],
            "near": {"lat": 51.5, "lon": -0.3, "radius_km": 700},
            "max_data_grade": 5,
        }),
        ("north-facing (shade) in August", {"aspect": "N", "month": 8}),
        ("limestone in August (Anica Kuk should NOT match — not in season)", {"rock": "limestone", "month": 8}),
    ]
    failures = 0
    for label, p in tests:
        rows = search_climbs(conn, p)
        print(f"\n== {label} → {len(rows)} result(s)")
        for r in rows:
            print(f"   {r['name']:34s} {r['grade']:12s} {r['rock']:10s} "
                  f"{(str(r['distance_km']) + ' km') if r['distance_km'] is not None else '':>10s}  {r['location']}")
    # enum rejection must raise
    try:
        search_climbs(conn, {"rock": "kryptonite"})
        print("FAIL: off-dictionary rock accepted"); failures += 1
    except ValueError as e:
        print(f"\n== enum rejection OK: {e}")
    sys.exit(1 if failures else 0)

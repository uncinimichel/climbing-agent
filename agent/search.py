"""search_climbs — the retrieval agent's data layer, over the JSON record.

No Postgres (the corpus consolidated on the JSON record — the Studio's own store).
This reads exactly what the Studio writes (corpus/tools/store.py): published route
documents, the area tree with downward-inherited eff_* (rock/aspect/gradeContext),
and the taxonomy enums. The enum lists come from the same taxonomy the store
validates against, so the tool schema and the corpus can never drift. The LLM
never writes a query; this module filters the in-memory records.

The public surface is unchanged from the Postgres era so its callers
(chat.py / core.py / search_cli.py / server.py) need no edits: `connect()` now
returns the in-memory Store (the "connection"), and load_enums/tool_schema/
search_climbs take that store in the old `conn` position.

Run directly for a no-LLM test pass:  python search.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "corpus" / "tools"))
from store import Store  # noqa: E402

MAX_LIMIT = 20
ASPECTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


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


def connect() -> Store:
    """The 'connection' is now the in-memory JSON store (loads the record once)."""
    return Store()


def load_enums(store: Store) -> dict[str, list[str]]:
    """The closed vocabularies, straight from the taxonomy record the store
    validates writes against — same source, so they can't drift."""
    code = lambda fam: sorted(t["code"] for t in store.tax[fam])  # noqa: E731
    return {
        "rock": code("rock_type"),
        "disciplines": code("discipline"),
        "features": code("feature"),
        "character": code("character"),
        "aspect": ASPECTS,
        "sun_window": code("sun_window"),
    }


def tool_schema(enums: dict[str, list[str]]) -> dict:
    """The search_climbs tool definition, enums injected from the taxonomy."""
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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _coords(store: Store, r: dict) -> tuple[float, float] | None:
    """Route coords, falling back to the nearest ancestor area with a location
    (the planner's own haversine matching does the same)."""
    if r.get("lat") is not None and r.get("lon") is not None:
        return float(r["lat"]), float(r["lon"])
    for a in store.area_chain(r.get("area_id")):
        if a.get("lat") is not None and a.get("lon") is not None:
            return float(a["lat"]), float(a["lon"])
    return None


def search_climbs(store: Store, params: dict) -> list[dict]:
    """Validate params against the enums and filter the published corpus. Raises
    ValueError on off-dictionary values (the agent loop returns that as an
    is_error tool result) — validation happens up front, before any row is seen,
    so a bad enum is rejected even when nothing would have matched."""
    enums = load_enums(store)
    rock_by_code = {t["code"]: t for t in store.tax["rock_type"]}

    # ── validate every param up front (matches the old pre-query validation) ──
    rock = params.get("rock")
    if rock is not None and rock not in enums["rock"]:
        raise ValueError(f"unknown rock type {rock!r}; allowed: {enums['rock']}")
    for facet in ("disciplines", "features", "character"):
        for val in params.get(facet) or []:
            if val not in enums[facet]:
                raise ValueError(f"unknown {facet} value {val!r}; allowed: {enums[facet]}")
    aspect = params.get("aspect")
    if aspect is not None and aspect not in enums["aspect"]:
        raise ValueError(f"unknown aspect {aspect!r}")
    month = params.get("month")
    if month is not None:
        month = int(month)
        if not 1 <= month <= 12:
            raise ValueError("month must be 1-12")
    max_dg = None if params.get("max_data_grade") is None else int(params["max_data_grade"])
    near = params.get("near")
    if near is not None:
        near = {"lat": float(near["lat"]), "lon": float(near["lon"]),
                "radius_km": float(near.get("radius_km", 150))}
    want = {f: set(params.get(f) or []) for f in ("disciplines", "features", "character")}
    limit = min(int(params.get("limit") or 10), MAX_LIMIT)

    rows: list[dict] = []
    for r in store.routes.values():
        if r.get("status") != "publish":
            continue
        eff = store.route_effective(r)

        if rock is not None and eff["eff_rock_code"] != rock:
            continue
        tags = r.get("tags") or {}
        if not want["disciplines"] <= set(tags.get("disciplines") or []):
            continue
        if not want["features"] <= set(tags.get("features") or []):
            continue
        if not want["character"] <= set(tags.get("character") or []):
            continue
        if aspect is not None and eff["eff_aspect"] != aspect:
            continue
        if month is not None:
            season = r.get("best_season")
            if season and month not in season:   # NULL season = matches any month (as in SQL)
                continue
        if max_dg is not None:
            dg = r.get("data_grade")
            if dg is None or dg > max_dg:          # NULL data_grade excluded, as in SQL
                continue

        distance_km = None
        if near is not None:
            co = _coords(store, r)
            if co is None:
                continue
            distance_km = round(_haversine_km(near["lat"], near["lon"], co[0], co[1]), 1)
            if distance_km > near["radius_km"]:
                continue

        rt = rock_by_code.get(eff["eff_rock_code"] or "", {})
        climo = next((c for c in (r.get("climatology") or []) if c.get("month") == month), {}) if month else {}
        og = r.get("original_grade")
        rows.append({
            "name": r["name"],
            "location": " > ".join(eff["path_tokens"]),
            "grade_context": eff["eff_grade_context"],
            "grade": f"{r.get('grade_system_code') or ''} {og}".strip() if og else None,
            "data_grade": r.get("data_grade"),
            "rock": eff["eff_rock_code"],
            "rock_notes": rt.get("notes"),
            "seeps": rt.get("seeps"),
            "fragile_when_wet": rt.get("fragile_when_wet"),
            "aspect": eff["eff_aspect"],
            "sun_window": r.get("sun_window_code"),
            "protection": r.get("protection_code"),
            "length_m": r.get("length_m"),
            "pitches_count": r.get("pitches_count"),
            "elevation_m": r.get("elevation_m"),
            "approach_time_min": r.get("approach_time_min"),
            "approach_difficulty": r.get("approach_difficulty"),
            "best_season": r.get("best_season"),
            "stars": r.get("stars"),
            "distance_km": distance_km,
            "month_rainy_days": climo.get("rainy_days"),
            "month_temp_high": climo.get("temp_high"),
            "protection_style": r.get("protection_style"),
            "belays": r.get("belays"),
            "disciplines": sorted(tags.get("disciplines") or []),
            "features": sorted(tags.get("features") or []),
            "character": sorted(tags.get("character") or []),
            "hazards": [{"hazard": h.get("hazard_code"), "evidence": h.get("evidence_span")}
                        for h in (r.get("hazards") or [])],
        })

    # distance NULLS LAST, then data_grade NULLS LAST, then stars DESC NULLS LAST
    rows.sort(key=lambda x: (
        x["distance_km"] is None, x["distance_km"] if x["distance_km"] is not None else 0.0,
        x["data_grade"] is None, x["data_grade"] if x["data_grade"] is not None else 0,
        x["stars"] is None, -(x["stars"] or 0),
    ))
    return rows[:limit]


if __name__ == "__main__":
    store = connect()
    tests = [
        ("sandstone in August", {"rock": "sandstone", "month": 8}),
        ("trad multi-pitch within 700km of London, ≤VS", {
            "disciplines": ["trad", "multi-pitch"],
            "near": {"lat": 51.5, "lon": -0.3, "radius_km": 700},
            "max_data_grade": 5,
        }),
        ("north-facing (shade) in August", {"aspect": "N", "month": 8}),
        ("limestone in August", {"rock": "limestone", "month": 8}),
    ]
    failures = 0
    for label, p in tests:
        rows = search_climbs(store, p)
        print(f"\n== {label} → {len(rows)} result(s)")
        for r in rows[:8]:
            dist = (str(r["distance_km"]) + " km") if r["distance_km"] is not None else ""
            print(f"   {r['name']:34s} {(r['grade'] or ''):14s} {(r['rock'] or ''):10s} "
                  f"{dist:>10s}  {r['location']}")
    try:
        search_climbs(store, {"rock": "kryptonite"})
        print("FAIL: off-dictionary rock accepted"); failures += 1
    except ValueError as e:
        print(f"\n== enum rejection OK: {e}")
    sys.exit(1 if failures else 0)

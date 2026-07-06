#!/usr/bin/env python3
"""Build db/corpus.json — the single authored source of truth (decision #27).

Consolidates the previously-scattered climb/venue sources into ONE file shaped 1:1
with the route/area schema (knowledge/data/route-schema.md), so it is a drop-in
Postgres seed, not a rival store:

  areas[]  — crag / region / country tree (coords, rock, aspect, gradeContext)
  routes[] — climbs; taxonomy VALUES inline; each hangs off an area

Curated vs uncurated is a FIELD, not a file:
  status = publish (curated) | draft (seeded, unverified) | quarantined
  dataGrade = 1..7 confidence

Seeds, in precedence order (publish wins over draft on a slug clash):
  1. Curated DB routes   → status: publish   (the human-verified corpus, via psql)
  2. venues.json crags   → status: publish   (curated area coords/rock/aspect)
  3. multi-pitch.com     → status: draft     (a SEED, not a live source — #27)

Taxonomy DEFINITIONS are NOT copied here — they live in tag-spec.json / taxonomy.md
(#25); entities carry taxonomy VALUES only.

Dependency-free (stdlib). Re-run to refresh:
    python3 db/tools/build_corpus.py
"""
import json
import re
import subprocess
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "db" / "corpus.json"
# A deployed copy under knowledge/ (the only tree GitHub Pages serves), so the
# corpus is fetchable by the Corpus Inspector and clickable from the data map.
DEPLOY_OUT = ROOT / "knowledge" / "data" / "corpus.json"
VENUES_JSON = ROOT / "trip-ni-july-2026" / "venues.json"
MP_URL = "https://multi-pitch.com/data/data.json"
DB_DSN = "postgresql://climbing:climbing@localhost:5432/climbing"
DB_CONTAINER = "climbing-db"          # docker exec fallback if no local psql
TAXONOMY_REF = "knowledge/data/tag-spec.json"


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def latlon(geo: str):
    try:
        a, b = (float(x) for x in str(geo).split(","))
        return [round(a, 4), round(b, 4)]
    except Exception:
        return None


# ── area registry (publish beats draft on a slug clash) ─────────────────────
class Areas:
    def __init__(self):
        self.by_slug = {}

    def add(self, name, kind, *, parent=None, country=None, region=None,
            lat=None, lon=None, rock=None, aspect=None, grade_context=None,
            status="draft", source="derived"):
        if not name:
            return None
        sid = slug(name)
        cur = self.by_slug.get(sid)
        cand = {"id": sid, "name": name, "kind": kind, "parent": parent,
                "country": country, "region": region,
                "geoLocation": [lat, lon] if lat is not None and lon is not None else None,
                "rock": rock, "aspect": aspect, "gradeContext": grade_context,
                "status": status, "source": source}
        if cur is None:
            self.by_slug[sid] = cand
        else:
            # merge: prefer publish; fill any blanks from the newcomer
            if status == "publish" and cur["status"] != "publish":
                cand_fill = {k: (cur.get(k) or cand.get(k)) for k in cand}
                cand_fill.update({"status": "publish", "source": source})
                self.by_slug[sid] = cand_fill
            else:
                for k, v in cand.items():
                    if not cur.get(k) and v:
                        cur[k] = v
        return sid

    def list(self):
        order = {"country": 0, "region": 1, "crag": 2, "sector": 3}
        return sorted(self.by_slug.values(),
                      key=lambda a: (order.get(a["kind"], 9), a["name"]))


MP_SNAPSHOT = ROOT / "db" / "mp-climbs.json"
ROCK_MAP = {"shale & sandstone": "sandstone", "qurtzite": "quartzite", "phonolite": "volcanic"}


def norm_rock(r):
    if not r:
        return None
    k = r.strip().lower()
    return ROCK_MAP.get(k, k)


def route_key(name, lat, lon):
    """Identity for dedup: normalised name + ~11 km geo bucket."""
    return (slug(name or ""), round(lat, 1) if lat is not None else None,
            round(lon, 1) if lon is not None else None)


def load_mp():
    """Rich local snapshot (db/mp-climbs.json, from enrich_from_multipitch.py) — offline,
    done once. Falls back to the shallow public feed only if the snapshot is absent."""
    if MP_SNAPSHOT.exists():
        return json.loads(MP_SNAPSHOT.read_text()).get("climbs", [])
    try:
        req = urllib.request.Request(MP_URL, headers={"User-Agent": "climbing-agent corpus seed"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("climbs", [])
    except Exception as e:
        print(f"[warn] no MP snapshot and fetch failed: {e}", file=sys.stderr)
        return []


def load_gazetteer():
    """The GAZETTEER venue coords, imported from sheet_venues.py so decision #27's
    'coords live in the corpus, not in code' actually holds — these rows land in
    corpus.json and the Python dict becomes a removable duplicate."""
    try:
        import importlib
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        return importlib.import_module("engine.sheet_venues").GAZETTEER
    except Exception as e:
        print(f"[warn] GAZETTEER import failed: {e}", file=sys.stderr)
        return {}


def curated_routes_from_db():
    """The human-verified corpus, read live from Postgres (best effort)."""
    q = r"""
    SELECT json_agg(r) FROM (
      SELECT rr.id, rr.name, rr.path_tokens, rr.eff_grade_context, rr.length_m,
        rr.pitches_count, rr.incline_code, rr.eff_rock_code, rr.eff_aspect,
        rr.grade_system_code, rr.original_grade, rr.trad_grade, rr.tech_grade,
        rr.data_grade, rr.protection_code, rr.protection_style, rr.belays,
        rr.approach_time_min, rr.elevation_m, rr.sun_window_code, rr.best_season, rr.stars,
        ST_Y(rr.geom::geometry) lat, ST_X(rr.geom::geometry) lon,
        (SELECT array_agg(discipline_code) FROM climbing.route_discipline d WHERE d.route_id=rr.id) disciplines,
        (SELECT array_agg(feature_code)    FROM climbing.route_feature   f WHERE f.route_id=rr.id) features,
        (SELECT array_agg(character_code)  FROM climbing.route_character  c WHERE c.route_id=rr.id) AS "character",
        (SELECT array_agg(hazard_code)     FROM climbing.route_hazard     h WHERE h.route_id=rr.id) hazards,
        (SELECT json_agg(json_build_object('month',month,'rainyDays',rainy_days,
           'tempHigh',temp_high,'tempLow',temp_low) ORDER BY month)
           FROM climbing.route_climatology w WHERE w.route_id=rr.id) climatology
      FROM climbing.route_resolved rr WHERE rr.status='publish' ORDER BY rr.id
    ) r;"""
    for cmd in (["psql", DB_DSN, "-tAc", q],
                ["docker", "exec", DB_CONTAINER, "psql", "-U", "climbing", "-d", "climbing", "-tAc", q]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout.strip())
        except Exception:
            continue
    print("[warn] could not read curated routes from the DB — seeding without them",
          file=sys.stderr)
    return []


def build():
    areas = Areas()
    routes = []
    seen = set()  # curated (name+geo) keys → skip their raw multi-pitch twins

    # 1. curated DB routes → publish, and their country/region/crag areas
    curated = curated_routes_from_db()
    for r in curated:
        seen.add(route_key(r.get("name"), r.get("lat"), r.get("lon")))
    for r in curated:
        toks = r.get("path_tokens") or []
        country = toks[0] if len(toks) > 0 else None
        region = toks[1] if len(toks) > 1 else None
        crag = toks[2] if len(toks) > 2 else (region or country)
        if country:
            areas.add(country, "country", status="publish", source="curated")
        if region:
            areas.add(region, "region", parent=slug(country), country=country,
                      status="publish", source="curated")
        crag_id = areas.add(crag, "crag", parent=slug(region or country), country=country,
                            region=region, lat=r.get("lat"), lon=r.get("lon"),
                            rock=r.get("eff_rock_code"), aspect=r.get("eff_aspect"),
                            grade_context=r.get("eff_grade_context"),
                            status="publish", source="curated")
        routes.append({
            "id": r["id"], "area": crag_id, "name": r["name"],
            "status": "publish", "source": "curated", "dataGrade": r.get("data_grade"),
            "originalGrade": r.get("original_grade"), "gradeSys": r.get("grade_system_code"),
            "tradGrade": r.get("trad_grade"), "techGrade": r.get("tech_grade"),
            "length": r.get("length_m"), "pitches": r.get("pitches_count"),
            "incline": r.get("incline_code"), "protection": r.get("protection_code"),
            "protectionStyle": r.get("protection_style"), "belays": r.get("belays"),
            "approachTime": r.get("approach_time_min"), "elevation": r.get("elevation_m"),
            "sunWindow": r.get("sun_window_code"), "bestSeason": r.get("best_season"),
            "stars": r.get("stars"),
            "disciplines": r.get("disciplines") or [], "features": r.get("features") or [],
            "character": r.get("character") or [], "hazards": r.get("hazards") or [],
            "climatology": r.get("climatology") or [],
            "geoLocation": [r.get("lat"), r.get("lon")],
        })

    # 2. venues.json curated crags → publish areas (coords / rock / aspect)
    try:
        for v in json.loads(VENUES_JSON.read_text()).get("venues", []):
            areas.add(v.get("country"), "country", status="publish", source="curated")
            areas.add(v["name"], "crag", parent=slug(v.get("country", "")),
                      country=v.get("country"), lat=v.get("lat"), lon=v.get("lon"),
                      rock=v.get("rock"), aspect=v.get("aspect"),
                      status="publish", source="curated")
    except Exception as e:
        print(f"[warn] venues.json: {e}", file=sys.stderr)

    # 3. multi-pitch.com → SEED routes + cliff areas as draft (uncurated), enriched
    #    from the local site source: rock, incline, aspect, hazards, 12-month weather.
    for c in load_mp():
        ll = latlon(c.get("geoLocation"))
        if route_key(c.get("routeName"), ll[0] if ll else None, ll[1] if ll else None) in seen:
            continue  # a curated (verified) version of this climb already exists
        country, county, cliff = c.get("country"), c.get("county"), c.get("cliff")
        rock, aspect = norm_rock(c.get("rock")), c.get("face")
        if country:
            areas.add(country, "country", status="draft", source="multi-pitch.com")
        if county:
            areas.add(county, "region", parent=slug(country or ""), country=country,
                      status="draft", source="multi-pitch.com")
        area_id = areas.add(cliff, "crag", parent=slug(county or country or ""),
                            country=country, region=county,
                            lat=ll[0] if ll else None, lon=ll[1] if ll else None,
                            rock=rock, aspect=aspect,
                            status="draft", source="multi-pitch.com") if cliff else None
        disc = []
        if (c.get("pitches") or 0) > 1:
            disc.append("multi-pitch")
        if c.get("tradGrade"):
            disc.append("trad")
        routes.append({
            "id": f"mp-{c.get('id')}", "area": area_id, "name": c.get("routeName"),
            "status": "draft", "source": "multi-pitch.com", "dataGrade": c.get("dataGrade"),
            "originalGrade": c.get("originalGrade"), "gradeSys": c.get("gradeSys"),
            "tradGrade": c.get("tradGrade"), "techGrade": c.get("techGrade"),
            "length": c.get("length"), "pitches": c.get("pitches"),
            "incline": c.get("incline"), "approachTime": c.get("approachTime"),
            "approachDifficulty": c.get("approachDifficulty"),
            "disciplines": disc, "features": [], "character": [],
            "hazards": c.get("hazards") or [],
            "climatology": c.get("climatology") or [],
            "description": c.get("description") or "",
            "geoLocation": ll,
        })

    # 4. GAZETTEER venue coords → draft areas (decision #27: coords live in the corpus)
    for name, g in load_gazetteer().items():
        areas.add(name.title(), "crag", lat=g.get("lat"), lon=g.get("lon"),
                  rock=norm_rock(g.get("rock")), aspect=g.get("aspect"),
                  status="draft", source="sheet-gazetteer")

    area_list = areas.list()
    pub_a = sum(a["status"] == "publish" for a in area_list)
    pub_r = sum(r["status"] == "publish" for r in routes)
    corpus = {
        "schemaVersion": "1.0",
        "generated": date.today().isoformat(),
        "note": "Single source of truth for climbs/venues (decision #27). Shaped as the "
                "Postgres seed. Curated = status:publish; seeded/unverified = status:draft.",
        "taxonomyRef": TAXONOMY_REF,
        "counts": {"areas": len(area_list), "areasCurated": pub_a,
                   "routes": len(routes), "routesCurated": pub_r,
                   "routesSeeded": len(routes) - pub_r},
        "areas": area_list,
        "routes": routes,
    }
    payload = json.dumps(corpus, ensure_ascii=False, indent=2) + "\n"
    OUT.write_text(payload)
    DEPLOY_OUT.write_text(payload)          # served copy for the site
    print(f"wrote {OUT.relative_to(ROOT)} + {DEPLOY_OUT.relative_to(ROOT)} — "
          f"{len(area_list)} areas ({pub_a} curated), {len(routes)} routes "
          f"({pub_r} curated, {len(routes)-pub_r} seeded from multi-pitch)")


if __name__ == "__main__":
    build()

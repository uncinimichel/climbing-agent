#!/usr/bin/env python3
"""Export db/corpus.json from the JSON record — the derived corpus the site reads.

Record-first (decision #39, supersedes #34's Postgres-first): db/record/ is the
source of truth — the Curation Studio (curate.py) edits it through store.py.
This script is the read side: a faithful, git-diffable EXPORT of every area and
route (draft, publish and quarantined alike), so

  - corpus.json stays the committed derived view (repo-as-database ethos, #2),
  - the Corpus Inspector and the trip pipeline (#27 pending switch) read one file,
  - every curation session shows up as a reviewable git diff.

Governance fields (#32) ride along: status · source · taggedBy · tagProv ·
curationNotes · needsFieldCheck. Prose rides along too: intro / approach /
pitchInfo + structured pitches[].

Run:  agent/.venv/bin/python db/tools/build_corpus.py
"""
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "db" / "corpus.json"
# A deployed copy under knowledge/ (the only tree GitHub Pages serves), so the
# corpus is fetchable by the Corpus Inspector and clickable from the data map.
DEPLOY_OUT = ROOT / "knowledge" / "data" / "corpus.json"
TAXONOMY_REF = "knowledge/data/tag-spec.json"


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def num(v):
    """Postgres numerics exported as 13.0 — the corpus has always said 13."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


def load_raw(s: Store) -> tuple[list[dict], list[dict]]:
    """The record, reshaped into the rows the old AREAS_Q / ROUTES_Q returned —
    everything downstream (ids, camelCase mapping) is unchanged."""
    areas_raw = []
    for a in s.areas.values():
        areas_raw.append({
            "pg_id": a["id"], "parent_id": a.get("parent_id"), "name": a["name"],
            "kind": a.get("kind"), "path_tokens": a["path_tokens"],
            "eff_grade_context": a.get("eff_grade_context"),
            "grade_context": a.get("grade_context"), "rock_code": a.get("rock_code"),
            "aspect": a.get("aspect"), "lat": a.get("lat"), "lon": a.get("lon"),
            "parent_name": s.areas.get(a.get("parent_id"), {}).get("name"),
        })
    areas_raw.sort(key=lambda a: a["path_tokens"])

    routes_raw = []
    for r in s.routes.values():
        ar = s.areas[r["area_id"]]
        row = {k: r.get(k) for k in (
            "name", "status", "tagged_by", "tag_prov", "curation_notes",
            "needs_field_check", "curated_at", "length_m", "pitches_count",
            "incline_code", "data_grade", "grade_system_code", "original_grade",
            "trad_grade", "tech_grade", "protection_code", "protection_style",
            "belays", "rack", "rope", "escapable", "commitment_code",
            "approach_time_min", "approach_difficulty", "descent_method",
            "descent_abseils", "descent_notes", "elevation_m", "sun_window_code",
            "wind_exposed", "best_season", "stars", "intro_html", "approach_html",
            "pitch_info_html", "area_id", "lat", "lon")}
        row.update({
            "pg_id": r["id"], "path_tokens": ar["path_tokens"], "area_name": ar["name"],
            "timezone": r.get("timezone"),    # the route's OWN column, like rr.timezone was
            "parkings": [{"label": pk.get("label"), "lat": pk.get("lat"), "lon": pk.get("lon")}
                         for pk in sorted(r.get("parkings") or [],
                                          key=lambda p: (p.get("ord") or 0, p.get("id") or 0))],
            "disciplines": sorted((r.get("tags") or {}).get("disciplines", [])),
            "features": sorted((r.get("tags") or {}).get("features", [])),
            "character": sorted((r.get("tags") or {}).get("character", [])),
            "hazards": sorted(h["hazard_code"] for h in r.get("hazards") or []),
            "hazard_evidence": {h["hazard_code"]: {"span": h.get("evidence_span"),
                                                   "url": h.get("source_url")}
                                for h in r.get("hazards") or []},
            "pitch_rows": [{"number": p.get("number"), "length": p.get("length_m"),
                            "gradeSys": p.get("grade_system_code"),
                            "grade": p.get("original_grade"),
                            "description": p.get("description")}
                           for p in sorted(r.get("pitches") or [],
                                           key=lambda p: p.get("number") or 0)],
            "climatology": [{"month": m["month"], "rainyDays": num(m.get("rainy_days")),
                             "tempHigh": num(m.get("temp_high")),
                             "tempLow": num(m.get("temp_low"))}
                            for m in sorted(r.get("climatology") or [],
                                            key=lambda m: m["month"])],
            "refs": [{"source": x.get("source_id"), "id": x.get("external_id"),
                      "url": x.get("url")}
                     for x in sorted(r.get("external_refs") or [],
                                     key=lambda x: (x.get("source_id"), x.get("external_id")))],
        })
        routes_raw.append(row)
    routes_raw.sort(key=lambda r: (r["path_tokens"], r["name"]))
    return areas_raw, routes_raw


def unique_area_ids(areas_raw: list[dict]) -> dict:
    """pg_id → exported id. slug(name), with slug--parentslug (then --2, --3…) on
    collision — duplicate ids silently re-parent routes on restore otherwise."""
    by_pg, taken = {}, set()
    for a in areas_raw:                      # sorted by path_tokens → parents first
        base = slug(a["name"])
        cand = base
        if cand in taken and a.get("parent_name"):
            cand = f"{base}--{slug(a['parent_name'])}"
        n = 2
        while cand in taken:
            cand = f"{base}--{n}"
            n += 1
        taken.add(cand)
        by_pg[a["pg_id"]] = cand
    return by_pg


def export_area(a: dict, ids: dict, parent_pg: dict) -> dict:
    toks = a["path_tokens"] or [a["name"]]
    return {
        "id": ids[a["pg_id"]], "name": a["name"], "kind": a["kind"],
        "parent": ids.get(parent_pg.get(a["pg_id"])),
        "country": toks[0] if len(toks) > 1 else None,
        "region": toks[1] if len(toks) > 2 else None,
        "geoLocation": [round(a["lat"], 4), round(a["lon"], 4)] if a.get("lat") is not None else None,
        "rock": a.get("rock_code"), "aspect": a.get("aspect"),
        "gradeContext": a.get("grade_context"),
        "status": "draft", "source": "record",
    }


def export_route(r: dict, area_ids: dict) -> dict:
    mp_ref = next((x for x in (r.get("refs") or []) if x["source"] == "multipitch"), None)
    rid = f"mp-{mp_ref['id']}" if mp_ref else r["pg_id"]
    out = {
        "id": rid, "pgId": r["pg_id"], "area": area_ids[r["area_id"]], "name": r["name"],
        "status": r["status"], "taggedBy": r["tagged_by"],
        "source": "curated" if r["tagged_by"] == "human" else
                  ("multi-pitch.com" if mp_ref else "crawler"),
        "dataGrade": r.get("data_grade"),
        "originalGrade": r.get("original_grade"), "gradeSys": r.get("grade_system_code"),
        "tradGrade": r.get("trad_grade"), "techGrade": r.get("tech_grade"),
        "length": r.get("length_m"), "pitches": r.get("pitches_count"),
        "incline": r.get("incline_code"),
        "protection": r.get("protection_code"), "protectionStyle": r.get("protection_style"),
        "belays": r.get("belays"), "rack": r.get("rack"), "rope": r.get("rope"),
        "approachTime": r.get("approach_time_min"),
        "approachDifficulty": r.get("approach_difficulty"),
        "descentMethod": r.get("descent_method"),
        "descentAbseils": r.get("descent_abseils"), "descentNotes": r.get("descent_notes"),
        "escapable": r.get("escapable"), "commitment": r.get("commitment_code"),
        "windExposed": r.get("wind_exposed"), "timezone": r.get("timezone"),
        "elevation": r.get("elevation_m"), "sunWindow": r.get("sun_window_code"),
        "bestSeason": r.get("best_season"), "stars": r.get("stars"),
        "disciplines": r.get("disciplines") or [], "features": r.get("features") or [],
        "character": r.get("character") or [], "hazards": r.get("hazards") or [],
        "hazardEvidence": r.get("hazard_evidence") or {},
        "climatology": r.get("climatology") or [],
        "description": r.get("intro_html"), "approach": r.get("approach_html"),
        "pitchInfo": r.get("pitch_info_html"), "pitchRows": r.get("pitch_rows") or [],
        "geoLocation": [round(r["lat"], 4), round(r["lon"], 4)] if r.get("lat") is not None else None,
        "parkings": r.get("parkings") or [],
        "refs": r.get("refs") or [],
    }
    if r.get("tag_prov"):
        out["tagProv"] = r["tag_prov"]
    if r.get("curation_notes"):
        out["curationNotes"] = r["curation_notes"]
    if r.get("needs_field_check"):
        out["needsFieldCheck"] = True
    if r.get("curated_at"):
        out["curatedAt"] = str(r["curated_at"])[:10]
    return out


def build():
    areas_raw, routes_raw = load_raw(Store())

    area_ids = unique_area_ids(areas_raw)
    parent_pg = {a["pg_id"]: a.get("parent_id") for a in areas_raw}
    areas = [export_area(a, area_ids, parent_pg) for a in areas_raw]
    routes = [export_route(r, area_ids) for r in routes_raw]

    # area status: publish if a human-published route hangs under it (walked by
    # record id, immune to name collisions) — mirrors the old curated-area semantics
    pub_pg = set()
    for r in routes_raw:
        if r["status"] == "publish":
            node = r["area_id"]
            while node is not None and node not in pub_pg:
                pub_pg.add(node)
                node = parent_pg.get(node)
    for a, raw in zip(areas, areas_raw):
        if raw["pg_id"] in pub_pg:
            a["status"], a["source"] = "publish", "curated"

    pub_a = sum(a["status"] == "publish" for a in areas)
    by_status = {}
    for r in routes:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    llm_r = sum(r["taggedBy"] == "llm" for r in routes)
    fc = sum(1 for r in routes if r.get("needsFieldCheck"))

    corpus = {
        "schemaVersion": "2.0",
        "generated": date.today().isoformat(),
        "note": "EXPORT of the JSON record (decision #39: db/record/ is the source of "
                "truth — edit via the Curation Studio, not this file). "
                "Governance (#32): suggestions/ranking may only use status:publish + "
                "taggedBy:human rows.",
        "taxonomyRef": TAXONOMY_REF,
        "counts": {"areas": len(areas), "areasCurated": pub_a,
                   "routes": len(routes),
                   "routesCurated": by_status.get("publish", 0),
                   "routesSeeded": by_status.get("draft", 0),
                   "routesQuarantined": by_status.get("quarantined", 0),
                   "routesLlmTagged": llm_r, "routesFieldCheck": fc},
        "areas": areas,
        "routes": routes,
    }
    payload = json.dumps(corpus, ensure_ascii=False, indent=2, default=str) + "\n"
    OUT.write_text(payload)
    DEPLOY_OUT.write_text(payload)          # served copy for the site
    print(f"exported {OUT.relative_to(ROOT)} + {DEPLOY_OUT.relative_to(ROOT)} — "
          f"{len(areas)} areas ({pub_a} curated), {len(routes)} routes "
          f"({by_status.get('publish', 0)} curated, {by_status.get('draft', 0)} draft, "
          f"{by_status.get('quarantined', 0)} quarantined, {llm_r} llm-tagged, {fc} field-check)")


if __name__ == "__main__":
    build()

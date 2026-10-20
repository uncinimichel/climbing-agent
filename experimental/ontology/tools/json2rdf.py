"""Convert the JSON record + ingest runs for a few example crags into RDF
(TriG, one named graph per source) under data/generated/.

    agent/.venv/bin/python experimental/ontology/tools/json2rdf.py

Graphs produced (all under https://climbing-agent.dev/graph/):
    record                 the curated JSON record (corpus/record), reshaped:
                           routes -> climb:Route on a climb:Place; crag facts
                           that today sit on route files are lifted onto the
                           Place (with a conflict report if two routes disagree)
    src/<source>/<run>     one per ingest parsed/<source>.json — SourceRecords
                           exactly as that source states them (never merged)
    enrich/<run>           Open-Meteo normals + dry-warm months per source crag
    llm/<run>              LLM tags with evidence spans, about SourceRecords
    link                   mechanical candidateSameAs between SourceRecords
                           (same normalised name, crags within 1.5 km) — the
                           identity judgment is left to the LLM/human phase
The hand-written data/curated/*.ttl files are loaded by run.py into graph
`curated`; this script does not touch them.

Raw source prose (UKC/theCrag descriptions) goes ONLY into data/generated/,
which is git-ignored — the scraping permission is conditional on raw never
reaching the public repo/site.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rdflib import BNode, Dataset, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS, XSD

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vocab import INGEST_GRADE_SYSTEM_LABELS, code_slug, concept_uri  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RECORD = ROOT / "corpus" / "record"
RUNS = ROOT / "ingest" / "runs"
OUT = Path(__file__).resolve().parents[1] / "data" / "generated"

CLIMB = Namespace("https://climbing-agent.dev/ontology/climb#")
ID = Namespace("https://climbing-agent.dev/id/")
G = Namespace("https://climbing-agent.dev/graph/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
SCHEMA = Namespace("https://schema.org/")

# ---- what to convert -------------------------------------------------------
CRAG_PATHS = [
    "northern-ireland/antrim/fair-head",
    "northern-ireland/mourne-and-down/pigeon-rock",
    "italy/bolzano/vajolet-towers",
]
# (run, source, crag-name predicate) — only crags matching are converted
INGEST = [
    ("20260812-075533-635a", "ukc", lambda n: n == "Fair Head"),
    ("20260813-075337-18f6", "ukc", lambda n: n == "Pigeon Rock"),
    ("20260813-075337-18f6", "irishwiki", lambda n: n == "Pigeon Rock"),
    ("20260813-075338-f886", "thecrag", lambda n: n == "Pigeon"),
]
LLM_RUNS = ["20260812-075533-635a"]

RECORD_SOURCE_IDS = {"ukclimbing": "ukc", "thecrag": "thecrag", "multipitch": "multipitch",
                     "openbeta": "openbeta", "mountainproject": "mountainproject", "irishwiki": "irishwiki"}
SOURCE_LABELS = {"ukc": "UKClimbing", "thecrag": "theCrag", "irishwiki": "Irish Climbing Wiki (wiki.climbing.ie)",
                 "multipitch": "multi-pitch.com", "openbeta": "OpenBeta", "mountainproject": "Mountain Project",
                 "record": "climbing-agent curated record", "open-meteo": "Open-Meteo ERA5 archive",
                 "llm": "LLM tagger (claude)", "curator": "human curator"}

# Place facts that live on ROUTE files in today's record and are lifted to the Place here
LIFTED = ["aspect", "rock_code", "lat", "lon", "elevation_m", "timezone", "approach_html",
          "approach_time_min", "approach_difficulty", "climatology", "parkings", "tile_image", "map_img",
          "sun_window_code", "best_season"]

report: dict[str, list] = defaultdict(list)


def slug(s: str) -> str:
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unsorted"


def norm_name(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"^the ", "", s)


def lit(v, dt=None):
    if dt is not None:
        return Literal(v, datatype=dt)
    return Literal(v)


def dec(v):
    return Literal(str(v), datatype=XSD.decimal)


def grade_node(g, subj, value: str | None, system_code: str | None):
    if not value:
        return
    gn = BNode()
    g.add((subj, CLIMB.grade, gn))
    g.add((gn, RDF.type, CLIMB.Grade))
    g.add((gn, CLIMB.gradeValue, Literal(value)))
    if system_code:
        g.add((gn, CLIMB.gradeSystem, concept_uri("grade_system", system_code)))


def hazard_node(g, subj, code: str, evidence: str | None, source_url: str | None = None):
    hn = BNode()
    g.add((subj, CLIMB.hazard, hn))
    g.add((hn, RDF.type, CLIMB.HazardAssertion))
    g.add((hn, CLIMB.hazardType, concept_uri("hazard", code)))
    if evidence:
        g.add((hn, CLIMB.evidenceSpan, Literal(evidence)))
    if source_url:
        g.add((hn, PROV.wasDerivedFrom, URIRef(source_url)))


def graph_meta(ds: Dataset, guri: URIRef, source_key: str, note: str, derived_from: URIRef | None = None):
    m = ds.graph(G["meta"])
    m.add((guri, RDF.type, PROV.Entity))
    m.add((guri, PROV.wasAttributedTo, ID[f"source/{source_key}"]))
    m.add((guri, PROV.generatedAtTime, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    m.add((guri, DCTERMS.description, Literal(note)))
    if derived_from is not None:
        m.add((guri, PROV.wasDerivedFrom, derived_from))
    src = ID[f"source/{source_key}"]
    m.add((src, RDF.type, CLIMB.Source))
    m.add((src, RDFS.label, Literal(SOURCE_LABELS.get(source_key, source_key))))


# ---------------------------------------------------------------------------
# 1. the curated record, reshaped onto Crag / Place / Route
# ---------------------------------------------------------------------------
def convert_record(ds: Dataset):
    g = ds.graph(G["record"])
    areas = {a["id"]: a for a in json.loads((RECORD / "areas.json").read_text())["areas"]}
    graph_meta(ds, G["record"], "record", "corpus/record JSON, reshaped: place facts lifted off route files")
    for srow in json.loads((RECORD / "taxonomies.json").read_text())["taxonomies"]["source"]:
        skey = RECORD_SOURCE_IDS.get(srow["id"], srow["id"])
        g.add((ID[f"source/{skey}"], RDF.type, CLIMB.Source)); g.add((ID[f"source/{skey}"], RDFS.label, Literal(srow["name"])))
        if srow.get("license"): g.add((ID[f"source/{skey}"], DCTERMS.license, Literal(srow["license"])))
        if srow.get("tos"): g.add((ID[f"source/{skey}"], CLIMB.tos, Literal(srow["tos"])))

    for crag_path in CRAG_PATHS:
        country, region, crag = crag_path.split("/")
        crag_uri = ID[f"crag/{crag_path}"]
        country_uri = ID[f"area/{country}"]
        region_uri = ID[f"area/{country}/{region}"]
        g.add((country_uri, RDF.type, CLIMB.Country)); g.add((country_uri, RDFS.label, Literal(country.replace("-", " ").title())))
        g.add((region_uri, RDF.type, CLIMB.Region)); g.add((region_uri, RDFS.label, Literal(region.replace("-", " ").title())))
        g.add((region_uri, CLIMB.parentArea, country_uri))
        g.add((crag_uri, RDF.type, CLIMB.Crag))
        g.add((crag_uri, CLIMB.parentArea, region_uri))
        g.add((crag_uri, CLIMB.recordPath, Literal(crag_path)))

        files = sorted(p for p in (RECORD / crag_path).glob("*.json"))
        routes = []
        for p in files:
            d = json.loads(p.read_text())
            if "original_grade" not in d:  # e.g. pigeon-rock/ukc-routes.json (a crawl dump, not a route)
                report["non-route files in crag folder"].append(str(p.relative_to(RECORD)))
                continue
            routes.append((p, d))

        # crag label from areas.json rows whose name matches the folder
        crag_rows = [a for a in areas.values() if slug(a["name"].split(",")[0]) == crag]
        label = crag_rows[0]["name"].split(",")[0] if crag_rows else crag.replace("-", " ").title()
        g.add((crag_uri, RDFS.label, Literal(label)))
        if len(crag_rows) > 1:
            report["duplicate area rows for one crag"].append(
                f"{crag}: " + "; ".join(f"id={a['id']} kind={a['kind']} name={a['name']!r} parent={a['parent_id']}" for a in crag_rows))
        for a in crag_rows:
            if a.get("grade_context"):
                g.add((region_uri, CLIMB.gradeContext, Literal(a["grade_context"])))
            if a.get("timezone"):
                g.add((crag_uri, CLIMB.timezone, Literal(a["timezone"])))
            for ref in [] if not a.get("access_notes") else [a["access_notes"]]:
                g.add((crag_uri, CLIMB.accessNotes, Literal(ref)))

        # places = distinct sector names; single-sector crags get one place "main"
        sectors = sorted({(r.get("sector") or "") for _, r in routes})
        multi = len([s for s in sectors if s]) > 1
        place_facts: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
        place_uri_of: dict[str, URIRef] = {}

        for _, r in routes:
            sec = r.get("sector") or ""
            pslug = slug(sec) if (multi and sec) else ("unsorted" if multi else "main")
            if multi and not sec:
                report["routes with no sector on a multi-sector crag"].append(r["name"])
            puri = ID[f"place/{crag_path}/{pslug}"]
            place_uri_of[pslug] = puri
            g.add((puri, RDF.type, CLIMB.Place))
            g.add((puri, RDFS.label, Literal(sec if (multi and sec) else (label if not multi else "Unsorted"))))
            g.add((puri, CLIMB.crag, crag_uri))
            for f in LIFTED:
                v = r.get(f)
                if v in (None, "", [], {}):
                    continue
                place_facts[pslug][f].add(json.dumps(v, sort_keys=True))

        # the areas.json crag row's aspect/rock/lat/lon: only a place fact if there is ONE place
        for a in crag_rows:
            if a["kind"] != "crag":
                continue
            if not multi:
                for f in ("aspect", "rock_code", "lat", "lon"):
                    if a.get(f) is not None:
                        place_facts["main"][f].add(json.dumps(a[f]))
            else:
                stated = {f: a.get(f) for f in ("aspect", "rock_code") if a.get(f)}
                if stated:
                    report["crag-level facts with no place to go (multi-sector crag, no inheritance)"].append(
                        f"{crag}: areas.json says {stated} — needs per-place curation ({len(place_uri_of)} places)")

        for pslug, facts in place_facts.items():
            puri = place_uri_of[pslug]
            for f, vals in facts.items():
                if len(vals) > 1:
                    report["place-fact conflicts between route files"].append(f"{crag_path}/{pslug}.{f}: {len(vals)} distinct values")
                v = json.loads(sorted(vals)[0])
                if f == "aspect": g.add((puri, CLIMB.aspect, Literal(v)))
                elif f == "rock_code": g.add((puri, CLIMB.rockType, concept_uri("rock_type", v)))
                elif f == "lat": g.add((puri, GEO.lat, dec(v)))
                elif f == "lon": g.add((puri, GEO.long, dec(v)))
                elif f == "elevation_m": g.add((puri, CLIMB.elevationM, Literal(int(v))))
                elif f == "timezone": g.add((puri, CLIMB.timezone, Literal(v)))
                elif f == "approach_html": g.add((puri, CLIMB.approachText, Literal(re.sub(r"<[^>]+>", " ", v).strip())))
                elif f == "approach_time_min": g.add((puri, CLIMB.approachTimeMin, Literal(int(v))))
                elif f == "sun_window_code": g.add((puri, CLIMB.sunWindow, concept_uri("sun_window", v)))
                elif f == "climatology":
                    for m in v:
                        mn = BNode()
                        g.add((puri, CLIMB.monthNormals, mn)); g.add((mn, RDF.type, CLIMB.MonthNormals))
                        g.add((mn, CLIMB.month, Literal(int(m["month"]))))
                        if m.get("temp_high") is not None: g.add((mn, CLIMB.tmaxMeanC, dec(m["temp_high"])))
                        if m.get("temp_low") is not None: g.add((mn, CLIMB.tminMeanC, dec(m["temp_low"])))
                        if m.get("rainy_days") is not None: g.add((mn, CLIMB.precipDays, dec(m["rainy_days"])))
                elif f == "parkings":
                    for i, pk in enumerate(v):
                        pk_uri = ID[f"parking/{crag_path}/{slug(pk.get('label') or str(i))}"]
                        g.add((puri, CLIMB.parking, pk_uri)); g.add((pk_uri, RDF.type, CLIMB.Parking))
                        if pk.get("label"): g.add((pk_uri, RDFS.label, Literal(pk["label"])))
                        if pk.get("lat") is not None: g.add((pk_uri, GEO.lat, dec(pk["lat"]))); g.add((pk_uri, GEO.long, dec(pk["lon"])))
                # tile_image / map_img / best_season / approach_difficulty: skipped in this pass

        # routes
        for p, r in routes:
            rpath = str(p.relative_to(RECORD))[:-5]
            ruri = ID[f"route/{rpath}"]
            sec = r.get("sector") or ""
            pslug = slug(sec) if (multi and sec) else ("unsorted" if multi else "main")
            g.add((ruri, RDF.type, CLIMB.Route))
            g.add((ruri, RDFS.label, Literal(r["name"])))
            g.add((ruri, CLIMB.place, place_uri_of[pslug]))
            g.add((ruri, CLIMB.recordPath, Literal(rpath)))
            if r.get("id") is not None: g.add((ruri, CLIMB.recordId, Literal(int(r["id"]))))
            grade_node(g, ruri, r.get("original_grade"), r.get("grade_system_code"))
            if r.get("data_grade") is not None: g.add((ruri, CLIMB.dataGrade, Literal(int(r["data_grade"]))))
            if r.get("length_m"): g.add((ruri, CLIMB.lengthM, Literal(int(r["length_m"]))))
            if r.get("pitches_count"): g.add((ruri, CLIMB.pitchCount, Literal(int(r["pitches_count"]))))
            if r.get("bolts_count") is not None: g.add((ruri, CLIMB.boltsCount, Literal(int(r["bolts_count"]))))
            if r.get("stars") is not None: g.add((ruri, CLIMB.stars, Literal(int(r["stars"]))))
            if r.get("left_right_index") is not None: g.add((ruri, CLIMB.leftRightIndex, Literal(int(r["left_right_index"]))))
            if r.get("protection_code"): g.add((ruri, CLIMB.protectionGrade, concept_uri("protection_grade", r["protection_code"])))
            if r.get("incline_code"): g.add((ruri, CLIMB.incline, concept_uri("incline", r["incline_code"])))
            if r.get("commitment_code"): g.add((ruri, CLIMB.commitmentGrade, concept_uri("commitment_grade", r["commitment_code"])))
            if r.get("status"): g.add((ruri, CLIMB.status, Literal(r["status"])))
            if r.get("tagged_by"): g.add((ruri, CLIMB.taggedBy, Literal(r["tagged_by"])))
            if r.get("needs_field_check") is not None: g.add((ruri, CLIMB.needsFieldCheck, Literal(bool(r["needs_field_check"]))))
            if r.get("intro_html"): g.add((ruri, CLIMB.intro, Literal(re.sub(r"<[^>]+>", " ", r["intro_html"]).strip())))
            tags = r.get("tags") or {}
            for d in tags.get("disciplines") or []: g.add((ruri, CLIMB.discipline, concept_uri("discipline", d)))
            for d in tags.get("features") or []: g.add((ruri, CLIMB.feature, concept_uri("feature", d)))
            for d in tags.get("character") or []: g.add((ruri, CLIMB.character, concept_uri("character", d)))
            for h in r.get("hazards") or []:
                hazard_node(g, ruri, h["hazard_code"], h.get("evidence_span"), h.get("source_url"))
            for fa in r.get("first_ascents") or []:
                g.add((ruri, CLIMB.firstAscent, Literal(", ".join(str(fa.get(k)) for k in ("climber", "year") if fa.get(k)))))
            for i, pt in enumerate(r.get("pitches") or [], start=1):
                n = int(pt.get("number") or i)
                puri = URIRef(f"{ruri}/pitch/{n}")
                g.add((puri, RDF.type, CLIMB.Pitch)); g.add((puri, CLIMB.route, ruri)); g.add((puri, CLIMB.pitchNumber, Literal(n)))
                grade_node(g, puri, pt.get("original_grade"), pt.get("grade_system_code"))
                if pt.get("length_m"): g.add((puri, CLIMB.lengthM, Literal(int(pt["length_m"]))))
                if pt.get("bolts_count") is not None: g.add((puri, CLIMB.boltsCount, Literal(int(pt["bolts_count"]))))
                if pt.get("description"): g.add((puri, CLIMB.description, Literal(pt["description"])))
            for gb in r.get("guidebooks") or []:
                gb_uri = ID[f"guidebook/{gb.get('isbn') or slug(gb['title'])}"]
                g.add((ruri, DCTERMS.references, gb_uri)); g.add((gb_uri, RDF.type, CLIMB.Guidebook))
                g.add((gb_uri, RDFS.label, Literal(gb["title"])))
                if gb.get("isbn"): g.add((gb_uri, CLIMB.isbn, Literal(gb["isbn"])))
                if gb.get("page"): g.add((ruri, CLIMB.page, Literal(f"{gb['title']} p.{gb['page']}")))
            for ref in r.get("references") or []:
                if ref.get("url"): g.add((ruri, DCTERMS.references, URIRef(ref["url"])))
            for x in r.get("external_refs") or []:
                skey = RECORD_SOURCE_IDS.get(x["source_id"], x["source_id"])
                sr = ID[f"src/{skey}/route/{slug(str(x['external_id']))}"]
                g.add((ruri, CLIMB.sourceRecord, sr))
                g.add((sr, RDF.type, CLIMB.SourceRecord)); g.add((sr, CLIMB.source, ID[f"source/{skey}"]))
                g.add((sr, CLIMB.sourceId, Literal(str(x["external_id"]))))
                if x.get("url"): g.add((sr, SCHEMA.url, URIRef(x["url"])))
        report["converted"].append(f"record {crag_path}: {len(routes)} routes, {len(place_uri_of)} places")


# ---------------------------------------------------------------------------
# 2. ingest runs — SourceRecords, one graph per (source, run)
# ---------------------------------------------------------------------------
def convert_ingest(ds: Dataset) -> dict[str, list[dict]]:
    """Returns crag source records per key for the link phase."""
    crag_records: list[dict] = []
    for run, source, want in INGEST:
        parsed = RUNS / run / "parsed" / f"{source}.json"
        if not parsed.exists():
            report["missing"].append(str(parsed)); continue
        d = json.loads(parsed.read_text())
        guri = G[f"src/{source}/{run}"]
        g = ds.graph(guri)
        graph_meta(ds, guri, source, f"ingest run {run} parsed/{source}.json — verbatim, one source's view", URIRef(f"urn:climbing-agent:run:{run}"))
        enriched = RUNS / run / "enriched" / f"{source}.json"
        enr = {c["source_id"]: c for c in json.loads(enriched.read_text())["crags"]} if enriched.exists() else {}
        eg = ds.graph(G[f"enrich/{run}"])
        if enr:
            graph_meta(ds, G[f"enrich/{run}"], "open-meteo", f"ingest run {run} enriched/: climate normals + dry-warm rule (mechanical)", guri)

        for c in d["crags"]:
            if not want(c["name"]):
                continue
            curi = ID[f"src/{source}/crag/{slug(c['source_id'])}"]
            g.add((curi, RDF.type, CLIMB.SourceRecord)); g.add((curi, CLIMB.recordKind, Literal("crag")))
            g.add((curi, CLIMB.source, ID[f"source/{source}"])); g.add((curi, CLIMB.sourceId, Literal(c["source_id"])))
            g.add((curi, RDFS.label, Literal(c["name"])))
            if c.get("url"): g.add((curi, SCHEMA.url, URIRef(c["url"])))
            if c.get("lat") is not None: g.add((curi, GEO.lat, dec(c["lat"]))); g.add((curi, GEO.long, dec(c["lon"])))
            if c.get("rock_type"): g.add((curi, CLIMB.rockType, concept_uri("rock_type", c["rock_type"])))
            if c.get("aspect"): g.add((curi, CLIMB.aspect, Literal(c["aspect"])))
            if c.get("country"): g.add((curi, SCHEMA.addressCountry, Literal(c["country"])))
            if c.get("region"): g.add((curi, SCHEMA.addressRegion, Literal(c["region"])))
            if c.get("description"): g.add((curi, CLIMB.description, Literal(c["description"])))
            crag_records.append({"uri": curi, "source": source, "name": c["name"], "lat": c.get("lat"), "lon": c.get("lon"), "routes": []})

            for r in c["routes"]:
                ruri = ID[f"src/{source}/route/{slug(str(r['source_id']))}"]
                g.add((ruri, RDF.type, CLIMB.SourceRecord)); g.add((ruri, CLIMB.recordKind, Literal("route")))
                g.add((ruri, CLIMB.source, ID[f"source/{source}"])); g.add((ruri, CLIMB.sourceId, Literal(str(r["source_id"]))))
                g.add((ruri, RDFS.label, Literal(r["name"]))); g.add((ruri, CLIMB.ofCragRecord, curi))
                if r.get("url"): g.add((ruri, SCHEMA.url, URIRef(r["url"])))
                gr = r.get("grade") or {}
                sys_label = gr.get("system")
                grade_node(g, ruri, gr.get("value"), INGEST_GRADE_SYSTEM_LABELS.get(sys_label) if sys_label else None)
                if sys_label and sys_label not in INGEST_GRADE_SYSTEM_LABELS:
                    report["unmapped ingest grade-system labels"].append(sys_label)
                if r.get("length_m"): g.add((ruri, CLIMB.lengthM, Literal(int(r["length_m"]))))
                if r.get("pitches"): g.add((ruri, CLIMB.pitchCount, Literal(int(r["pitches"]))))
                if r.get("stars") is not None: g.add((ruri, CLIMB.stars, Literal(int(r["stars"]))))
                if r.get("bolts_count") is not None: g.add((ruri, CLIMB.boltsCount, Literal(int(r["bolts_count"]))))
                if r.get("protection"): g.add((ruri, CLIMB.protectionGrade, concept_uri("protection_grade", r["protection"])))
                for dsc in r.get("disciplines") or []: g.add((ruri, CLIMB.discipline, concept_uri("discipline", dsc)))
                if r.get("fa"): g.add((ruri, CLIMB.firstAscent, Literal(r["fa"])))
                if r.get("description"): g.add((ruri, CLIMB.description, Literal(r["description"])))
                crag_records[-1]["routes"].append({"uri": ruri, "name": r["name"], "grade": gr.get("value")})

            e = enr.get(c["source_id"], {}).get("enrichment")
            if e:
                if e.get("sun_window"): eg.add((curi, CLIMB.sunWindow, concept_uri("sun_window", e["sun_window"])))
                for m in (e.get("season") or {}).get("dry_warm_months") or []: eg.add((curi, CLIMB.dryWarmMonth, Literal(int(m))))
                for mm, vals in ((e.get("climate") or {}).get("monthly") or {}).items():
                    mn = BNode()
                    eg.add((curi, CLIMB.monthNormals, mn)); eg.add((mn, RDF.type, CLIMB.MonthNormals)); eg.add((mn, CLIMB.month, Literal(int(mm))))
                    if vals.get("tmax_mean_c") is not None: eg.add((mn, CLIMB.tmaxMeanC, dec(vals["tmax_mean_c"])))
                    if vals.get("tmin_mean_c") is not None: eg.add((mn, CLIMB.tminMeanC, dec(vals["tmin_mean_c"])))
                    if vals.get("precip_days") is not None: eg.add((mn, CLIMB.precipDays, dec(vals["precip_days"])))
                    if vals.get("wind_max_mean_kmh") is not None: eg.add((mn, CLIMB.windMaxMeanKmh, dec(vals["wind_max_mean_kmh"])))
            report["converted"].append(f"src/{source}/{run} {c['name']}: {len(c['routes'])} routes" + (" + enrichment" if e else ""))
    return crag_records


# ---------------------------------------------------------------------------
# 3. LLM tags (llm-curated/inventory.json) — assertions about SourceRecords
# ---------------------------------------------------------------------------
def convert_llm(ds: Dataset):
    for run in LLM_RUNS:
        inv_p = RUNS / run / "llm-curated" / "inventory.json"
        if not inv_p.exists():
            report["missing"].append(str(inv_p)); continue
        inv = json.loads(inv_p.read_text())
        guri = G[f"llm/{run}"]
        g = ds.graph(guri)
        graph_meta(ds, guri, "llm", f"ingest run {run} llm-curated: tags with verbatim evidence, model={inv.get('model')}", G[f"src/ukc/{run}"])
        n = 0
        for c in inv["crags"]:
            if c["name"] != "Fair Head":
                continue
            for r in c["routes"]:
                t = r.get("tags")
                if not t:
                    continue
                for ref in r.get("refs") or []:
                    ruri = ID[f"src/{ref['source']}/route/{slug(str(ref['source_id']))}"]
                    for f in t.get("feature") or []: g.add((ruri, CLIMB.feature, concept_uri("feature", f)))
                    for ch in t.get("character") or []: g.add((ruri, CLIMB.character, concept_uri("character", ch)))
                    if t.get("incline"): g.add((ruri, CLIMB.incline, concept_uri("incline", t["incline"])))
                    if t.get("protection"): g.add((ruri, CLIMB.protectionGrade, concept_uri("protection_grade", t["protection"])))
                    for h in t.get("hazards") or []:
                        hazard_node(g, ruri, h["code"], h.get("evidence"), ref.get("url"))
                    n += 1
        report["converted"].append(f"llm/{run}: {n} tagged source routes")


# ---------------------------------------------------------------------------
# 4. link — mechanical candidate identities between SourceRecords
# ---------------------------------------------------------------------------
def haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def link(ds: Dataset, crags: list[dict]):
    g = ds.graph(G["link"])
    graph_meta(ds, G["link"], "record", "mechanical candidateSameAs: same normalised route name, crag records within 1.5 km or sharing a name token. Judgment left to LLM/human.")
    # cluster crag records
    clusters: list[list[dict]] = []
    for c in crags:
        placed = False
        for cl in clusters:
            for o in cl:
                near = c["lat"] is not None and o["lat"] is not None and haversine_km((c["lat"], c["lon"]), (o["lat"], o["lon"])) < 1.5
                tok = set(norm_name(c["name"]).split()) & set(norm_name(o["name"]).split())
                if near or (tok and c["source"] != o["source"]):
                    cl.append(c); placed = True; break
            if placed: break
        if not placed:
            clusters.append([c])
    n_pairs = 0
    for cl in clusters:
        if len(cl) < 2:
            continue
        for i, a in enumerate(cl):
            for b in cl[i + 1:]:
                g.add((a["uri"], CLIMB.candidateSameAs, b["uri"]))
                by_name = defaultdict(list)
                for r in b["routes"]: by_name[norm_name(r["name"])].append(r)
                for r in a["routes"]:
                    for o in by_name.get(norm_name(r["name"]), []):
                        g.add((r["uri"], CLIMB.candidateSameAs, o["uri"]))
                        conf = 0.9 if (r["grade"] and r["grade"] == o["grade"]) else 0.6
                        st = BNode()  # confidence as a small reified statement
                        g.add((st, RDF.type, RDF.Statement)); g.add((st, RDF.subject, r["uri"])); g.add((st, RDF.predicate, CLIMB.candidateSameAs)); g.add((st, RDF.object, o["uri"]))
                        g.add((st, CLIMB.matchConfidence, dec(conf)))
                        n_pairs += 1
        report["converted"].append("link cluster: " + " + ".join(f"{c['source']}:{c['name']}" for c in cl))
    report["converted"].append(f"link: {n_pairs} candidate route identities")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ds = Dataset()
    for pfx, ns in (("climb", CLIMB), ("id", ID), ("g", G), ("geo", GEO), ("schema", SCHEMA), ("prov", PROV), ("dcterms", DCTERMS), ("vocab", "https://climbing-agent.dev/vocab/")):
        ds.bind(pfx, ns)
    convert_record(ds)
    crags = convert_ingest(ds)
    convert_llm(ds)
    link(ds, crags)

    total = 0
    for ctx in ds.graphs():
        if len(ctx) == 0:
            continue
        name = str(ctx.identifier).replace(str(G), "").replace("/", "__")
        single = Dataset(); single.namespace_manager = ds.namespace_manager
        tg = single.graph(ctx.identifier)
        for t in ctx: tg.add(t)
        single.serialize(OUT / f"{name}.trig", format="trig")
        total += len(ctx)
        print(f"  {name:32s} {len(ctx):7d} triples")
    print(f"total {total} triples -> {OUT}")
    (OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print("\nREPORT")
    for k, v in report.items():
        print(f"- {k} ({len(v)})")
        for x in v[:12]: print(f"    {x}")


if __name__ == "__main__":
    main()

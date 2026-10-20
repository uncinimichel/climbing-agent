"""Generate vocab.ttl — the SKOS concept schemes — from the record's
taxonomies.json + grades.json. Never hand-edit vocab.ttl; edit the JSON
(the human source of truth per taxonomy.md) and re-run.

Each taxonomy value -> one skos:Concept with prefLabel, definition (the
`meaning`), the extra metadata the record carries (seeps, safety_critical,
sort_order...) and, where we know them, skos:exactMatch / closeMatch to
the OSM climbing:* tag value and theCrag / OpenBeta names.

Usage: agent/.venv/bin/python experimental/ontology/tools/vocab.py
"""
from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

ROOT = Path(__file__).resolve().parents[3]
RECORD = ROOT / "corpus" / "record"
OUT = Path(__file__).resolve().parents[1] / "vocab.ttl"

VOCAB = "https://climbing-agent.dev/vocab/"
CLIMB = Namespace("https://climbing-agent.dev/ontology/climb#")
OSM = Namespace("https://wiki.openstreetmap.org/wiki/Tag:")
THECRAG = Namespace("https://www.thecrag.com/tag/")
OPENBETA = Namespace("https://openbeta.io/schema/")

# Hand-curated outside mappings (SKOS mapping relations). Extend here.
# OSM values from wiki.openstreetmap.org/wiki/Climbing (fetched 2026-09-06).
MAPPINGS: dict[tuple[str, str], list[tuple[str, URIRef]]] = {
    ("discipline", "trad"): [("exact", OSM["climbing:trad=yes"]), ("exact", OPENBETA["ClimbType/trad"])],
    ("discipline", "sport"): [("exact", OSM["climbing:sport=yes"]), ("exact", OPENBETA["ClimbType/sport"])],
    ("discipline", "bouldering"): [("exact", OSM["climbing:boulder=yes"]), ("exact", OPENBETA["ClimbType/bouldering"])],
    ("discipline", "multi-pitch"): [("exact", OSM["climbing:multipitch=yes"])],
    ("discipline", "ice"): [("exact", OSM["climbing:ice=yes"]), ("exact", OPENBETA["ClimbType/ice"])],
    ("discipline", "mixed"): [("exact", OSM["climbing:mixed=yes"]), ("exact", OPENBETA["ClimbType/mixed"])],
    ("discipline", "aid"): [("exact", OSM["climbing:aid=yes"]), ("exact", OPENBETA["ClimbType/aid"])],
    ("discipline", "deepwatersolo"): [("exact", OSM["climbing:deepwater=yes"]), ("exact", OPENBETA["ClimbType/deepwatersolo"])],
    ("discipline", "alpine"): [("exact", OPENBETA["ClimbType/alpine"])],
    ("discipline", "snow"): [("exact", OPENBETA["ClimbType/snow"])],
    ("rock_type", "limestone"): [("exact", OSM["climbing:rock=limestone"])],
    ("rock_type", "granite"): [("exact", OSM["climbing:rock=granite"])],
    ("rock_type", "basalt"): [("exact", OSM["climbing:rock=basalt"])],
    ("rock_type", "sandstone"): [("exact", OSM["climbing:rock=sandstone"])],
    ("rock_type", "gneiss"): [("exact", OSM["climbing:rock=gneiss"])],
    ("rock_type", "dolomite"): [("exact", OSM["climbing:rock=dolomite"])],
    ("rock_type", "dolerite"): [("close", OSM["climbing:rock=dolerite"])],
    ("rock_type", "gritstone"): [("close", OSM["climbing:rock=gritstone"])],
    ("hazard", "loose"): [("close", OSM["climbing:hazard:loose_rock=yes"])],
    ("hazard", "rockfall"): [("exact", OSM["climbing:hazard:rockfall_zone=yes"])],
    ("hazard", "seepage"): [("close", OSM["climbing:hazard:wet=yes"])],
    ("hazard", "polished"): [("close", OSM["climbing:hazard:slippery_rock=yes"])],
    ("hazard", "nesting-birds"): [("close", OSM["climbing:hazard:animal_nest=yes"])],
    ("hazard", "grassLedges"): [("close", OSM["climbing:hazard:vegetation=yes"])],
    ("protection_grade", "PG"): [("exact", OPENBETA["SafetyEnum/PG"])],
    ("protection_grade", "PG-13"): [("exact", OPENBETA["SafetyEnum/PG13"])],
    ("protection_grade", "R"): [("exact", OPENBETA["SafetyEnum/R"])],
    ("protection_grade", "X"): [("exact", OPENBETA["SafetyEnum/X"])],
    ("protection_grade", "runout"): [("exact", OPENBETA["SafetyEnum/runout"]), ("close", OSM["climbing:hazard:long_runout=yes"])],
    ("protection_grade", "terrain"): [("exact", OPENBETA["SafetyEnum/terrain"])],
    ("protection_grade", "UNSPECIFIED"): [("exact", OPENBETA["SafetyEnum/UNSPECIFIED"])],
    ("incline", "Slab"): [("exact", OSM["climbing:inclination:slab=yes"])],
    ("incline", "Vertical"): [("exact", OSM["climbing:inclination:vertical=yes"])],
    ("incline", "Overhanging"): [("exact", OSM["climbing:inclination:overhang=yes"])],
    ("grade_system", "UIAA"): [("exact", OSM["climbing:grade:uiaa"]), ("exact", OPENBETA["GradeType/uiaa"])],
    ("grade_system", "FS"): [("exact", OSM["climbing:grade:french"]), ("exact", OPENBETA["GradeType/french"])],
    ("grade_system", "YDS"): [("exact", OSM["climbing:grade:yds_class"]), ("exact", OPENBETA["GradeType/yds"])],
    ("grade_system", "BAS"): [("exact", OSM["climbing:grade:british_adjectival"])],
    ("grade_system", "Font"): [("exact", OPENBETA["GradeType/font"])],
    ("grade_system", "V"): [("exact", OSM["climbing:grade:hueco"]), ("exact", OPENBETA["GradeType/vscale"])],
    ("grade_system", "EW"): [("exact", OPENBETA["GradeType/ewbank"])],
    ("grade_system", "WI"): [("exact", OSM["climbing:grade:ice"]), ("exact", OPENBETA["GradeType/wi"])],
    ("grade_system", "SX"): [("exact", OSM["climbing:grade:saxon"])],
    ("grade_system", "N"): [("exact", OSM["climbing:grade:norwegian"])],
    ("grade_system", "BRZ"): [("exact", OPENBETA["GradeType/brazilianCrux"])],
    ("sun_window", "afternoon"): [("close", THECRAG["afternoon-sun"])],
    ("sun_window", "morning"): [("close", THECRAG["morning-sun"])],
    ("sun_window", "all-day"): [("close", THECRAG["all-day-sun"])],
    ("sun_window", "shade"): [("close", THECRAG["shady"])],
}

# The straw-man approach-difficulty words (curator handbook, still open)
APPROACH_DIFFICULTY = [
    ("flat-path", "Flat path, trainers fine."),
    ("uphill-walk", "Uphill walk on a path."),
    ("steep-rough", "Steep or rough ground, no path in places."),
    ("scramble", "Hands-on scrambling to reach the base."),
    ("technical", "Technical approach: abseil, Tyrolean, boat or tidal timing."),
]

# Ingest adapters emit these labels for grade.system; map onto record codes.
INGEST_GRADE_SYSTEM_LABELS = {
    "uk_adjectival_tech": "BAS", "uk_tech": "BAS", "french": "FS", "uiaa": "UIAA",
    "yds": "YDS", "font": "Font", "vscale": "V", "ewbank": "EW", "wi": "WI",
}


def code_slug(code: str) -> str:
    """URI-safe form of a taxonomy code. Case and hyphens preserved so that
    vocab:discipline/multi-pitch, vocab:grade_system/BAS, vocab:hazard/grassLedges
    read exactly like the record; only spaces/punctuation become '-'
    ('Slab & Vertical' -> 'Slab-Vertical'). skos:notation keeps the verbatim code."""
    import re
    return re.sub(r"[^A-Za-z0-9._~-]+", "-", code).strip("-")


def concept_uri(scheme: str, code: str) -> URIRef:
    return URIRef(f"{VOCAB}{scheme}/{code_slug(code)}")


def scheme_uri(scheme: str) -> URIRef:
    return URIRef(f"{VOCAB}{scheme}")


def build() -> Graph:
    g = Graph()
    g.bind("skos", SKOS); g.bind("climb", CLIMB); g.bind("dcterms", DCTERMS)
    g.bind("osm", OSM); g.bind("thecrag", THECRAG); g.bind("openbeta", OPENBETA)
    g.bind("vocab", VOCAB)

    tax = json.loads((RECORD / "taxonomies.json").read_text())["taxonomies"]
    grades = json.loads((RECORD / "grades.json").read_text())

    def add_scheme(name: str, title: str, source_note: str):
        s = scheme_uri(name)
        g.add((s, RDF.type, SKOS.ConceptScheme))
        g.add((s, DCTERMS.title, Literal(title)))
        g.add((s, DCTERMS.source, Literal(source_note)))
        return s

    def add_concept(scheme: str, code: str, label: str | None, meaning: str | None, extra: dict):
        s = scheme_uri(scheme)
        c = concept_uri(scheme, code)
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, SKOS.inScheme, s))
        g.add((c, SKOS.topConceptOf, s))
        g.add((c, SKOS.notation, Literal(code)))
        g.add((c, SKOS.prefLabel, Literal(label or code, lang="en")))
        if meaning:
            g.add((c, SKOS.definition, Literal(meaning, lang="en")))
        for k, v in extra.items():
            if v is None or v == "" or k in ("code", "meaning", "name"):
                continue
            if isinstance(v, bool):
                g.add((c, CLIMB[k], Literal(v)))
            elif isinstance(v, (int, float)):
                g.add((c, CLIMB[k], Literal(v)))
            elif isinstance(v, list):
                for x in v:
                    g.add((c, CLIMB[k], Literal(str(x))))
            else:
                g.add((c, CLIMB[k], Literal(str(v))))
        for kind, target in MAPPINGS.get((scheme, code), []):
            g.add((c, SKOS.exactMatch if kind == "exact" else SKOS.closeMatch, target))
        return c

    for name, values in tax.items():
        if name == "source":
            continue  # sources become climb:Source agents in the data, not concepts
        add_scheme(name, f"climbing-agent {name}", "corpus/record/taxonomies.json")
        for v in values:
            add_concept(name, v["code"], v.get("name"), v.get("meaning") or v.get("notes"), v)

    add_scheme("grade_system", "Grade systems", "corpus/record/grades.json#systems")
    for sysm in grades["systems"]:
        add_concept("grade_system", sysm["code"], sysm["name"],
                    f"{sysm['name']} — e.g. {sysm['example']} ({sysm['region']})",
                    {"discipline": sysm.get("discipline"), "region": sysm.get("region"), "example": sysm.get("example")})

    add_scheme("approach_difficulty", "Approach difficulty (described enum)", "knowledge/curator-handbook.md (words still open)")
    for code, meaning in APPROACH_DIFFICULTY:
        add_concept("approach_difficulty", code, code.replace("-", " "), meaning, {})

    # Aspect stays a datatype (compass string) in this pass — mirrors the record.
    return g


if __name__ == "__main__":
    g = build()
    g.serialize(OUT, format="turtle")
    schemes = len(set(g.subjects(RDF.type, SKOS.ConceptScheme)))
    concepts = len(set(g.subjects(RDF.type, SKOS.Concept)))
    mapped = len(set(s for s, _, _ in g.triples((None, SKOS.exactMatch, None))) | set(s for s, _, _ in g.triples((None, SKOS.closeMatch, None))))
    print(f"vocab.ttl: {schemes} schemes, {concepts} concepts, {mapped} with outside mappings, {len(g)} triples -> {OUT}")

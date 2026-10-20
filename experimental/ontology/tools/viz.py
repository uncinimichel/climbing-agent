"""Export a focused subgraph as JSON for the HTML graph view (viz.html).

    agent/.venv/bin/python experimental/ontology/tools/viz.py          # -> data/generated/viz.json + viz.html

Two neighbourhoods, chosen because they show what a graph view is FOR:
  * Fair Head: crag header, its independent places, parkings, the curated
    routes on the 6 curated places (colour = which named graph asserted it)
  * Pigeon Rock: the three source crag records and the candidateSameAs
    web between their routes, plus the one curated route (Virgo)
Nodes carry their facts so the page can show them on click. Source prose
is NOT exported (raw stays private).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import load  # noqa: E402
from rdflib import Namespace, URIRef  # noqa: E402
from rdflib.namespace import RDF, RDFS  # noqa: E402

CLIMB = Namespace("https://climbing-agent.dev/ontology/climb#")
ID = "https://climbing-agent.dev/id/"
G = "https://climbing-agent.dev/graph/"
SKIP_PROPS = {str(CLIMB.description)}


def short(u: str) -> str:
    return (u.replace(ID, "").replace(G, "g:").replace("https://climbing-agent.dev/vocab/", "")
             .replace("https://climbing-agent.dev/ontology/climb#", "climb:")
             .replace("http://www.w3.org/2000/01/rdf-schema#", "rdfs:")
             .replace("http://www.w3.org/2003/01/geo/wgs84_pos#", "geo:")
             .replace("http://www.w3.org/ns/prov#", "prov:").replace("https://schema.org/", "schema:"))


def main():
    ds = load()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges = set()

    def kind_of(u: URIRef) -> str:
        for t in ds.objects(u, RDF.type):
            k = short(str(t)).replace("climb:", "")
            if k in ("Crag", "Place", "Route", "Parking", "SourceRecord", "Pitch", "Source"):
                if k == "SourceRecord":
                    rk = ds.value(u, CLIMB.recordKind)
                    return f"Source{str(rk).title()}" if rk else k
                return k
        return "Other"

    def add_node(u: URIRef, graph: str):
        k = str(u)
        if k in nodes:
            return
        facts = []
        for g in ds.graphs():
            for p, o in g.predicate_objects(u):
                if str(p) in SKIP_PROPS or p == RDF.type:
                    continue
                if isinstance(o, URIRef) and str(o).startswith(ID) and kind_of(o) != "Other":
                    continue  # structural edges shown as edges, not facts
                val = short(str(o)) if isinstance(o, URIRef) else str(o)
                if (o, RDF.type, CLIMB.Grade) in ds or (o, RDF.type, CLIMB.HazardAssertion) in ds or (o, RDF.type, CLIMB.MonthNormals) in ds:
                    # inline the blank-node value
                    inner = ", ".join(f"{short(str(pp))}={short(str(oo)) if isinstance(oo, URIRef) else oo}" for pp, oo in ds.predicate_objects(o) if pp != RDF.type)
                    val = inner
                facts.append({"p": short(str(p)), "v": val[:160], "g": short(str(g.identifier))})
        label = ds.value(u, RDFS.label)
        nodes[k] = {"id": k, "label": str(label) if label else short(k), "kind": kind_of(u), "graph": graph, "facts": facts}

    def add_edge(a: URIRef, p: URIRef, b: URIRef, graph: str):
        key = (str(a), str(p), str(b))
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": str(a), "to": str(b), "label": short(str(p)), "graph": graph})

    def graph_of(a, p, b) -> str:
        for g in ds.graphs():
            if (a, p, b) in g:
                return short(str(g.identifier))
        return "?"

    # --- Fair Head neighbourhood
    crag = URIRef(ID + "crag/northern-ireland/antrim/fair-head")
    add_node(crag, "g:record")
    curated_places = [p for p in ds.subjects(CLIMB.crag, crag) if any(True for _ in ds.graph(URIRef(G + "curated")).predicate_objects(p))]
    for p in ds.subjects(CLIMB.crag, crag):
        add_node(p, graph_of(p, CLIMB.crag, crag)); add_edge(p, CLIMB.crag, crag, graph_of(p, CLIMB.crag, crag))
        for pk in ds.objects(p, CLIMB.parking):
            add_node(pk, "g:curated"); add_edge(p, CLIMB.parking, pk, "g:curated")
        if p in curated_places:
            for r in ds.subjects(CLIMB.place, p):
                add_node(r, "g:record"); add_edge(r, CLIMB.place, p, "g:record")
                for sr in ds.objects(r, CLIMB.sourceRecord):
                    add_node(sr, "g:record"); add_edge(r, CLIMB.sourceRecord, sr, "g:record")

    # --- Pigeon Rock identity web
    for sc in ds.subjects(CLIMB.recordKind, None):
        lbl = str(ds.value(sc, RDFS.label) or "")
        if ds.value(sc, CLIMB.recordKind) == None or str(ds.value(sc, CLIMB.recordKind)) != "crag" or not lbl.lower().startswith("pigeon"):
            continue
        add_node(sc, graph_of(sc, RDF.type, CLIMB.SourceRecord))
        for o in ds.objects(sc, CLIMB.candidateSameAs):
            add_node(o, graph_of(o, RDF.type, CLIMB.SourceRecord)); add_edge(sc, CLIMB.candidateSameAs, o, "g:link")
        for r in ds.subjects(CLIMB.ofCragRecord, sc):
            if any(True for _ in ds.objects(r, CLIMB.candidateSameAs)) or any(True for _ in ds.subjects(CLIMB.candidateSameAs, r)):
                add_node(r, graph_of(r, RDF.type, CLIMB.SourceRecord)); add_edge(r, CLIMB.ofCragRecord, sc, graph_of(r, CLIMB.ofCragRecord, sc))
                for o in ds.objects(r, CLIMB.candidateSameAs):
                    add_node(o, graph_of(o, RDF.type, CLIMB.SourceRecord)); add_edge(r, CLIMB.candidateSameAs, o, "g:link")
    pcrag = URIRef(ID + "crag/northern-ireland/mourne-and-down/pigeon-rock")
    add_node(pcrag, "g:record")
    for p in ds.subjects(CLIMB.crag, pcrag):
        add_node(p, "g:record"); add_edge(p, CLIMB.crag, pcrag, "g:record")
        for r in ds.subjects(CLIMB.place, p):
            add_node(r, "g:record"); add_edge(r, CLIMB.place, p, "g:record")
            for sr in ds.objects(r, CLIMB.sourceRecord):
                add_node(sr, "g:record"); add_edge(r, CLIMB.sourceRecord, sr, "g:record")

    out = {"nodes": list(nodes.values()), "edges": edges,
           "graphs": sorted({n["graph"] for n in nodes.values()} | {e["graph"] for e in edges})}
    gen = Path(__file__).resolve().parents[1] / "data" / "generated"
    (gen / "viz.json").write_text(json.dumps(out, ensure_ascii=False))
    tpl = (Path(__file__).resolve().parents[1] / "viz.template.html").read_text()
    (gen / "viz.html").write_text(tpl.replace("/*DATA*/", json.dumps(out, ensure_ascii=False)))
    print(f"{len(nodes)} nodes, {len(edges)} edges -> {gen / 'viz.html'}")


if __name__ == "__main__":
    main()

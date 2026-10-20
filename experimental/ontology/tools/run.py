"""Load ontology + vocab + generated + curated data, validate with SHACL,
run every query in queries/*.rq and print tables with timings.

    agent/.venv/bin/python experimental/ontology/tools/run.py            # everything
    agent/.venv/bin/python experimental/ontology/tools/run.py validate   # SHACL only
    agent/.venv/bin/python experimental/ontology/tools/run.py query q02  # one query
    agent/.venv/bin/python experimental/ontology/tools/run.py inject     # prove the shapes fire
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from pyshacl import validate
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

HERE = Path(__file__).resolve().parents[1]
CLIMB = Namespace("https://climbing-agent.dev/ontology/climb#")
G = Namespace("https://climbing-agent.dev/graph/")


def load() -> Dataset:
    t = time.time()
    ds = Dataset(default_union=True)
    ds.parse(HERE / "climb.ttl", format="turtle", publicID=str(G["ontology"]))
    ds.parse(HERE / "vocab.ttl", format="turtle", publicID=str(G["vocab"]))
    for f in sorted((HERE / "data" / "generated").glob("*.trig")):
        ds.parse(f, format="trig")
    cur = ds.graph(G["curated"])
    for f in sorted((HERE / "data" / "curated").glob("*.ttl")):
        cur.parse(f, format="turtle")
    n = sum(len(c) for c in ds.graphs())
    print(f"loaded {n} triples in {len(list(ds.graphs()))} graphs ({time.time() - t:.2f}s)")
    return ds


def union(ds: Dataset) -> Graph:
    """SHACL and most queries want the merged view: one graph with everything."""
    g = Graph()
    for c in ds.graphs():
        for t in c:
            g.add(t)
    return g


def shacl(data: Graph, label="data") -> bool:
    shapes = Graph().parse(HERE / "shapes.ttl", format="turtle")
    t = time.time()
    conforms, report_graph, text = validate(data, shacl_graph=shapes, inference="none", advanced=True, allow_warnings=True)
    dt = time.time() - t
    # count by severity
    SH = Namespace("http://www.w3.org/ns/shacl#")
    sev = {}
    for r in report_graph.subjects(RDF.type, SH.ValidationResult):
        s = str(report_graph.value(r, SH.resultSeverity)).split("#")[-1]
        sev[s] = sev.get(s, 0) + 1
    print(f"SHACL {label}: conforms={conforms} {sev} ({dt:.2f}s)")
    if not conforms or sev:
        # group messages
        msgs = {}
        for r in report_graph.subjects(RDF.type, SH.ValidationResult):
            m = str(report_graph.value(r, SH.resultMessage))
            s = str(report_graph.value(r, SH.resultSeverity)).split("#")[-1]
            f = str(report_graph.value(r, SH.focusNode))
            msgs.setdefault((s, m), []).append(f)
        for (s, m), nodes in sorted(msgs.items()):
            print(f"  [{s}] {len(nodes):4d}  {m}")
            for n in nodes[:3]:
                print(f"            {n.replace('https://climbing-agent.dev/id/', 'id:')}")
    return conforms


def run_queries(g, only: str | None = None):
    for q in sorted((HERE / "queries").glob("*.rq")):
        if only and only not in q.name:
            continue
        text = q.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        t = time.time()
        res = g.query(text)
        rows = list(res)
        dt = time.time() - t
        print(f"\n== {q.name}: {title}  [{len(rows)} rows, {dt:.2f}s]")
        if not rows:
            continue
        vars_ = [str(v) for v in res.vars]
        widths = [len(v) for v in vars_]
        cells = []
        for r in rows[:25]:
            row = []
            for i, v in enumerate(r):
                s = "" if v is None else str(v)
                s = s.replace("https://climbing-agent.dev/id/", "id:").replace("https://climbing-agent.dev/vocab/", "").replace("https://climbing-agent.dev/graph/", "g:")
                s = s[:48]
                widths[i] = max(widths[i], len(s)); row.append(s)
            cells.append(row)
        print("  " + " | ".join(v.ljust(w) for v, w in zip(vars_, widths)))
        print("  " + "-+-".join("-" * w for w in widths))
        for row in cells:
            print("  " + " | ".join(c.ljust(w) for c, w in zip(row, widths)))
        if len(rows) > 25:
            print(f"  ... {len(rows) - 25} more")


def inject(g: Graph):
    """Add deliberately bad triples and show each rule firing."""
    ID = "https://climbing-agent.dev/id/"
    bad = Graph()
    r = URIRef(ID + "route/test/bad-route")
    place = URIRef(ID + "place/northern-ireland/antrim/fair-head/the-prow")
    bad.add((r, RDF.type, CLIMB.Route)); bad.add((r, CLIMB.place, place))
    bad.add((r, URIRef("http://www.w3.org/2000/01/rdf-schema#label"), Literal("Bad Route")))
    bad.add((r, CLIMB.rockType if False else CLIMB.aspect, Literal("N")))                    # place fact on a route
    bad.add((r, CLIMB.discipline, URIRef("https://climbing-agent.dev/vocab/discipline/via-ferrata-x")))  # off-vocabulary
    bad.add((r, CLIMB.status, Literal("publish"))); bad.add((r, CLIMB.taggedBy, Literal("llm")))  # publish without human
    bad.add((r, CLIMB.stars, Literal(5)))                                                       # stars out of range
    gn = URIRef(ID + "route/test/bad-route/grade")
    bad.add((r, CLIMB.grade, gn)); bad.add((gn, CLIMB.gradeValue, Literal("6a+")))
    bad.add((gn, CLIMB.gradeSystem, URIRef("https://climbing-agent.dev/vocab/grade_system/BAS")))  # French value, BAS system
    hn = URIRef(ID + "route/test/bad-route/hazard/1")
    bad.add((r, CLIMB.hazard, hn)); bad.add((hn, CLIMB.hazardType, URIRef("https://climbing-agent.dev/vocab/hazard/tidal")))  # no evidence
    crag = URIRef(ID + "crag/northern-ireland/antrim/fair-head")
    bad.add((crag, CLIMB.aspect, Literal("N")))                                                 # inheritance smuggled onto the header
    merged = g + bad
    print("\n-- injected 8 deliberate violations --")
    shacl(merged, label="with injected errors")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    ds = load()
    g = union(ds)
    if cmd in ("all", "validate"):
        shacl(g)
    if cmd in ("all", "query"):
        run_queries(ds, sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd in ("all", "inject"):
        inject(g)

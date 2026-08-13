"""The scrape CLI — each verb is a future REST endpoint on the ingest API
(designed 2026-08-11; job-based because tree-walk scrapes take minutes-to-
hours and a web API can't block):

    python -m ingest start  --bbox S,W,N,E --source ukc,thecrag,openbeta \
                            [--max-pages N] [--max-crags N] [--root URL] [--follow]
    python -m ingest status <run-id>
    python -m ingest result <run-id> [--source X]     # combined JSON to stdout
    python -m ingest resume <run-id> [--follow]
    python -m ingest list

start detaches a worker process by default (--follow keeps it in the
foreground); the run directory (ingest/runs/<id>/) is the whole job state, so
status/result/resume only ever read/extend that directory.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import geo
from .runstore import Run
from .sources import REGISTRY


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingest")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="start a new scrape run")
    s.add_argument("--bbox", required=True, help="south,west,north,east")
    s.add_argument("--source", required=True,
                   help=f"comma-separated: {','.join(REGISTRY)} or 'all'")
    s.add_argument("--max-pages", type=int, default=None)
    s.add_argument("--max-crags", type=int, default=None)
    s.add_argument("--root", default=None,
                   help="walk root URL for tree sources (thecrag)")
    s.add_argument("--follow", action="store_true", help="run in the foreground")

    for name in ("status", "result", "resume"):
        sp = sub.add_parser(name)
        sp.add_argument("run_id")
        if name == "result":
            sp.add_argument("--source", default=None)
        if name == "resume":
            sp.add_argument("--follow", action="store_true")
            sp.add_argument("--max-pages", type=int, default=None, help="raise/replace the cap")
            sp.add_argument("--max-crags", type=int, default=None, help="raise/replace the cap")

    c = sub.add_parser("chatter", help="SerpAPI per-crag chatter run (separate schema)")
    c.add_argument("--crag", action="append", default=[], help="seed crag name (repeatable)")
    c.add_argument("--from-run", default=None,
                   help="seed with every crag name from this scrape run's inventories")
    c.add_argument("--window", default="w2", help="Google tbs qdr window (default w2 = 2 weeks)")
    c.add_argument("--num", type=int, default=20)
    c.add_argument("--force", action="store_true", help="ignore the shared-quota guard")

    sv = sub.add_parser("survey", help="region-level multi-lens SerpAPI discovery sweep (mechanical)")
    sv.add_argument("--region", required=True, help='region name, e.g. "Marche"')
    sv.add_argument("--num", type=int, default=20)
    sv.add_argument("--lang", default="en", choices=["en", "it"], help="lens language pack")
    sv.add_argument("--force", action="store_true", help="ignore the shared-quota guard")

    ln = sub.add_parser("link", help="link a chatter run's docs to known crags")
    ln.add_argument("run_id", help="chatter run id")
    ln.add_argument("--against", default="",
                    help="comma-separated scrape run ids to match against (corpus record always included)")

    e = sub.add_parser("enrich", help="static enrichment (climate/wind/season/sun) — no LLM")
    e.add_argument("run_id")

    m = sub.add_parser("llm", help="LLM curation: dedupe/merge + taxonomy tags -> llm-curated/")
    m.add_argument("run_id", help="primary run (output lands here)")
    m.add_argument("--with", dest="with_runs", default="",
                   help="comma-separated additional run ids to merge in")
    m.add_argument("--model", default="sonnet")
    m.add_argument("--batch", type=int, default=20)
    m.add_argument("--max-llm-routes", type=int, default=None,
                   help="cap the number of routes sent to the model (testing knob)")

    k = sub.add_parser("keyed", help="store crawl + curated output under the canonical S3 record key scheme")
    k.add_argument("run_id")

    sub.add_parser("list", help="list runs")
    w = sub.add_parser("_work", help=argparse.SUPPRESS)  # internal: the worker process
    w.add_argument("run_id")

    a = p.parse_args(argv)
    return {"start": _start, "status": _status, "result": _result,
            "resume": _resume, "list": _list, "_work": _work,
            "chatter": _chatter, "survey": _survey, "link": _link,
            "enrich": _enrich, "llm": _llm, "keyed": _keyed}[a.cmd](a)


def _start(a) -> int:
    bbox = geo.parse_bbox(a.bbox)
    sources = list(REGISTRY) if a.source == "all" else a.source.split(",")
    unknown = [s for s in sources if s not in REGISTRY]
    if unknown:
        print(f"unknown source(s) {unknown}; have: {list(REGISTRY)}", file=sys.stderr)
        return 2
    caps = {"max_pages": a.max_pages, "max_crags": a.max_crags}
    roots = {s: a.root for s in sources} if a.root else {}  # tree/index sources use it, geo sources ignore it
    run = Run.create(bbox, sources, caps, roots)
    print(f"run: {run.run_id}  ({run.dir})")
    return _launch(run, a.follow)


def _resume(a) -> int:
    run = Run.load(a.run_id)
    m = run.manifest
    changed = False
    for cap in ("max_pages", "max_crags"):
        v = getattr(a, cap)
        if v is not None:
            m["caps"][cap] = v
            changed = True
    if changed:
        from .runstore import _atomic_write
        _atomic_write(run.manifest_path, m)
    # a capped/failed source gets another go under the (possibly raised) caps;
    # its capped marker is stale the moment we relaunch
    st = run.state()
    for s in m["sources"]:
        if m["status"][s] in ("capped", "failed"):
            st[s]["capped"] = None
            st[s]["error"] = None
            run.set_status(s, "pending")
    run.save_state(st)
    return _launch(run, a.follow)


def _launch(run: Run, follow: bool) -> int:
    if follow:
        from .runner import work_run
        work_run(run)
        return _status_code(run)
    # stdout -> devnull (run.log() already writes every line to log.txt; keeping
    # stdout on the same file doubled each line); stderr -> log for uncaught crashes
    log = open(run.dir / "log.txt", "a")
    subprocess.Popen([sys.executable, "-m", "ingest", "_work", run.run_id],
                     cwd=Path(__file__).resolve().parent.parent,
                     stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
    print(f"worker detached — watch with: python -m ingest status {run.run_id}")
    return 0


def _work(a) -> int:
    run = Run.load(a.run_id)
    from .runner import work_run
    work_run(run)
    return _status_code(run)


def _status(a) -> int:
    run = Run.load(a.run_id)
    m, st = run.manifest, run.state()
    print(f"run {m['run_id']}  bbox={m['bbox']}  caps={m['caps']}")
    for s in m["sources"]:
        t = st[s]
        line = (f"  {s:<9} {m['status'][s]:<8} {t['pages_fetched']:>4} pages  "
                f"{t['crags']:>4} crags  {t['routes']:>5} routes  {len(t['pending']):>4} pending")
        if t.get("capped"):
            line += f"  [{t['capped']}]"
        if t.get("error"):
            line += f"  ERROR: {t['error']}"
        print(line)
    return _status_code(run)


def _status_code(run: Run) -> int:
    return 1 if any(v == "failed" for v in run.manifest["status"].values()) else 0


def _result(a) -> int:
    run = Run.load(a.run_id)
    m = run.manifest
    sources = [a.source] if a.source else m["sources"]
    out = {"run_id": m["run_id"], "bbox": m["bbox"], "status": m["status"],
           "inventories": {}}
    for s in sources:
        parsed = run.load_parsed(s)
        if parsed:
            out["inventories"][s] = parsed
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


def _chatter(a) -> int:
    from .chatter import run_chatter
    seeds = list(a.crag)
    if a.from_run:
        src_run = Run.load(a.from_run)
        for f in (src_run.dir / "parsed").glob("*.json"):
            for c in json.loads(f.read_text()).get("crags") or []:
                if c["name"] not in seeds:
                    seeds.append(c["name"])
    if not seeds:
        print("no seeds: pass --crag and/or --from-run", file=sys.stderr)
        return 2
    run = run_chatter(seeds, a.window, a.num, a.force)
    print(f"run: {run.run_id}  ({run.dir})")
    return 0


def _survey(a) -> int:
    from .chatter import run_survey
    run = run_survey(a.region, a.num, a.force, a.lang)
    print(f"run: {run.run_id}  ({run.dir})")
    return 0


def _link(a) -> int:
    from .chatter import link_chatter
    against = [r for r in a.against.split(",") if r]
    out = link_chatter(a.run_id, against)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


def _enrich(a) -> int:
    from .enrich import enrich_run
    summary = enrich_run(a.run_id)
    json.dump(summary, sys.stdout, indent=2)
    print()
    return 0


def _llm(a) -> int:
    from .llm import llm_curate
    with_runs = [r for r in a.with_runs.split(",") if r]
    counts = llm_curate(a.run_id, with_runs, a.model, a.batch, a.max_llm_routes)
    json.dump(counts, sys.stdout, indent=2)
    print()
    return 0


def _keyed(a) -> int:
    from .keyed import key_run
    report = key_run(a.run_id)
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


def _list(a) -> int:
    for m in Run.list_runs():
        print(f"{m['run_id']}  bbox={m['bbox']}  sources={','.join(m['sources'])}  "
              f"status={m['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

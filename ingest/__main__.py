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

    sub.add_parser("list", help="list runs")
    w = sub.add_parser("_work", help=argparse.SUPPRESS)  # internal: the worker process
    w.add_argument("run_id")

    a = p.parse_args(argv)
    return {"start": _start, "status": _status, "result": _result,
            "resume": _resume, "list": _list, "_work": _work}[a.cmd](a)


def _start(a) -> int:
    bbox = geo.parse_bbox(a.bbox)
    sources = list(REGISTRY) if a.source == "all" else a.source.split(",")
    unknown = [s for s in sources if s not in REGISTRY]
    if unknown:
        print(f"unknown source(s) {unknown}; have: {list(REGISTRY)}", file=sys.stderr)
        return 2
    caps = {"max_pages": a.max_pages, "max_crags": a.max_crags}
    roots = {"thecrag": a.root} if a.root else {}
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


def _list(a) -> int:
    for m in Run.list_runs():
        print(f"{m['run_id']}  bbox={m['bbox']}  sources={','.join(m['sources'])}  "
              f"status={m['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

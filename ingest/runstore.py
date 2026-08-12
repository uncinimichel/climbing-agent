"""One scrape run = one directory under ingest/runs/<run-id>/ (git-ignored —
raw scrapes must never reach the public repo, per the theCrag/UKC permission
terms; syncing raw/ to the private store is a separate explicit step).

    manifest.json          run params + per-source status (the API's run object)
    state.json             per-source frontier: pending items + done keys — the
                           resumability contract; saved after every item
    raw/<source>/<key>.json   verbatim payload per fetched item
    parsed/<source>.json   the shared-schema inventory (side by side per source)
    log.txt                worker log (start --follow tails it live)

Writes are atomic (tmp + rename) so a killed worker never leaves a half-written
state file — the whole job model leans on that.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def item_key(item: dict) -> str:
    """Stable identity of one unit of work — dedups the frontier and names the
    raw capture file."""
    ident = item.get("id") or item.get("url") or json.dumps(item, sort_keys=True)
    return hashlib.sha1(f"{item['kind']}:{ident}".encode()).hexdigest()[:16]


class Run:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.dir = RUNS_DIR / run_id
        self.manifest_path = self.dir / "manifest.json"
        self.state_path = self.dir / "state.json"

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def create(cls, bbox, sources: list[str], caps: dict, roots: dict,
               kind: str = "scrape") -> "Run":
        stamp = time.strftime("%Y%m%d-%H%M%S")
        run = cls(f"{stamp}-{secrets.token_hex(2)}")
        (run.dir / "raw").mkdir(parents=True)
        (run.dir / "parsed").mkdir()
        _atomic_write(run.manifest_path, {
            "run_id": run.run_id,
            "kind": kind,                         # scrape (bbox inventory) | chatter (serp mentions)
            "created_at": _now(),
            "bbox": list(bbox) if bbox else None,
            "sources": sources,
            "caps": caps,
            "roots": roots,                       # per-source override, e.g. thecrag walk root
            "status": {s: "pending" for s in sources},
        })
        _atomic_write(run.state_path, {s: {"pending": [], "done": [], "planned": False,
                                           "pages_fetched": 0, "crags": 0, "routes": 0,
                                           "capped": None, "error": None}
                      for s in sources})
        return run

    @classmethod
    def load(cls, run_id: str) -> "Run":
        run = cls(run_id)
        if not run.manifest_path.exists():
            raise FileNotFoundError(f"no such run: {run_id} (looked in {RUNS_DIR})")
        return run

    @classmethod
    def list_runs(cls) -> list[dict]:
        out = []
        if RUNS_DIR.exists():
            for d in sorted(RUNS_DIR.iterdir()):
                m = d / "manifest.json"
                if m.exists():
                    out.append(json.loads(m.read_text()))
        return out

    # -- manifest/state ------------------------------------------------------
    @property
    def manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text())

    def set_status(self, source: str, status: str) -> None:
        m = self.manifest
        m["status"][source] = status
        _atomic_write(self.manifest_path, m)

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def save_state(self, state: dict) -> None:
        _atomic_write(self.state_path, state)

    # -- payloads ------------------------------------------------------------
    def save_raw(self, source: str, item: dict, payload) -> None:
        d = self.dir / "raw" / source
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / f"{item_key(item)}.json",
                      {"item": item, "fetched_at": _now(), "payload": payload})

    def load_raw(self, source: str, item: dict):
        p = self.dir / "raw" / source / f"{item_key(item)}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def save_parsed(self, source: str, bbox, crags: list[dict], capped) -> None:
        _atomic_write(self.dir / "parsed" / f"{source}.json", {
            "run_id": self.run_id, "source": source, "bbox": list(bbox),
            "generated_at": _now(),
            "counts": {"crags": len(crags), "routes": sum(len(c["routes"]) for c in crags)},
            "capped": capped,          # never truncate silently — say what was cut
            "crags": crags,
        })

    def load_parsed(self, source: str) -> dict | None:
        p = self.dir / "parsed" / f"{source}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def log(self, msg: str) -> None:
        line = f"[{_now()}] {msg}"
        with open(self.dir / "log.txt", "a") as f:
            f.write(line + "\n")
        print(line, flush=True)

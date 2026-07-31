#!/usr/bin/env python3
"""The crawl frontier — the mechanical area→crag→route ledger.

This is the answer to "how do we keep track of area → climbing": one row per
node in a source's tree, and the worker walks it **breadth-first** (area →
child area → crag → route). Every row carries its own fetch/tag status, so the
process can be started, stopped, or killed at any point with nothing lost —
all state lives in the file, never in memory. That is the whole pattern: a
durable work queue with per-node status = a resumable crawler.

It replaces the Postgres `crawl_frontier` table (the retired corpus/sql/040_crawl.sql)
with the same columns and the same claim → complete → fail lifecycle, backed by
corpus/record/crawl-frontier.json (decision #39: the JSON record IS the database).
Single-writer by design — one worker process at a time — so no row-level locking
is needed; durability comes from atomic tmp+rename writes, exactly like store.py.

Source-agnostic: OpenBeta, theCrag, UKC and the SerpAPI social-discovery source
all enqueue rows here and the worker treats them uniformly. `kind` distinguishes
an `area` row (fetch discovers children/routes) from a `route`/`candidate` row
(fetch already done at enqueue time, only tagging left).

CLI:
    python ingest/frontier.py --status                # counts, all sources
    python ingest/frontier.py --status --source openbeta
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTIER_PATH = ROOT / "corpus" / "record" / "crawl-frontier.json"

# Lifecycle vocabularies — kept identical to the retired SQL table so the 257
# already-crawled rows stay valid and readable.
FETCH_STATES = ("pending", "in_progress", "done", "failed")
TAG_STATES = ("pending", "in_progress", "done", "failed", "needs_review", "not_applicable")
STALE_LEASE_MINUTES = 30
MAX_ATTEMPTS = 3

# The full column set of a frontier row, with defaults. Anything the worker
# hasn't computed yet is null — never absent — so git diffs stay honest and the
# schema is self-documenting.
_ROW_DEFAULTS = {
    "id": None,
    "source_id": None,
    "external_id": None,
    "kind": None,                 # 'area' | 'route' | 'candidate'
    "parent_frontier_id": None,   # tree link — the area/crag this node hangs under
    "corpus_area_id": None,       # anchor into corpus areas (int id or slug) for mapping
    "area_id": None,              # store area id once mapped
    "route_id": None,             # store route id once mapped
    "path": None,                 # human breadcrumb: "USA > California > Yosemite"
    "fetch_status": "pending",
    "tag_status": "not_applicable",
    "passes_filter": None,        # did the multipitch-trad/alpine filter keep it
    "raw_capture_path": None,     # gitignored cache path — NEVER inside corpus/record/
    "attempts": 0,
    "flagged_fields": None,
    "last_error": None,
    "created_at": None,
    "claimed_at": None,
    "last_attempted_at": None,
    "fetched_at": None,
    "tagged_at": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Frontier:
    def __init__(self, path: Path = FRONTIER_PATH):
        self.path = Path(path)
        doc = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.note = doc.get("note", "crawl frontier — see ingest/frontier.py")
        self.schema = doc.get("schema", 1)
        self.rows: list[dict] = doc.get("frontier", [])
        # (source_id, external_id) → row, for O(1) dedup on enqueue
        self._by_key = {(r["source_id"], r["external_id"]): r for r in self.rows}

    # ── persistence: atomic tmp+rename, stable key order for clean diffs ──────
    def save(self) -> None:
        body = json.dumps(
            {"schema": self.schema, "note": self.note, "frontier": self.rows},
            ensure_ascii=False, indent=1, sort_keys=True,
        ) + "\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(body)
        tmp.replace(self.path)

    def _next_id(self) -> int:
        return max((r["id"] for r in self.rows), default=0) + 1

    # ── enqueue — the only way rows are born; dedups on (source, external_id) ─
    def enqueue(self, source_id: str, external_id: str, kind: str, **fields) -> dict:
        """Add a node if this (source, external_id) isn't already tracked, and
        return the row (existing or new). Idempotent: re-running a seed or a
        parent's child-discovery never double-inserts."""
        key = (source_id, str(external_id))
        if key in self._by_key:
            return self._by_key[key]
        row = dict(_ROW_DEFAULTS)
        row.update(fields)
        row.update(
            id=self._next_id(), source_id=source_id, external_id=str(external_id),
            kind=kind, created_at=_now(),
        )
        self.rows.append(row)
        self._by_key[key] = row
        return row

    # ── claiming — mark rows in progress so a resumed run doesn't redo them ───
    def reclaim_stale(self, source_id: str, minutes: int = STALE_LEASE_MINUTES) -> int:
        """A previous run crashed mid-batch: its in_progress rows are stuck.
        Anything leased longer than `minutes` ago goes back to pending."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        n = 0
        for r in self.rows:
            if (r["source_id"] == source_id and r["fetch_status"] == "in_progress"
                    and r["claimed_at"] and datetime.fromisoformat(r["claimed_at"]) < cutoff):
                r["fetch_status"], r["claimed_at"] = "pending", None
                n += 1
        if n:
            self.save()
        return n

    def claim_fetch(self, source_id: str, batch_size: int) -> list[dict]:
        batch = [r for r in self.rows
                 if r["source_id"] == source_id and r["fetch_status"] == "pending"][:batch_size]
        for r in batch:
            r.update(fetch_status="in_progress", claimed_at=_now(), last_attempted_at=_now())
        if batch:
            self.save()
        return batch

    def claim_tag(self, source_id: str, batch_size: int) -> list[dict]:
        batch = [r for r in self.rows
                 if r["source_id"] == source_id and r["fetch_status"] == "done"
                 and r["tag_status"] == "pending"][:batch_size]
        for r in batch:
            r.update(tag_status="in_progress", last_attempted_at=_now())
        if batch:
            self.save()
        return batch

    # ── completion / failure ─────────────────────────────────────────────────
    def complete_fetch(self, row: dict, *, area_id=None, route_id=None,
                       passes_filter=None, tag_status=None, raw_capture_path=None) -> None:
        row.update(fetch_status="done", fetched_at=_now())
        if area_id is not None:
            row["area_id"] = area_id
        if route_id is not None:
            row["route_id"] = route_id
        if passes_filter is not None:
            row["passes_filter"] = passes_filter
        if raw_capture_path is not None:
            row["raw_capture_path"] = raw_capture_path
        if tag_status is not None:
            row["tag_status"] = tag_status
        self.save()

    def complete_tag(self, row: dict, *, status: str = "done", flagged_fields=None) -> None:
        row.update(tag_status=status, tagged_at=_now(), flagged_fields=flagged_fields or None)
        self.save()

    def fail(self, row: dict, stage: str, error: str) -> None:
        """Retry up to MAX_ATTEMPTS, then park the row as failed (never silently
        dropped — CONVENTIONS.md quota discipline). `stage` is 'fetch' or 'tag'."""
        col = "fetch_status" if stage == "fetch" else "tag_status"
        row["attempts"] += 1
        row[col] = "pending" if row["attempts"] < MAX_ATTEMPTS else "failed"
        row["last_error"] = (error or "")[:2000]
        if col == "fetch_status":
            row["claimed_at"] = None
        self.save()

    # ── introspection ────────────────────────────────────────────────────────
    def counts(self, source_id: str | None = None) -> dict:
        rows = [r for r in self.rows if source_id is None or r["source_id"] == source_id]
        by_source: dict = {}
        for r in rows:
            s = by_source.setdefault(r["source_id"], {"total": 0, "fetch": {}, "tag": {}})
            s["total"] += 1
            s["fetch"][r["fetch_status"]] = s["fetch"].get(r["fetch_status"], 0) + 1
            s["tag"][r["tag_status"]] = s["tag"].get(r["tag_status"], 0) + 1
        return by_source


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--status", action="store_true", help="print row counts and exit")
    p.add_argument("--source", help="limit --status to one source id")
    args = p.parse_args()

    f = Frontier()
    if args.status:
        counts = f.counts(args.source)
        if not counts:
            print("(frontier empty)")
            return
        for source, c in sorted(counts.items()):
            print(f"\n{source}: {c['total']} rows")
            print(f"  fetch: {c['fetch']}")
            print(f"  tag:   {c['tag']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Ingest worker — walks the frontier breadth-first for one source, mapping and
(optionally) LLM-tagging what it finds into validated `status: draft` records.

Pipeline per row:  fetch → discover children (enqueue) → map (mechanical) →
                   [tag (LLM)] → validate against the store schema → draft

    # OpenBeta (name-seeded), dry-run against the live API, writing NOTHING:
    python ingest/worker.py --source openbeta --seed "Yosemite" --country USA --dry-run
    # theCrag / UKC (URL-seeded, headless browser), with LLM tagging:
    python ingest/worker.py --source thecrag --seed "https://www.thecrag.com/…/fair-head/area/12518215" \
        --path "Ireland > Antrim > Fair Head" --dry-run --tag
    python ingest/worker.py --source ukclimbing --seed "https://www.ukclimbing.com/logbook/crags/fair_head-17029/" \
        --path "Northern Ireland > Antrim > Fair Head" --dry-run --tag

`--dry-run` (the safe default while the draft-area landing policy is undecided —
see ingest/README.md) runs against a scratch copy of the frontier and an
in-memory store: it fetches, maps, tags and VALIDATES every draft, then prints a
summary — but never touches corpus/record/. Drop it to actually land drafts.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "corpus" / "tools"))

import map as mapping  # noqa: E402
import tag as tagging  # noqa: E402
from drafts import DraftStore  # noqa: E402
from frontier import FRONTIER_PATH, Frontier  # noqa: E402
from sources import openbeta, thecrag, ukc  # noqa: E402
from store import Store  # noqa: E402

# Each source module implements the same small interface (SOURCE_ID, NEEDS_BROWSER,
# fetch, children, map_routes; openbeta also has seed_area for name lookup). The
# worker below is source-agnostic — it only talks to this registry.
SOURCES = {s.SOURCE_ID: s for s in (openbeta, thecrag, ukc)}

SCRATCH_FRONTIER = ROOT / "ingest" / ".cache" / "frontier-dryrun.json"


def _route_id(external_id: str) -> int:
    """A stable integer route id from a source's external id — the numeric id
    itself when the source uses one (UKC/theCrag), else a deterministic CRC of
    the string (OpenBeta uuids), so re-runs overwrite the same holding-pen draft."""
    ext = str(external_id)
    return int(ext) if ext.isdigit() else (zlib.crc32(ext.encode()) & 0x7FFFFFFF)


class _AreaMinter:
    """In-memory area creation so mapped routes have a real store area_id to
    reference (store.validate requires area_id ∈ store.areas). In --dry-run
    these live only in memory; a committing run is where the landing policy
    (inject vs holding-pen) actually applies — see README."""
    def __init__(self, store: Store):
        self.store = store
        self._next = max(store.areas, default=0) + 1
        self._by_key: dict[str, int] = {}

    def ensure(self, external_id: str, name: str, path: str, source_id: str,
               lat=None, lon=None, grade_context=None) -> int:
        key = f"{source_id}:{external_id}"
        if key in self._by_key:
            return self._by_key[key]
        aid = self._next
        self._next += 1
        self.store.areas[aid] = {
            "id": aid, "name": name, "kind": "crag", "parent_id": None,
            "lat": lat, "lon": lon, "grade_context": grade_context, "aspect": None,
            "rock_code": None, "timezone": None, "access_notes": None,
            "_ingest_path": path, "_ingest_source": source_id,
        }
        self._by_key[key] = aid
        return aid


def run(source: str, seed: str | None, path: str | None, country: str, dry_run: bool,
        do_tag: bool, batch_size: int, max_cycles: int) -> None:
    src = SOURCES.get(source)
    if src is None:
        sys.exit(f"unknown source {source!r}; wired: {sorted(SOURCES)}")

    # dry-run mutates a scratch frontier + an in-memory store — the record is never touched
    if dry_run:
        SCRATCH_FRONTIER.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FRONTIER_PATH, SCRATCH_FRONTIER)
    f = Frontier(SCRATCH_FRONTIER if dry_run else FRONTIER_PATH)
    store = Store()
    minter = _AreaMinter(store)                       # dry-run only: in-memory areas to validate against
    draftstore = None if dry_run else DraftStore(store)
    enums = tagging.enums_from_store(store)
    stats = {"areas_fetched": 0, "children_found": 0, "climbs_seen": 0,
             "kept": 0, "review": 0, "dropped": 0, "validated": 0, "invalid": 0,
             "committed": 0, "tagged": 0, "flagged": 0}
    drafts: list[dict] = []
    committed_key = None
    errors: list[str] = []

    if seed:
        is_url = seed.startswith(("http://", "https://"))
        if hasattr(src, "seed_area") and not is_url:      # openbeta: resolve a name → uuid
            m = src.seed_area(seed, country)
            if not m:
                sys.exit(f"no real {source} match for {seed!r} in {country!r}")
            f.enqueue(source, m["uuid"], "area", path=" > ".join(m["pathTokens"]),
                      tag_status="not_applicable")
            print(f"seeded: {' > '.join(m['pathTokens'])}  ({m['totalClimbs']} climbs)")
        else:                                              # thecrag/ukc: seed a URL + breadcrumb
            if not is_url:
                sys.exit(f"{source} is seeded by URL — pass --seed <url> [--path \"A > B > Crag\"]")
            f.enqueue(source, seed, "area", path=path or "", tag_status="not_applicable")
            print(f"seeded: {seed}" + (f"  ({path})" if path else ""))
        f.save()

    session, browser_cm = None, None
    if src.NEEDS_BROWSER:
        from browser_fetch import BrowserSession
        browser_cm = BrowserSession()
        session = browser_cm.__enter__()

    try:
        for _ in range(max_cycles):
            f.reclaim_stale(source)
            batch = f.claim_fetch(source, batch_size)
            if not batch:
                break
            for row in batch:
                try:
                    raw = src.fetch(row["external_id"], session)
                except Exception as e:  # one bad node must not kill the walk
                    f.fail(row, "fetch", str(e))
                    errors.append(f"fetch {row['external_id']}: {e}")
                    continue
                stats["areas_fetched"] += 1

                # discover child areas → enqueue for the next cycle (breadth-first).
                # total is None for sources that don't publish counts (theCrag) — enqueue anyway.
                for child in src.children(raw):
                    if child.get("total") is None or child["total"] > 0:
                        stats["children_found"] += 1
                        child_path = f"{row['path']} > {child['name']}" if row["path"] else child["name"]
                        f.enqueue(source, child["external_id"], "area",
                                  parent_frontier_id=row["id"], path=child_path,
                                  tag_status="not_applicable")

                breadcrumb = raw.get("pathTokens") or [p.strip() for p in (row["path"] or "").split(">") if p.strip()]
                area_name = raw.get("name") or (breadcrumb[-1] if breadcrumb else "unknown")

                # map + scope-filter this area's routes
                kept = []
                for route in src.map_routes(raw):
                    stats["climbs_seen"] += 1
                    verdict = mapping.classify_multipitch_trad_alpine(
                        route["pitches_count"], route["length_m"], route["tags"]["disciplines"])
                    if verdict == "drop":
                        stats["dropped"] += 1
                        continue
                    stats["kept" if verdict == "keep" else "review"] += 1
                    route["_review"] = verdict == "review"
                    kept.append(route)

                # tag the WHOLE area in one LLM call (fixed per-call overhead → batch)
                if do_tag and kept:
                    try:
                        tags, _ = tagging.tag_batch(enums, [tagging.describe_route(r) for r in kept])
                        for r, t in zip(kept, tags):
                            flg = tagging.apply_tags(r, t, enums)
                            stats["tagged"] += 1
                            stats["flagged"] += 1 if flg else 0
                    except Exception as e:
                        errors.append(f"tag batch ({area_name}): {e}")

                for route in kept:
                    review = route.pop("_review", False)
                    route.pop("_raw_description", None)
                    if review:
                        route["needs_field_check"] = True
                        route["curation_notes"] = "auto-ingest: multipitch-unconfirmed"
                    ext = route["external_refs"][0]["external_id"]
                    route["status"] = "draft"
                    route["tagged_by"] = route.get("tagged_by", "source")

                    if dry_run:
                        route["id"] = store.new_route_id() + stats["validated"] + stats["invalid"] + 1
                        route["area_id"] = minter.ensure(row["external_id"], area_name, row["path"],
                                                         source, grade_context=raw.get("gradeContext"))
                        try:
                            store.validate(route)
                            stats["validated"] += 1
                            drafts.append(route)
                        except ValueError as e:
                            stats["invalid"] += 1
                            errors.append(f"validate {route['name']}: {e}")
                    else:
                        route["id"] = _route_id(ext)     # deterministic → idempotent re-runs
                        route["area_id"] = None
                        route["ingest_path"] = breadcrumb
                        try:
                            committed_key = draftstore.save(route, breadcrumb)
                            stats["committed"] += 1
                            drafts.append(route)
                        except ValueError as e:
                            stats["invalid"] += 1
                            errors.append(f"validate {route['name']}: {e}")

                f.complete_fetch(row, area_id=None)
    finally:
        if browser_cm is not None:
            browser_cm.__exit__(None, None, None)

    _report(stats, drafts, errors, dry_run, committed_key)


def _report(stats, drafts, errors, dry_run, committed_key=None):
    print("\n── ingest summary ─────────────────────────────")
    for k, v in stats.items():
        print(f"  {k:16} {v}")
    if drafts:
        d = drafts[0]
        print("\nsample draft route (validated against the store schema):")
        import json
        preview = {k: d[k] for k in ("id", "name", "area_id", "status", "tagged_by",
                                     "original_grade", "grade_system_code", "length_m",
                                     "pitches_count", "protection_code", "tags",
                                     "hazards", "external_refs") if k in d}
        print(json.dumps(preview, ensure_ascii=False, indent=1))
    if errors:
        print(f"\n{len(errors)} issue(s) (never silently dropped):")
        for e in errors[:10]:
            print(f"  ! {e}")
    if dry_run:
        print("\n[dry-run] validated only — nothing written to corpus/record/.")
    elif committed_key:
        pen = committed_key.rsplit("/", 1)[0]
        print(f"\n[commit] {stats['committed']} drafts written to the holding pen "
              f"(S3-keyed like the record):\n  {pen}/…\n  e.g. {committed_key}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="openbeta", help=f"one of {sorted(SOURCES)}")
    p.add_argument("--seed", help="openbeta: an area NAME (\"Yosemite\"); thecrag/ukc: a crag/area URL")
    p.add_argument("--path", help="thecrag/ukc only: breadcrumb for the URL seed, e.g. \"Ireland > Antrim > Fair Head\"")
    p.add_argument("--country", default="USA", help="disambiguates a name seed (OpenBeta is ~US-only)")
    p.add_argument("--dry-run", action="store_true", help="validate + print, write nothing")
    p.add_argument("--tag", action="store_true", dest="do_tag", help="run the LLM tag stage")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--max-cycles", type=int, default=2, help="BFS depth budget for this run")
    args = p.parse_args()
    run(args.source, args.seed, args.path, args.country, args.dry_run,
        args.do_tag, args.batch_size, args.max_cycles)


if __name__ == "__main__":
    main()

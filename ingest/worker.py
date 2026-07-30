#!/usr/bin/env python3
"""Ingest worker — walks the frontier breadth-first for one source, mapping and
(optionally) LLM-tagging what it finds into validated `status: draft` records.

Pipeline per row:  fetch → discover children (enqueue) → map (mechanical) →
                   [tag (LLM)] → validate against the store schema → draft

    # prove the whole vertical against the LIVE OpenBeta API, writing NOTHING:
    python ingest/worker.py --source openbeta --seed "Yosemite" --country USA --dry-run
    python ingest/worker.py --source openbeta --seed "Red Rocks" --dry-run --tag --max-cycles 3

`--dry-run` (the safe default while the draft-area landing policy is undecided —
see ingest/README.md) runs against a scratch copy of the frontier and an
in-memory store: it fetches, maps, tags and VALIDATES every draft, then prints a
summary — but never touches corpus/record/. Drop it to actually land drafts.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "corpus" / "tools"))

import map as mapping  # noqa: E402
import tag as tagging  # noqa: E402
from drafts import DraftStore  # noqa: E402
from frontier import FRONTIER_PATH, Frontier  # noqa: E402
from sources import openbeta  # noqa: E402
from store import Store  # noqa: E402

SCRATCH_FRONTIER = ROOT / "ingest" / ".cache" / "frontier-dryrun.json"


class _AreaMinter:
    """In-memory area creation so mapped routes have a real store area_id to
    reference (store.validate requires area_id ∈ store.areas). In --dry-run
    these live only in memory; a committing run is where the landing policy
    (inject vs holding-pen) actually applies — see README."""
    def __init__(self, store: Store):
        self.store = store
        self._next = max(store.areas, default=0) + 1
        self._by_uuid: dict[str, int] = {}

    def ensure(self, ob_area: dict, path: str) -> int:
        uuid = ob_area["external_id"]
        if uuid in self._by_uuid:
            return self._by_uuid[uuid]
        aid = self._next
        self._next += 1
        self.store.areas[aid] = {
            "id": aid, "name": ob_area["name"], "kind": "crag", "parent_id": None,
            "lat": ob_area.get("lat"), "lon": ob_area.get("lon"),
            "grade_context": ob_area.get("grade_context"), "aspect": None,
            "rock_code": None, "timezone": None, "access_notes": None,
            "_ingest_path": path, "_ingest_source": openbeta.SOURCE_ID,
        }
        self._by_uuid[uuid] = aid
        return aid


def run(source: str, seed: str | None, country: str, dry_run: bool,
        do_tag: bool, batch_size: int, max_cycles: int) -> None:
    if source != "openbeta":
        sys.exit(f"only 'openbeta' is wired today (see ingest/sources.json); got {source!r}")

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
        m = openbeta.seed_area(seed, country)
        if not m:
            sys.exit(f"no real OpenBeta match for {seed!r} in {country!r} "
                     f"(OpenBeta is ~US-only — try a US area)")
        row = f.enqueue(source, m["uuid"], "area", path=" > ".join(m["pathTokens"]),
                        tag_status="not_applicable")
        f.save()
        print(f"seeded: {' > '.join(m['pathTokens'])}  ({m['totalClimbs']} climbs, uuid={m['uuid']})")

    for _ in range(max_cycles):
        f.reclaim_stale(source)
        batch = f.claim_fetch(source, batch_size)
        if not batch:
            break
        for row in batch:
            try:
                raw = openbeta.fetch(row["external_id"])
            except Exception as e:  # one bad node must not kill the walk
                f.fail(row, "fetch", str(e))
                errors.append(f"fetch {row['external_id']}: {e}")
                continue
            stats["areas_fetched"] += 1

            # discover children → enqueue for the next cycle (breadth-first descent)
            for child in openbeta.children(raw):
                if child["totalClimbs"] > 0:  # skip empty branches
                    stats["children_found"] += 1
                    f.enqueue(source, child["uuid"], "area",
                              parent_frontier_id=row["id"],
                              path=f"{row['path']} > {child['name']}",
                              tag_status="not_applicable")

            # map this area's climbs (leaf areas only carry climbs)
            gc = raw.get("gradeContext")
            breadcrumb = raw.get("pathTokens") or [p.strip() for p in row["path"].split(">")]
            for climb in (raw.get("climbs") or []):
                stats["climbs_seen"] += 1
                route = openbeta.to_route(climb, gc)
                verdict = mapping.classify_multipitch_trad_alpine(
                    route["pitches_count"], route["length_m"], route["tags"]["disciplines"])
                if verdict == "drop":
                    stats["dropped"] += 1
                    continue
                stats["kept" if verdict == "keep" else "review"] += 1
                review_flags = ["multipitch-unconfirmed"] if verdict == "review" else []

                if do_tag:
                    try:
                        tags, _ = tagging.tag_batch(enums, [tagging.describe_route(route)])
                        flg = tagging.apply_tags(route, tags[0], enums)
                        stats["tagged"] += 1
                        stats["flagged"] += 1 if flg else 0
                    except Exception as e:
                        errors.append(f"tag {route['name']}: {e}")

                route.pop("_raw_description", None)
                if review_flags:
                    route["needs_field_check"] = True
                    route["curation_notes"] = "auto-ingest: " + ", ".join(review_flags)
                ext = route["external_refs"][0]["external_id"]
                route["status"] = "draft"
                route["tagged_by"] = route.get("tagged_by", "source")

                if dry_run:
                    # validate against an in-memory area so store.validate's area
                    # check passes — proves the record is well-formed, writes nothing
                    route["id"] = store.new_route_id() + stats["kept"] + stats["review"]
                    route["area_id"] = minter.ensure(openbeta.to_area(raw), row["path"])
                    try:
                        store.validate(route)
                        stats["validated"] += 1
                        drafts.append(route)
                    except ValueError as e:
                        stats["invalid"] += 1
                        errors.append(f"validate {route['name']}: {e}")
                else:
                    # land in the S3-keyed holding pen: deterministic id from the
                    # OpenBeta uuid (idempotent re-runs), area unresolved until curation
                    route["id"] = int(ext.replace("-", "")[:8], 16)
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
    p.add_argument("--source", default="openbeta")
    p.add_argument("--seed", help="area name to start from (e.g. \"Yosemite\")")
    p.add_argument("--country", default="USA", help="disambiguates the seed (OpenBeta is ~US-only)")
    p.add_argument("--dry-run", action="store_true", help="validate + print, write nothing")
    p.add_argument("--tag", action="store_true", dest="do_tag", help="run the LLM tag stage")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--max-cycles", type=int, default=2, help="BFS depth budget for this run")
    args = p.parse_args()
    run(args.source, args.seed, args.country, args.dry_run,
        args.do_tag, args.batch_size, args.max_cycles)


if __name__ == "__main__":
    main()

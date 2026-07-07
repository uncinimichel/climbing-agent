#!/usr/bin/env python3
"""Coverage check + crawl_frontier seeding against OpenBeta, for the crags in
db/corpus.json — the "seed from what we already trust" approach (roadmap
Stage 5): search OpenBeta by name for each curated crag; a real match
(totalClimbs > 0) gets enqueued into crawl_frontier for the worker to pick up;
a miss is reported, never silently dropped (CONVENTIONS.md quota discipline).

Run:
    python db/tools/seed_openbeta_frontier.py            # seed + report
    python db/tools/seed_openbeta_frontier.py --dry-run  # report only, no writes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))
from search import connect, load_dotenv  # noqa: E402

from openbeta_client import OpenBetaError, best_match  # noqa: E402

CORPUS = ROOT / "db" / "corpus.json"
SOURCE_ID = "openbeta"
REQUEST_DELAY_S = 0.5  # politeness pacing between name lookups


def enqueue(conn, uuid: str, path_tokens: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawl_frontier (source_id, external_id, kind, path)
            VALUES (%s, %s, 'area', %s)
            ON CONFLICT (source_id, external_id) DO NOTHING
            """,
            (SOURCE_ID, uuid, " > ".join(path_tokens)),
        )
    conn.commit()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="report matches, don't write to crawl_frontier")
    args = p.parse_args()

    crags = [a for a in json.loads(CORPUS.read_text())["areas"] if a["kind"] == "crag"]

    conn = None
    if not args.dry_run:
        load_dotenv()
        conn = connect()

    matched, missed = [], []
    for crag in crags:
        try:
            m = best_match(crag["name"], crag["country"])
        except OpenBetaError as e:
            print(f"  ! {crag['name']!r} — lookup failed: {e}", file=sys.stderr)
            missed.append(crag["name"])
            time.sleep(REQUEST_DELAY_S)
            continue
        if m:
            matched.append((crag["name"], m))
            if conn is not None:
                enqueue(conn, m["uuid"], m["pathTokens"])
        else:
            missed.append(crag["name"])
        time.sleep(REQUEST_DELAY_S)

    print(f"\n{len(matched)}/{len(crags)} corpus crags have a real OpenBeta match:")
    for name, m in matched:
        print(f"  ✓ {name} -> {' > '.join(m['pathTokens'])} ({m['totalClimbs']} climbs)")
    print(f"\n{len(missed)}/{len(crags)} with no OpenBeta data (never silently dropped):")
    for name in missed:
        print(f"  ✗ {name}")


if __name__ == "__main__":
    main()

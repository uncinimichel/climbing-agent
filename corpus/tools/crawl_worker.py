#!/usr/bin/env python3
"""Crawl worker — claims pending `crawl_frontier` rows, fetches + mechanically
filters + LLM-tags them, and writes state back (corpus/sql/040_crawl.sql, roadmap
Stage 5). Designed to run as a slow, unattended loop: every cycle claims a
small batch, so the process can be started, stopped, or killed at any point
with nothing lost — all state lives in the table, never in memory.

Usage:
    python corpus/tools/crawl_worker.py --source openbeta
    python corpus/tools/crawl_worker.py --source thecrag --batch-size 5 --poll-interval 30

Each cycle:
    1. Reclaim stale leases (a previous run crashed mid-batch).
    2. Claim a batch of fetch-pending rows for --source; fetch + mechanically
       insert (area/route tables) + apply the multi-pitch trad/alpine filter.
    3. Claim a batch of tag-pending rows (fetch done, filter passed); LLM-tag
       the inferred fields, validated against the taxonomy enums.
    4. Sleep --poll-interval and repeat.

--batch-size and --poll-interval are the "run slowly all day and night" knobs
— small batches + a long poll interval keep it polite without needing a
separate rate limiter here; per-request pacing for a given source belongs
inside that source's fetcher (only it knows the endpoint's real politeness
budget), see fetch_item below.

Fetch is a per-source plug-in point (ukc_client/thecrag_client — see
fetch_item); openbeta_client.py exists but isn't wired in here (0/89 corpus
crags have real OpenBeta data, see the decision log — nothing to map yet).
Tag is one shared LLM stage (llm_tag.py) that works the same way regardless
of source.
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

from route_mapping import ensure_area, ensure_sector, passes_multipitch_trad_alpine, save_raw, upsert_route  # noqa: E402

STALE_LEASE_MINUTES = 30
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Claiming — SKIP LOCKED so a restarted (or concurrent) worker never double-
# claims a row; each UPDATE...RETURNING claims and leases in one transaction.
# ---------------------------------------------------------------------------
def reclaim_stale(conn, source_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE crawl_frontier
            SET fetch_status = 'pending', claimed_at = NULL
            WHERE source_id = %s AND fetch_status = 'in_progress'
              AND claimed_at < now() - make_interval(mins => %s)
            """,
            (source_id, STALE_LEASE_MINUTES),
        )
    conn.commit()


def claim_fetch_batch(conn, source_id: str, batch_size: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE crawl_frontier
            SET fetch_status = 'in_progress', claimed_at = now(), last_attempted_at = now()
            WHERE id IN (
                SELECT id FROM crawl_frontier
                WHERE source_id = %s AND fetch_status = 'pending'
                ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (source_id, batch_size),
        )
        rows = cur.fetchall()
    conn.commit()
    return rows


def claim_tag_batch(conn, source_id: str, batch_size: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE crawl_frontier
            SET tag_status = 'in_progress', last_attempted_at = now()
            WHERE id IN (
                SELECT id FROM crawl_frontier
                WHERE source_id = %s AND fetch_status = 'done' AND tag_status = 'pending'
                ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (source_id, batch_size),
        )
        rows = cur.fetchall()
    conn.commit()
    return rows


# ---------------------------------------------------------------------------
# Fetch stage — per-source plug-in. `session` is a browser_fetch.BrowserSession,
# only opened when the active --source needs one (ukclimbing/thecrag); openbeta
# is a plain keyless GraphQL call, no browser required.
#
# mountainproject has no client yet (its M0/M1 slot is still open — see
# ingestion-plan.md); openbeta's client works (openbeta_client.py) but isn't
# wired into insert_mechanical below, since the live coverage check found 0/89
# corpus crags have real OpenBeta data (see the decision log) — nothing real
# to write yet, so that mapping work is deferred until a source crag with
# real OpenBeta coverage actually exists in corpus/corpus.json.
# ---------------------------------------------------------------------------
def fetch_item(item: dict, session) -> dict:
    source_id = item["source_id"]
    if source_id == "ukclimbing":
        from ukc_client import fetch_crag

        return fetch_crag(session, item["external_id"])
    if source_id == "thecrag":
        from thecrag_client import fetch_area as fetch_thecrag_area

        return fetch_thecrag_area(session, item["external_id"])
    raise NotImplementedError(f"no fetch client wired up yet for {source_id!r}")


def _enqueue_route_frontier(conn, parent_item: dict, source_id: str, external_id, area_id: int,
                             route_id: int, raw_path: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawl_frontier (source_id, external_id, kind, parent_frontier_id, corpus_area_id,
                                         area_id, route_id, fetch_status, fetched_at, tag_status, raw_capture_path)
            VALUES (%s, %s, 'route', %s, %s, %s, %s, 'done', now(), 'pending', %s)
            ON CONFLICT (source_id, external_id) DO NOTHING
            """,
            (source_id, str(external_id), parent_item["id"], parent_item["corpus_area_id"], area_id, route_id, raw_path),
        )
    conn.commit()


def _insert_ukc(conn, item: dict, record: dict) -> tuple[int, None, None]:
    crag_area_id = ensure_area(conn, item["corpus_area_id"])
    kept = 0
    for route in record["routes"]:
        if not passes_multipitch_trad_alpine(route["pitches"], route["length_m"], route["discipline_label"]):
            continue
        sector_area_id = ensure_sector(conn, crag_area_id, route.get("sector_name"))
        raw_path = save_raw("ukclimbing", route["id"], route)
        route_pg_id = upsert_route(
            conn, sector_area_id, "ukclimbing", route["id"], route["url"],
            name=route["name"], trad_grade=route["adjectival_grade"], tech_grade=route["tech_grade"],
            discipline=route["discipline_label"], stars=route["stars"],
            length_m=route["length_m"], pitches=route["pitches"],
        )
        _enqueue_route_frontier(conn, item, "ukclimbing", route["id"], sector_area_id, route_pg_id, raw_path)
        kept += 1
    print(f"  ukclimbing {item['external_id']}: {kept}/{len(record['routes'])} routes kept (multi-pitch trad/alpine)")
    return crag_area_id, None, None


def _insert_thecrag(conn, item: dict, record: dict) -> tuple[int, None, None]:
    crag_area_id = ensure_area(conn, item["corpus_area_id"])
    if record["children"]:
        return crag_area_id, None, None  # parent area — discover_children enqueues them
    sector_area_id = ensure_sector(conn, crag_area_id, record.get("name"))
    kept = 0
    for r in record["routes"]:
        grade = r.get("gradeAtom", {}).get("grade", "") or ""
        trad_grade, _, tech_grade = grade.partition(" ")
        pitches = int(r["pitches"]) if r.get("pitches") else None
        length_m = (r.get("displayHeight") or [None])[0]
        discipline = r.get("styleStub")
        if not passes_multipitch_trad_alpine(pitches, length_m, discipline):
            continue
        raw_path = save_raw("thecrag", r["id"], r)
        route_pg_id = upsert_route(
            conn, sector_area_id, "thecrag", r["id"], r.get("url"),
            name=r["name"], trad_grade=trad_grade or None, tech_grade=tech_grade or None,
            discipline=discipline, stars=int(r["stars"]) if r.get("stars") else None,
            length_m=length_m, pitches=pitches,
        )
        _enqueue_route_frontier(conn, item, "thecrag", r["id"], sector_area_id, route_pg_id, raw_path)
        kept += 1
    print(f"  thecrag {item['external_id']}: {kept}/{len(record['routes'])} routes kept (multi-pitch trad/alpine)")
    return crag_area_id, None, None


def insert_mechanical(conn, item: dict, record: dict) -> tuple[int | None, int | None, bool | None]:
    """Insert the mechanical fields into area/route (route-schema.md mapping);
    return (area_id, route_id, passes_filter). Only meaningful for kind='area'
    rows — route-kind frontier rows are born already inserted (see
    _enqueue_route_frontier), since UKC/theCrag hand back a whole crag's
    routes in one fetch and there's nothing left to do for them here."""
    source_id = item["source_id"]
    if source_id == "ukclimbing":
        return _insert_ukc(conn, item, record)
    if source_id == "thecrag":
        return _insert_thecrag(conn, item, record)
    raise NotImplementedError(f"insert_mechanical not implemented for {source_id!r}")


def discover_children(conn, item: dict, record: dict) -> None:
    """theCrag only: a parent area page lists child areas, not routes —
    enqueue each as its own crawl_frontier row. UKC has no such stage (one
    crag page already returns every route in one fetch)."""
    if item["source_id"] != "thecrag":
        return
    for child in record.get("children", []):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crawl_frontier (source_id, external_id, kind, parent_frontier_id, corpus_area_id, path)
                VALUES ('thecrag', %s, 'area', %s, %s, %s)
                ON CONFLICT (source_id, external_id) DO NOTHING
                """,
                (child["url"], item["id"], item["corpus_area_id"], f"{item['path']} > {child['name']}"),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Tag stage — LLM inference (protection, hazards+evidence, character,
# feature, incline) via the `claude` CLI (llm_tag.py), not the raw Anthropic
# SDK — see llm_tag.py's docstring for why. One `claude -p` call tags the
# WHOLE claimed batch at once (fixed per-call overhead, so batching beats
# one call per route); a batch-level failure fails every item in it, an
# individual write failure only fails that one route.
# ---------------------------------------------------------------------------
def process_tag_batch(conn, items: list[dict]) -> None:
    if not items:
        return
    from llm_tag import describe_raw, load_tag_enums, tag_batch, write_tags

    tag_enums = load_tag_enums(conn)

    routes_input = []
    for item in items:
        raw = json.loads(Path(item["raw_capture_path"]).read_text())
        routes_input.append(describe_raw(item["source_id"], raw))

    try:
        tags, cost_usd = tag_batch(tag_enums, routes_input)
        print(f"  tagged {len(items)} routes for ${cost_usd:.4f}")
    except Exception as e:  # noqa: BLE001 — whole batch failed, retry each item later
        conn.rollback()
        for item in items:
            _fail(conn, item["id"], "tag_status", item["attempts"], str(e))
        return

    for item, tag in zip(items, tags):
        try:
            flagged = write_tags(conn, item["route_id"], tag, tag_enums)
            status = "needs_review" if flagged else "done"
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE crawl_frontier SET tag_status = %s, tagged_at = now(), flagged_fields = %s WHERE id = %s",
                    (status, flagged or None, item["id"]),
                )
            conn.commit()
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            _fail(conn, item["id"], "tag_status", item["attempts"], str(e))


# ---------------------------------------------------------------------------
# Per-item processing — catches failures so one bad item never kills the loop.
# ---------------------------------------------------------------------------
def process_fetch(conn, item: dict, session) -> None:
    fid = item["id"]
    try:
        record = fetch_item(item, session)
        area_id, route_id, passes = insert_mechanical(conn, item, record)
        if item["kind"] == "area":
            discover_children(conn, item, record)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crawl_frontier
                SET fetch_status = 'done', fetched_at = now(),
                    area_id = %s, route_id = %s, passes_filter = %s,
                    tag_status = CASE WHEN %s THEN 'pending' ELSE tag_status END
                WHERE id = %s
                """,
                (area_id, route_id, passes, item["kind"] == "route" and bool(passes), fid),
            )
        conn.commit()
    except Exception as e:  # noqa: BLE001 — one bad item must not kill the loop
        conn.rollback()
        _fail(conn, fid, "fetch_status", item["attempts"], str(e))


def _fail(conn, frontier_id: int, status_col: str, attempts: int, error: str) -> None:
    next_status = "pending" if attempts + 1 < MAX_ATTEMPTS else "failed"
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE crawl_frontier SET {status_col} = %s, attempts = attempts + 1, last_error = %s WHERE id = %s",
            (next_status, error[:2000], frontier_id),
        )
    conn.commit()


def run(source_id: str, batch_size: int, poll_interval: float, max_cycles: int | None) -> None:
    load_dotenv()
    conn = connect()
    cycles = 0

    needs_browser = source_id in ("ukclimbing", "thecrag")
    browser_cm = None
    session = None
    if needs_browser:
        from browser_fetch import BrowserSession

        browser_cm = BrowserSession()
        session = browser_cm.__enter__()

    try:
        while max_cycles is None or cycles < max_cycles:
            reclaim_stale(conn, source_id)

            fetch_batch = claim_fetch_batch(conn, source_id, batch_size)
            for item in fetch_batch:
                process_fetch(conn, item, session)

            tag_items = claim_tag_batch(conn, source_id, batch_size)
            process_tag_batch(conn, tag_items)

            if not fetch_batch and not tag_items:
                time.sleep(poll_interval)
            cycles += 1
    finally:
        if browser_cm is not None:
            browser_cm.__exit__(None, None, None)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, help="source id from the `source` table (openbeta, thecrag, …)")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--poll-interval", type=float, default=15.0, help="seconds to sleep when a cycle finds no work")
    p.add_argument("--max-cycles", type=int, default=None, help="stop after N cycles (testing); default: run forever")
    args = p.parse_args()
    run(args.source, args.batch_size, args.poll_interval, args.max_cycles)


if __name__ == "__main__":
    main()

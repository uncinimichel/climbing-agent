"""The job engine: works one run to completion, source by source.

Per source: plan (once, resumable) -> frontier loop (fetch -> store raw ->
parse -> inventory/extend frontier), state saved after EVERY item so a
kill -9 at any moment loses at most one in-flight fetch. Caps (--max-pages /
--max-crags, testing knobs per the design session) stop a source cleanly and
are recorded in its parsed output — capped output is never silent.

Sources are independent: one source failing (or hitting its cap) never stops
the others; its error lands in state + manifest instead.
"""
from __future__ import annotations

import time
import traceback

from . import geo, schema
from .runstore import Run, item_key
from .sources import REGISTRY


def work_run(run: Run) -> None:
    manifest = run.manifest
    bbox = tuple(manifest["bbox"])
    caps = manifest["caps"]
    sources = manifest["sources"]

    session = None
    needs_browser = any(REGISTRY[s].NEEDS_BROWSER for s in sources)
    try:
        if needs_browser:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "corpus" / "tools"))
            from browser_fetch import BrowserSession
            session = BrowserSession().__enter__()
        for source_id in sources:
            if manifest["status"].get(source_id) == "done":
                continue
            _work_source(run, source_id, bbox, caps,
                         session if REGISTRY[source_id].NEEDS_BROWSER else None,
                         manifest.get("roots", {}).get(source_id))
    finally:
        if session is not None:
            session.__exit__(None, None, None)


def _work_source(run: Run, source_id: str, bbox, caps: dict, session, root) -> None:
    src = REGISTRY[source_id]
    run.set_status(source_id, "running")
    state = run.state()
    st = state[source_id]
    try:
        if not st["planned"]:
            run.log(f"{source_id}: planning (bbox -> frontier)…")
            items = src.plan(bbox, session, root=root)
            st["pending"] = items
            st["planned"] = True
            run.save_state(state)
            run.log(f"{source_id}: frontier seeded with {len(items)} item(s)")

        crags = _existing_crags(run, source_id)
        done = set(st["done"])
        while st["pending"]:
            if caps.get("max_pages") and st["pages_fetched"] >= caps["max_pages"]:
                st["capped"] = f"max_pages={caps['max_pages']} hit with {len(st['pending'])} item(s) still pending"
                break
            if caps.get("max_crags") and st["crags"] >= caps["max_crags"]:
                st["capped"] = f"max_crags={caps['max_crags']} hit with {len(st['pending'])} item(s) still pending"
                break

            item = st["pending"][0]
            key = item_key(item)
            if key in done:
                st["pending"].pop(0)
                continue

            existing = run.load_raw(source_id, item)   # resume: reuse the stored payload
            if existing is None:
                payload = src.fetch(item, session)
                run.save_raw(source_id, item, payload)
                st["pages_fetched"] += 1
                time.sleep(src.DELAY_S)
            else:
                payload = existing["payload"]

            result = src.parse(item, payload, bbox)
            for c in result["crags"]:
                problems = schema.validate(c)
                if problems:
                    # a mapper emitting off-schema output is a bug to fix, not
                    # data to keep — fail the source loudly (raw is stored, so
                    # rerunning after the fix costs no re-fetch)
                    raise RuntimeError(f"schema violation in {c.get('name')!r}: {problems}")
            for c in result["crags"]:
                crags.append(c)
                st["crags"] += 1
                st["routes"] += len(c["routes"])
            seen_pending = {item_key(i) for i in st["pending"]}
            for nxt in result["next"]:
                if item_key(nxt) not in done and item_key(nxt) not in seen_pending:
                    st["pending"].append(nxt)
            st["pending"].pop(0)
            done.add(key)
            st["done"] = sorted(done)
            run.save_state(state)
            run.save_parsed(source_id, bbox, crags, st["capped"])
            name = item.get("name") or item.get("url") or item.get("id")
            run.log(f"{source_id}: {name} -> +{len(result['crags'])} crag(s), "
                    f"+{sum(len(c['routes']) for c in result['crags'])} route(s) "
                    f"[{st['pages_fetched']} pages, {st['crags']} crags, {st['routes']} routes, "
                    f"{len(st['pending'])} pending]")

        run.save_parsed(source_id, bbox, crags, st["capped"])
        run.save_state(state)
        status = "capped" if st["capped"] else "done"
        run.set_status(source_id, status)
        run.log(f"{source_id}: {status} — {st['crags']} crags / {st['routes']} routes"
                + (f" ({st['capped']})" if st["capped"] else ""))
    except Exception as e:
        st["error"] = f"{type(e).__name__}: {e}"
        run.save_state(state)
        run.set_status(source_id, "failed")
        run.log(f"{source_id}: FAILED — {st['error']}\n{traceback.format_exc()}")


def _existing_crags(run: Run, source_id: str) -> list[dict]:
    parsed = run.load_parsed(source_id)
    return parsed["crags"] if parsed else []

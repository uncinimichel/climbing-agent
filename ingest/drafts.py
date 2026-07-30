#!/usr/bin/env python3
"""The draft holding pen — where scraped, uncurated routes land before a human
promotes them in the Studio.

Keyed exactly like the curated record's S3 layout (store.py): a hierarchical
slug path, reserved under an `_ingest/` prefix so it shares the record's bucket,
`_dump` atomic writes and slug scheme but is ISOLATED from the curated corpus —
    curated:  record/<country>/<region>/<crag>/<route>.json
    drafts:   record/_ingest/<country>/<region>/<crag>/<route>.json
The store loader skips `_`-prefixed dirs, so drafts never pollute store.routes.

Why a holding pen and not the curated tree: a curated route must resolve to an
integer area in areas.json, but a fresh scrape has no verified area yet — and
areas have no draft gate. So a draft carries its source breadcrumb (`ingest_path`)
and leaves `area_id` null; promotion in the Studio is where a human resolves it
to (or creates) the real area and the route moves into the curated keyspace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "corpus" / "tools"))
import jsonschema  # noqa: E402
from store import REC_DIR, Store, _dump, slug  # noqa: E402  (reuse the record's own key + write machinery)

INGEST_PREFIX = "_ingest"


class DraftStore:
    def __init__(self, store: Store):
        self.store = store
        # Relaxed copy of the curated route schema: same closed-enum validation
        # (protection/discipline/hazard/... still can't be off-dictionary), but a
        # draft need not resolve to a curated area yet, so area_id is optional.
        schema = json.loads(json.dumps(store._schema))
        schema["required"] = ["id", "name", "status", "tagged_by"]
        schema["properties"]["area_id"] = {"anyOf": [{"type": "null"}, {"type": "integer"}]}
        self._schema = schema

    def key_for(self, breadcrumb: list[str], route_name: str, external_id: str) -> Path:
        """The draft's file path == its S3 key (minus the `record/` prefix _dump
        adds). Built from the source breadcrumb the same way store.crag_prefix
        builds curated keys: country / region / crag / route-<extid>.json. The
        external-id suffix keeps duplicate route names across sectors distinct."""
        toks = [t for t in (breadcrumb or []) if t]
        country = slug(toks[0]) if toks else "unknown"
        region = slug(toks[1]) if len(toks) > 1 else "unsorted"
        crag = slug(toks[-1]) if len(toks) > 2 else region
        fname = f"{slug(route_name)}-{slug(str(external_id))[:12]}.json"
        return REC_DIR / INGEST_PREFIX / country / region / crag / fname

    def validate(self, route: dict) -> None:
        try:
            jsonschema.validate(route, self._schema)
        except jsonschema.ValidationError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "route"
            raise ValueError(f"{path}: {e.message}") from None

    def save(self, route: dict, breadcrumb: list[str]) -> str:
        """Validate + atomically write the draft to its S3-style key (local file
        now, same key to S3 when RECORD_BUCKET is set). Returns the repo-relative
        key. Re-running ingest overwrites the same key (idempotent per route)."""
        self.validate(route)
        ext = route["external_refs"][0]["external_id"]
        path = self.key_for(breadcrumb, route["name"], ext)
        _dump(path, route)                       # atomic tmp+rename (+ S3 put in cloud mode)
        return str(path.relative_to(REC_DIR.parent.parent))

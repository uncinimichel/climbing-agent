#!/usr/bin/env python3
"""Shared mechanical mapping — source-agnostic pieces the worker uses for every
source: the multi-pitch trad/alpine filter (the mission's scope gate) and the
raw-capture cache.

CRITICAL: raw captures go to ingest/.cache/ (gitignored), NEVER inside
corpus/record/ — a stray non-route JSON in the record tree crashes store.py's
loader (that's the UKC ukc-routes.json bug). The record holds only validated
route/area documents; everything else lives here.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_CACHE = ROOT / "ingest" / ".cache"

MIN_PITCHES = 2
MIN_LENGTH_M = 60
# The mission is multi-pitch TRAD (+ the alpine/aid/big-wall family that shares
# the rack-and-commitment character). Sport/bouldering multipitch is out of scope.
MULTIPITCH_DISCIPLINES = {"trad", "alpine", "big-wall", "aid"}


def classify_multipitch_trad_alpine(pitch_count: int | None, length_m: int | None,
                                    disciplines: list[str]) -> str:
    """Tri-state scope gate → "keep" | "review" | "drop".

    The mission is multi-pitch trad/alpine, but sources under-populate structure:
    OpenBeta routinely gives length=-1 (unknown) and an empty pitch list even for
    long routes (verified live — "Ping Ridge", a trad/alpine line, carries neither).
    Silently dropping those loses real climbs, so we never discard on *missing*
    data — only on data that positively says single-pitch:

      keep   — in family AND confirmed multi-pitch (>=2 pitches OR >=60 m), or alpine
      review — in family but structure unknown (no pitch count, no length) → draft
               for a human, flagged 'multipitch-unconfirmed'
      drop   — not trad/alpine/aid, or positively single-pitch (1 pitch / <60 m known)
    """
    if not any(d in MULTIPITCH_DISCIPLINES for d in (disciplines or [])):
        return "drop"
    if (pitch_count or 0) >= MIN_PITCHES or (length_m or 0) >= MIN_LENGTH_M:
        return "keep"
    if "alpine" in disciplines:                     # alpine is ~always multi-pitch
        return "keep"
    if pitch_count is None and length_m is None:    # unknown structure — let a human judge
        return "review"
    return "drop"                                   # positively single-pitch → out of scope


def save_raw(source_id: str, external_id: str, record: dict) -> str:
    """Persist a raw source capture for provenance/debugging; return its path
    (relative to repo root) for the frontier row. Gitignored — never committed,
    never in the record tree."""
    d = RAW_CACHE / source_id
    d.mkdir(parents=True, exist_ok=True)
    safe = str(external_id).replace("/", "_").replace(":", "_")[:120]
    path = d / f"{safe}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    return str(path.relative_to(ROOT))

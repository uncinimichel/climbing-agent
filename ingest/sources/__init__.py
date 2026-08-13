"""Source adapter registry. An adapter is a module with:

    SOURCE_ID: str
    NEEDS_BROWSER: bool          # True -> runner passes a BrowserSession
    DELAY_S: float               # min seconds between fetches (politeness)

    plan(bbox, session, root=None) -> list[item]
        Translate the bbox into this source's starting frontier — a geo query
        (openbeta/ukc) or a walk root (thecrag). May itself fetch.

    fetch(item, session) -> payload
        One unit of work -> the verbatim payload (JSON dict or HTML string).
        The runner stores it before parsing, so a mapper bug never costs a re-scrape.

    parse(item, payload, bbox) -> {"crags": [schema.crag], "next": [item]}
        Map the payload into the shared schema and/or extend the frontier.
        Bbox pruning happens here — only the source knows where its coords live.

An item is a plain dict: {"kind": ..., "id" or "url": ..., "name": ...} — it
must survive JSON round-tripping (the frontier is persisted per item).
"""
from __future__ import annotations

from . import camptocamp, climbook, falesiait, irishwiki, openbeta, thecrag, ukc

REGISTRY = {m.SOURCE_ID: m for m in (camptocamp, climbook, falesiait, irishwiki,
                                     openbeta, thecrag, ukc)}

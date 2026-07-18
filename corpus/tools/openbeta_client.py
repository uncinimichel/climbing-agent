#!/usr/bin/env python3
"""OpenBeta GraphQL client — CC-licensed, keyless, ingestion-encouraged (the
first, license-safe crawl source per ingestion-plan.md). Schema verified live
against https://api.openbeta.io/graphql via introspection (2026-07-06); field
names below are not guessed.

Dependency-free (stdlib urllib), matching corpus/tools/build_corpus.py's convention.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

GRAPHQL_URL = "https://api.openbeta.io/graphql"
RETRYABLE_HTTP_CODES = {429, 502, 503, 504}  # transient Cloudflare/upstream hiccups
MAX_RETRIES = 3

CLIMB_FIELDS = """
    uuid name fa length boltsCount gradeContext
    pitches { pitchNumber length boltsCount description grades { yds french uiaa ewbank font vscale wi brazilianCrux } type { trad sport alpine ice mixed aid tr } }
    grades { yds french uiaa ewbank font vscale wi brazilianCrux }
    type { trad sport bouldering deepwatersolo alpine snow ice mixed aid tr }
    safety
    metadata { lat lng mp_id }
    content { description location protection }
    pathTokens ancestors
"""

AREA_DETAIL_QUERY = f"""
query($id: ID) {{
  area(uuid: $id) {{
    uuid areaName pathTokens ancestors gradeContext totalClimbs
    metadata {{ lat lng leaf isDestination isBoulder mp_id }}
    children {{ uuid areaName totalClimbs metadata {{ leaf isBoulder }} }}
    climbs {{ {CLIMB_FIELDS} }}
  }}
}}
"""

SEARCH_AREAS_QUERY = """
query($name: String!) {
  areas(filter: {area_name: {match: $name}}) {
    uuid areaName pathTokens totalClimbs
  }
}
"""


class OpenBetaError(RuntimeError):
    pass


def _post(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    headers = {
        "Content-Type": "application/json",
        # Cloudflare (fronting api.openbeta.io) 403s the default "Python-urllib/x.y" UA.
        "User-Agent": "climbing-agent-crawler/0.1 (+https://github.com/uncinimichel/climbing-agent)",
    }
    req = urllib.request.Request(GRAPHQL_URL, data=body, headers=headers, method="POST")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)  # 2s, 4s
                continue
            raise OpenBetaError(f"HTTP {e.code}: {e.read()[:500]!r}") from e
    if payload.get("errors"):
        raise OpenBetaError(str(payload["errors"]))
    return payload["data"]


def search_areas_by_name(name: str) -> list[dict]:
    """All areas (worldwide, OpenBeta has no exact-crag lookup) matching `name`."""
    return _post(SEARCH_AREAS_QUERY, {"name": name})["areas"]


# corpus.json's `country` for UK home nations vs. OpenBeta's pathTokens[0]
# (OpenBeta nests all four under one "United Kingdom" country node).
COUNTRY_ALIASES = {
    "Northern Ireland": "United Kingdom",
    "Scotland": "United Kingdom",
    "Wales": "United Kingdom",
    "England": "United Kingdom",
}


def best_match(name: str, country: str, candidates: list[dict] | None = None) -> dict | None:
    """The candidate most likely to be the real venue.

    `country` is required, not a nicety: generic rock-feature names collide
    worldwide (a name-only match sent "Buzzards Roost"/Mournes, NI to a Red
    River Gorge, Kentucky crag of the same name — verified live 2026-07-06).
    Requires pathTokens[0] == the corpus's country (via COUNTRY_ALIASES) on
    top of totalClimbs > 0 and, ideally, an exact name match.
    """
    candidates = candidates if candidates is not None else search_areas_by_name(name)
    want = COUNTRY_ALIASES.get(country, country)
    real = [c for c in candidates if c["totalClimbs"] > 0 and c["pathTokens"] and c["pathTokens"][0] == want]
    if not real:
        return None
    exact = [c for c in real if c["areaName"].strip().lower() == name.strip().lower()]
    pool = exact or real
    return max(pool, key=lambda c: c["totalClimbs"])


def fetch_area(uuid: str) -> dict:
    """Area detail + children (for discovery) + full climb records (leaf areas
    only — OpenBeta only populates `climbs` on leaf nodes, empty elsewhere)."""
    return _post(AREA_DETAIL_QUERY, {"id": uuid})["area"]


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "Smith Rock"
    country = sys.argv[2] if len(sys.argv) > 2 else "USA"
    match = best_match(name, country)
    if not match:
        print(f"no real (totalClimbs > 0, country={country!r}) OpenBeta match for {name!r}")
    else:
        print(json.dumps(match, indent=2))
        print(json.dumps(fetch_area(match["uuid"]), indent=2)[:1000])

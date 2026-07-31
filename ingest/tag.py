#!/usr/bin/env python3
"""LLM tag stage — JSON-native (no Postgres).

Infers the fields that need judgement from prose (protection, belays,
hazards+evidence, character, feature, incline) for mechanically-fetched routes.
The Claude call (prompt + `claude -p` CLI + batching) is inlined below; the two
halves that used to be Postgres-coupled are now record-native:

  - load enums from the DB   →  enums_from_store(store)   reads taxonomies.json
  - write tags to SQL rows   →  apply_tags(route, tag)    mutates the route dict

The validate-and-repair rule (never trust the model's own `flagged`;
independently check every value against the closed enums, repair to a safe
default and flag it ourselves) is preserved — it just writes into the draft
route document instead of SQL rows.
"""
from __future__ import annotations

import json
import subprocess

PROTECTION_STYLES = ("gear", "bolted", "mixed", "none", None)
BELAYS = ("gear", "bolted", "mixed", None)

# The Claude call runs via the `claude` CLI (not the raw Anthropic SDK): a direct
# client.messages.create() bills the account's pay-per-token API balance and fails
# "credit balance too low" on this machine; the CLI path bills the Claude Code
# subscription (established by agent/cli_agent.py). One call tags a whole batch —
# each carries a fixed ~$0.02-0.07 overhead, so batching amortizes it.
MODEL = "haiku"
CLI_TIMEOUT_S = 180

PROMPT_TEMPLATE = """You are tagging climbing routes against a STRICT closed vocabulary. For
each route below, output your best judgement ONLY from the given text — never guess or
infer beyond what's stated. If there's no usable text, say so honestly (protection
"UNSPECIFIED", empty hazards/character/feature arrays, incline null) rather than
inventing detail to fill the schema.

Closed vocabularies (use ONLY these exact values):
  protection: {protection}
  hazards: {hazards}
  character: {character}
  feature: {feature}
  incline: {incline}

Rules:
- hazards: only include one if the text gives clear evidence; "evidence" must be a short
  VERBATIM quote from the route's own text (not paraphrased or invented). No evidence ->
  omit the hazard entirely.
- protection/belays: infer only from explicit gear/bolt/peg mentions in the text; if the
  text says nothing about protection, use "UNSPECIFIED" (protection) and null
  (protection_style, belays) — never guess from the grade alone.
- character/feature: only tags with real textual support; empty arrays are the expected,
  correct answer for terse or missing descriptions.
- incline: only set if the text actually describes the angle (slab/vertical/overhanging);
  otherwise null.
- flagged: list any field you could not confidently resolve (e.g. ["protection","character"]
  when the description is empty) — this routes the route to human review instead of a guess.

Output a JSON array, one object per route, IN THE SAME ORDER as the routes are listed,
each shaped EXACTLY like this (no extra keys, no missing keys):
{{"protection": "<code>", "protection_style": "<code or null>", "belays": "<code or null>",
  "hazards": [{{"code": "<code>", "evidence": "<verbatim quote>"}}], "character": ["<code>"],
  "feature": ["<code>"], "incline": "<code or null>", "flagged": ["<field name>"]}}

Output ONLY the JSON array — no markdown fences, no commentary, nothing else.

Routes:
{routes_block}
"""


def _routes_block(routes: list[dict]) -> str:
    lines = []
    for i, r in enumerate(routes):
        text = r.get("description") or "(no description available)"
        lines.append(f"[{i}] {r['name']} ({r.get('grade') or 'grade unknown'}): {text}")
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def tag_batch(enums: dict, routes: list[dict]) -> tuple[list[dict], float]:
    """One `claude -p` call tagging the whole batch. Returns (one tag dict per
    route in order, cost_usd)."""
    prompt = PROMPT_TEMPLATE.format(
        protection=", ".join(enums["protection"]),
        hazards=", ".join(enums["hazards"]),
        character=", ".join(enums["character"]),
        feature=", ".join(enums["feature"]),
        incline=", ".join(enums["incline"]),
        routes_block=_routes_block(routes),
    )
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", MODEL, "--output-format", "json"],
        capture_output=True, text=True, timeout=CLI_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude CLI error: {payload.get('result')}")
    tags = json.loads(_strip_fences(payload["result"]))
    if not isinstance(tags, list) or len(tags) != len(routes):
        raise ValueError(f"expected {len(routes)} tag objects, got {tags!r}")
    return tags, payload.get("total_cost_usd", 0.0)


def enums_from_store(store) -> dict:
    """Closed vocabularies straight from the loaded taxonomy record, so the
    prompt can't drift from the schema's actual enums (store.tax is what
    store.py validates writes against)."""
    tax = store.tax
    code = lambda fam: [r["code"] for r in tax[fam]]  # noqa: E731
    return {
        "protection": code("protection_grade"),
        "hazards": code("hazard"),
        "safety_critical_hazards": {r["code"] for r in tax["hazard"] if r.get("safety_critical")},
        "character": code("character"),
        "feature": code("feature"),
        "incline": code("incline"),
    }


def describe_route(route: dict) -> dict:
    """The {name, grade, description} the tagger reads — from a mapped route dict
    (openbeta.to_route stashed the prose under `_raw_description`)."""
    return {
        "name": route.get("name"),
        "grade": route.get("original_grade"),
        "description": route.get("_raw_description") or None,
    }


def apply_tags(route: dict, tag: dict, enums: dict) -> list[str]:
    """Validate-and-repair every LLM value against the enums and write it into
    `route` (mutates in place). Returns the final flagged-field list; a
    non-empty list routes the draft to `needs_review`. Sets tagged_by='llm'."""
    flagged = list(tag.get("flagged", []))

    protection = tag.get("protection")
    if protection not in enums["protection"] and protection != "UNSPECIFIED":
        flagged.append("protection")
        protection = "UNSPECIFIED"
    # never overwrite a mechanically-known protection (OpenBeta `safety`) with a guess
    if not route.get("protection_code"):
        route["protection_code"] = None if protection == "UNSPECIFIED" else protection

    style = tag.get("protection_style")
    if style not in PROTECTION_STYLES:
        flagged.append("protection_style")
        style = None
    route["protection_style"] = style

    belays = tag.get("belays")
    if belays not in BELAYS:
        flagged.append("belays")
        belays = None
    route["belays"] = belays

    incline = tag.get("incline")
    if incline is not None and incline not in enums["incline"]:
        flagged.append("incline")
        incline = None
    route["incline_code"] = incline

    hazards = []
    for h in tag.get("hazards", []):
        c, ev = h.get("code"), (h.get("evidence") or "").strip()
        if c not in enums["hazards"] or not ev:
            flagged.append(f"hazard:{c}")
            continue
        hazards.append({"hazard_code": c, "evidence_span": ev})
    route["hazards"] = hazards

    route.setdefault("tags", {}).setdefault("disciplines", [])
    char = [c for c in tag.get("character", []) if c in enums["character"]]
    feat = [f for f in tag.get("feature", []) if f in enums["feature"]]
    flagged += [f"character:{c}" for c in tag.get("character", []) if c not in enums["character"]]
    flagged += [f"feature:{f}" for f in tag.get("feature", []) if f not in enums["feature"]]
    route["tags"]["character"] = char
    route["tags"]["features"] = feat

    route["tagged_by"] = "llm"
    route["tag_prov"] = {"model": "claude-cli", "source": "ingest/tag.py"}
    return flagged


__all__ = ["tag_batch", "enums_from_store", "describe_route", "apply_tags"]

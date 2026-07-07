"""LLM tag stage — infers the fields that need judgement from prose
(protection, belays, hazards+evidence, character, feature, incline) for
mechanically-fetched routes. Everything else (name, grade, pitches, length,
discipline) is already mechanical — see route_mapping.py.

Runs via the `claude` CLI (`claude -p ... --output-format json`), not the raw
Anthropic SDK: a direct client.messages.create() call bills against the
account's separate pay-per-token API credit balance and fails with "credit
balance too low" on this machine — the CLI path bills against the Claude Code
subscription instead (established by agent/cli_agent.py; see the
project-climbing-db memory before "fixing" this back to the SDK).

Batches multiple routes into ONE `claude -p` call — each call carries a fixed
~$0.02-0.07 overhead regardless of content, so tagging 197 routes one-by-one
would be wasteful; batching amortizes it.
"""
from __future__ import annotations

import json
import subprocess

MODEL = "haiku"
CLI_TIMEOUT_S = 180


def load_tag_enums(conn) -> dict:
    """Straight from the DB (taxonomy.md's mirror) — never hardcoded, so the
    prompt can't drift from the schema's actual closed vocabularies."""
    enums: dict = {}
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM climbing.protection_grade ORDER BY code")
        enums["protection"] = [r["code"] for r in cur.fetchall()]

        cur.execute("SELECT code, safety_critical FROM climbing.hazard WHERE kind = 'route' ORDER BY code")
        rows = cur.fetchall()
        enums["hazards"] = [r["code"] for r in rows]
        enums["safety_critical_hazards"] = {r["code"] for r in rows if r["safety_critical"]}

        cur.execute("SELECT code FROM climbing.character ORDER BY code")
        enums["character"] = [r["code"] for r in cur.fetchall()]
        cur.execute("SELECT code FROM climbing.feature ORDER BY code")
        enums["feature"] = [r["code"] for r in cur.fetchall()]
        cur.execute("SELECT code FROM climbing.incline ORDER BY sort_order")
        enums["incline"] = [r["code"] for r in cur.fetchall()]
    return enums


def describe_raw(source_id: str, raw: dict) -> dict:
    """Extract {name, grade, description} uniformly — UKC carries real
    pitch-by-pitch prose; theCrag's listing data carries no description at
    all, so that field is honestly None, not fabricated."""
    if source_id == "ukclimbing":
        grade = " ".join(p for p in (raw.get("adjectival_grade"), raw.get("tech_grade")) if p)
        return {"name": raw.get("name"), "grade": grade or None, "description": raw.get("description")}
    if source_id == "thecrag":
        return {"name": raw.get("name"), "grade": raw.get("gradeAtom", {}).get("grade"), "description": None}
    raise NotImplementedError(f"describe_raw not implemented for {source_id!r}")


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
    """Returns (one tag dict per route, in order, cost_usd of the call)."""
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


def write_tags(conn, route_id: int, tag: dict, enums: dict) -> list[str]:
    """Validate-and-repair (taxonomy.md rule #1): never trust the model's own
    `flagged` self-report alone — independently check every value against the
    enums, repairing to a safe default (UNSPECIFIED/null/omit) and flagging
    it ourselves if it's off-dictionary. Returns the final flagged-field list."""
    flagged = list(tag.get("flagged", []))

    protection = tag.get("protection")
    if protection not in enums["protection"]:
        flagged.append("protection")
        protection = "UNSPECIFIED"
    protection_style = tag.get("protection_style")
    if protection_style not in ("gear", "bolted", "mixed", "none", None):
        flagged.append("protection_style")
        protection_style = None
    belays = tag.get("belays")
    if belays not in ("gear", "bolted", "mixed", None):
        flagged.append("belays")
        belays = None
    incline = tag.get("incline")
    if incline is not None and incline not in enums["incline"]:
        flagged.append("incline")
        incline = None

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE route SET protection_code = %s, protection_style = %s, belays = %s, incline_code = %s WHERE id = %s",
            (protection, protection_style, belays, incline, route_id),
        )
    conn.commit()

    for h in tag.get("hazards", []):
        code, evidence = h.get("code"), h.get("evidence")
        if code not in enums["hazards"] or not evidence:
            flagged.append(f"hazard:{code}")
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO route_hazard (route_id, hazard_code, evidence_span) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (route_id, code, evidence),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            flagged.append(f"hazard:{code}")

    for c in tag.get("character", []):
        if c not in enums["character"]:
            flagged.append(f"character:{c}")
            continue
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO route_character (route_id, character_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (route_id, c),
            )
        conn.commit()

    for f in tag.get("feature", []):
        if f not in enums["feature"]:
            flagged.append(f"feature:{f}")
            continue
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO route_feature (route_id, feature_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (route_id, f),
            )
        conn.commit()

    return flagged

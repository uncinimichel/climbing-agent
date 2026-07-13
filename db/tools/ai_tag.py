#!/usr/bin/env python3
"""Phase-2 AI tagging — infer the prose-only fields once, cached (roadmap Phase 2).

feature (crack/slab/corner…), character (sustained/exposed…), protection (G/PG/R/X)
and discipline don't exist as structured data anywhere — they live only in the
multi-pitch prose. This reads each climb's description, asks Claude to extract them
as strict-enum JSON, validates against the taxonomy, and caches the result in
db/enrichment-cache.json keyed by route id.

IDEMPOTENT — this is the whole point: a climb already in the cache is skipped, so
re-runs and the daily build make ZERO LLM calls. You pay once per route, ever.

Uses `claude -p` (decision #23: Claude Code CLI, subscription-billed, not API credit).

    python3 db/tools/ai_tag.py --limit 5     # proof: tag up to 5 untagged
    python3 db/tools/ai_tag.py               # tag all remaining untagged
    python3 db/tools/ai_tag.py --retag mp-34 # force re-tag one id
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MP = ROOT / "db" / "mp-climbs.json"
CACHE = ROOT / "db" / "enrichment-cache.json"
SEED = ROOT / "db" / "sql" / "100_seed_taxonomy.sql"
LIVE_VALUES = ROOT / "knowledge" / "data" / "taxonomy-values.json"
_FAMILY_BY_TABLE = {"feature": "feature", "character": "character",
                    "discipline": "discipline", "protection_grade": "protection"}


def enum(table):
    """Allowed values for a taxonomy table — the LIVE set, so values added in the
    Curation Studio's Taxonomy page reach the tagger (decision #35). Preference:
    Postgres → taxonomy-values.json export → the hand-written seed file."""
    q = f"SELECT string_agg(code, ',' ORDER BY code) FROM climbing.{table};"
    for cmd in (["psql", "postgresql://climbing:climbing@localhost:5432/climbing", "-tAc", q],
                ["docker", "exec", "climbing-db", "psql", "-U", "climbing", "-d", "climbing", "-tAc", q]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip().split(",")
        except Exception:
            continue
    if LIVE_VALUES.exists():
        fam = _FAMILY_BY_TABLE.get(table)
        rows = json.loads(LIVE_VALUES.read_text()).get("families", {}).get(fam)
        if rows:
            return [r["code"] for r in rows]
    sql = SEED.read_text()
    for chunk in re.split(r"INSERT INTO ", sql)[1:]:
        if re.match(r"(\w+)", chunk).group(1) == table:
            return list(dict.fromkeys(re.findall(r"\(\s*'([^']*)'", chunk)))
    return []


def build_prompt(c, en):
    desc = " ".join(filter(None, [c.get("description"), c.get("pitchInfo")]))[:4000]
    return f"""You are tagging a rock-climbing route from its guidebook description, using a STRICT controlled vocabulary. Use ONLY values from the allowed lists. Include a value ONLY if the text clearly supports it; if unsure, leave it out. Do not invent values.

Route: {c.get('routeName')} on {c.get('cliff')} ({c.get('country')}). Grade {c.get('originalGrade')}, {c.get('pitches')} pitches, {c.get('length')}m.

Description:
{desc or '(none)'}

Allowed values:
- features (rock forms/shapes climbed): {', '.join(en['feature'])}
- character (how it climbs / feel): {', '.join(en['character'])}
- protection (choose ONE): {', '.join(en['protection_grade'])} — G well-protected, PG/PG-13 mostly, R serious, X deadly, runout long gaps, UNSPECIFIED if not stated
- discipline: {', '.join(en['discipline'])}

Respond with ONLY a JSON object, no prose, no code fence:
{{"features":[],"character":[],"protection":"","discipline":[]}}"""


def call_claude(prompt):
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "claude -p failed")[:200])
    return r.stdout


def extract_json(text):
    text = text.strip().strip("`")
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON in model output")
    obj, _ = json.JSONDecoder().raw_decode(text[i:])  # ignores any trailing prose
    return obj


def tag_one(c, en):
    out = extract_json(call_claude(build_prompt(c, en)))
    fe, ch, di = set(en["feature"]), set(en["character"]), set(en["discipline"])
    pr = set(en["protection_grade"])
    feats = [x for x in (out.get("features") or []) if x in fe]
    chars = [x for x in (out.get("character") or []) if x in ch]
    disc = [x for x in (out.get("discipline") or []) if x in di]
    prot = out.get("protection") if out.get("protection") in pr else None
    desc = " ".join(filter(None, [c.get("description"), c.get("pitchInfo")]))
    return {"features": feats, "character": chars, "protection": prot, "discipline": disc,
            "_prov": {"model": "claude-cli", "date": date.today().isoformat(),
                      "descHash": hashlib.sha1(desc.encode()).hexdigest()[:10]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max routes to tag this run (0 = all)")
    ap.add_argument("--retag", help="force re-tag this route id (e.g. mp-34)")
    args = ap.parse_args()

    climbs = json.loads(MP.read_text())["climbs"]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    en = {t: enum(t) for t in ("feature", "character", "discipline", "protection_grade")}

    todo = []
    for c in climbs:
        rid = f"mp-{c.get('id')}"
        if args.retag:
            if rid == args.retag:
                todo.append((rid, c))
        elif rid not in cache:
            todo.append((rid, c))
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(cache)} cached · {len(todo)} to tag this run"
          f"{' (limit '+str(args.limit)+')' if args.limit else ''}", file=sys.stderr)

    done = 0
    for rid, c in todo:
        try:
            cache[rid] = tag_one(c, en)
            done += 1
            e = cache[rid]
            print(f"  ✓ {rid} {c.get('routeName')[:28]:28} "
                  f"feat={e['features']} char={e['character']} prot={e['protection']}",
                  file=sys.stderr)
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")  # save incrementally
        except Exception as ex:
            print(f"  ✗ {rid}: {ex}", file=sys.stderr)
    print(f"tagged {done} · cache now {len(cache)} routes → {CACHE.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()

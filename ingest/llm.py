"""LLM curation — phase 3 (crawl -> enrich -> THIS). Takes enriched (or
parsed) inventories from one or more runs, dedupes across sources, has the
LLM apply the judgment tags, and publishes to runs/<primary>/llm-curated/ —
machine-curated, explicitly NOT human-curated yet.

    python -m ingest llm <run-id> [--with <run-id>,...] [--max-llm-routes N]
                        [--model sonnet] [--batch 20]

Dedupe (mechanical first, LLM only for judgment):
  crags  — merged when normalized names match AND coords agree (<1 km, or a
           side has none); near-misses (<500 m, similar-but-not-equal names)
           go to the LLM as explicit same-place? questions, merged only on a
           confident yes. UKC's one-crag-per-cliff vs theCrag's sub-crags
           stay SEPARATE on purpose — different granularity is not a dupe.
  routes — two levels. Inside a merged crag, same-name routes become ONE
           entity with per-source refs. ACROSS crags that stayed separate
           (the granularity case: UKC's whole-cliff record vs theCrag's
           sub-crags), a global pass links same-named routes on nearby crags
           (<2 km) from different sources via `same_as` — identity recorded,
           entities kept where their sources put them (the "Nobody Move"
           case: one UKC ref, one theCrag ref, linked not collapsed).

Tags (via the `claude` CLI like corpus/tools/llm_tag.py, default sonnet —
haiku proved unreliable on terse text, see decision log): protection /
hazards(+verbatim evidence) / character / feature / incline, closed to the
corpus taxonomy. Validate-and-repair: off-vocabulary codes are dropped and
recorded under `repairs`, hazard evidence must literally appear in the
route's own text, and empty-text routes are never sent to the model at all
(tags=None, "no-text"). --max-llm-routes caps the spend for testing; what
was skipped is counted, never silent.
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
import unicodedata

from . import geo, schema
from .runstore import Run, _atomic_write

DEFAULT_MODEL = "sonnet"
DEFAULT_BATCH = 20

PROMPT = """You are tagging climbing routes against a STRICT closed vocabulary. For each
route below, output your best judgement ONLY from the given text — never guess or infer
beyond what's stated. If there's no usable text, answer honestly with "UNSPECIFIED" /
empty arrays / null rather than inventing detail.

Closed vocabularies (use ONLY these exact values):
  protection: {protection}
  hazards: {hazards}
  character: {character}
  feature: {feature}
  incline: {incline}

Rules:
- hazards: only with clear evidence; "evidence" must be a short VERBATIM quote from that
  route's own text. No evidence -> omit the hazard.
- protection: only from explicit gear/bolt/peg/runout mentions; otherwise "UNSPECIFIED".
  Never infer from the grade.
- character/feature: only tags with real textual support; empty arrays are the correct
  answer for terse text.
- incline: only if the text describes the angle; otherwise null.
- flagged: field names you could not confidently resolve.

Output a JSON array, one object per route, IN THE SAME ORDER as listed, each shaped
EXACTLY like:
{{"protection": "<code>", "hazards": [{{"code": "<code>", "evidence": "<verbatim quote>"}}],
  "character": ["<code>"], "feature": ["<code>"], "incline": "<code or null>",
  "flagged": ["<field>"]}}
Output ONLY the JSON array — no markdown fences, no commentary.

Routes:
{routes_block}
"""

MERGE_PROMPT = """For each numbered pair of crag records below, answer whether they are the
SAME physical crag (not parent/sub-area, not merely nearby). Consider name, coordinates
and region. Output ONLY a JSON array, one object per pair, in order:
[{{"pair": <n>, "same": true|false}}]

Pairs:
{pairs_block}
"""


# --- normalization / matching ------------------------------------------------

def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _dist_m(a: dict, b: dict) -> float | None:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return None
    return geo._haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])


# --- claude CLI --------------------------------------------------------------

def _claude(prompt: str, model: str) -> list:
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "json"],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude CLI error: {str(payload.get('result'))[:400]}")
    text = payload["result"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# --- tag validation ----------------------------------------------------------

def repair_tags(tag: dict, text: str) -> tuple[dict, list[str]]:
    """Never trust the model's own compliance: drop anything off-vocabulary or
    with fabricated evidence; every drop is recorded."""
    repairs = []
    out = {"protection": None, "hazards": [], "character": [], "feature": [],
           "incline": None, "flagged": list(tag.get("flagged") or [])}
    p = tag.get("protection")
    if p in schema.PROTECTION_GRADES:
        out["protection"] = p
    elif p not in (None, ""):
        repairs.append(f"protection:{p!r}")
    for h in tag.get("hazards") or []:
        code, ev = h.get("code"), (h.get("evidence") or "").strip()
        if code in schema.HAZARDS and ev and ev.lower() in (text or "").lower():
            out["hazards"].append({"code": code, "evidence": ev})
        else:
            repairs.append(f"hazard:{code!r}")
    for key, allowed in (("character", schema.CHARACTER), ("feature", schema.FEATURES)):
        for v in tag.get(key) or []:
            if v in allowed:
                out[key].append(v)
            else:
                repairs.append(f"{key}:{v!r}")
    inc = tag.get("incline")
    if inc in schema.INCLINES:
        out["incline"] = inc
    elif inc not in (None, ""):
        repairs.append(f"incline:{inc!r}")
    return out, repairs


def validate_curated(c: dict) -> list[str]:
    problems = []
    if c.get("rock_type") is not None and c["rock_type"] not in schema.ROCK_TYPES:
        problems.append(f"rock_type: {c['rock_type']!r}")
    enr = c.get("enrichment") or {}
    if enr.get("sun_window") is not None and enr["sun_window"] not in schema.SUN_WINDOWS:
        problems.append(f"sun_window: {enr['sun_window']!r}")
    for r in c["routes"]:
        for d in r["disciplines"]:
            if d not in schema.DISCIPLINES:
                problems.append(f"discipline {d!r} ({r['name']})")
        t = r.get("tags")
        if not t:
            continue
        if t["protection"] is not None and t["protection"] not in schema.PROTECTION_GRADES:
            problems.append(f"tag protection {t['protection']!r} ({r['name']})")
        for h in t["hazards"]:
            if h["code"] not in schema.HAZARDS:
                problems.append(f"tag hazard {h['code']!r} ({r['name']})")
        for v in t["character"]:
            if v not in schema.CHARACTER:
                problems.append(f"tag character {v!r} ({r['name']})")
        for v in t["feature"]:
            if v not in schema.FEATURES:
                problems.append(f"tag feature {v!r} ({r['name']})")
        if t["incline"] is not None and t["incline"] not in schema.INCLINES:
            problems.append(f"tag incline {t['incline']!r} ({r['name']})")
    return problems


# --- merging -----------------------------------------------------------------

def _load_crags(run_ids: list[str]) -> list[dict]:
    """Prefer enriched/ (has enrichment), fall back to parsed/."""
    out = []
    for rid in run_ids:
        run = Run.load(rid)
        src_dir = run.dir / "enriched"
        if not src_dir.exists() or not any(src_dir.glob("*.json")):
            src_dir = run.dir / "parsed"
        for f in sorted(src_dir.glob("*.json")):
            inv = json.loads(f.read_text())
            if inv.get("kind") == "chatter":
                continue
            for c in inv.get("crags") or []:
                c["_run"] = rid
                out.append(c)
    return out


def _merge_crag_group(group: list[dict]) -> dict:
    def first(key):
        return next((c.get(key) for c in group if c.get(key) is not None), None)
    routes = _merge_routes(group)
    return {
        "name": max((c["name"] for c in group), key=len),
        "sources": [{"source": c["source"], "source_id": c["source_id"],
                     "url": c.get("url"), "run": c["_run"]} for c in group],
        "lat": first("lat"), "lon": first("lon"),
        "country": first("country"), "region": first("region"),
        "rock_type": first("rock_type"), "aspect": first("aspect"),
        "enrichment": first("enrichment"),
        "routes": routes,
    }


def _merge_routes(crag_group: list[dict]) -> list[dict]:
    groups: dict[str, list] = {}
    for c in crag_group:
        for r in c["routes"]:
            groups.setdefault(norm(r["name"]), []).append((c, r))
    out = []
    for _, members in groups.items():
        refs = [{"source": c["source"], "crag_source_id": c["source_id"],
                 "source_id": r["source_id"], "url": r.get("url"),
                 "grade": r.get("grade")} for c, r in members]
        def firstr(key):
            return next((r.get(key) for _, r in members if r.get(key) is not None), None)
        disciplines = sorted({d for _, r in members for d in r["disciplines"]})
        desc = max((r.get("description") or "" for _, r in members), key=len)
        out.append({
            "name": members[0][1]["name"],
            "refs": refs,
            "grade_by_source": {ref["source"]: ref["grade"] for ref in refs},
            "length_m": firstr("length_m"), "pitches": firstr("pitches"),
            "stars": firstr("stars"), "bolts_count": firstr("bolts_count"),
            "protection_source": firstr("protection"),
            "disciplines": disciplines, "fa": firstr("fa"),
            "description": desc, "tags": None,
        })
    return out


def dedupe_crags(crags: list[dict], model: str, log) -> tuple[list[list[dict]], int]:
    """Union-find over mechanical rules + one LLM adjudication call for the
    ambiguous near-misses. Returns (groups, llm_merges)."""
    parent = list(range(len(crags)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    ambiguous = []
    for i in range(len(crags)):
        for j in range(i + 1, len(crags)):
            a, b = crags[i], crags[j]
            if a["source"] == b["source"]:
                continue  # same-source duplicates don't exist at crag level
            d = _dist_m(a, b)
            sim = _sim(a["name"], b["name"])
            if norm(a["name"]) == norm(b["name"]) and (d is None or d < 1000):
                union(i, j)
            elif d is not None and d < 500 and 0.55 <= sim < 1.0:
                ambiguous.append((i, j))

    llm_merges = 0
    if ambiguous:
        blocks = []
        for n, (i, j) in enumerate(ambiguous):
            a, b = crags[i], crags[j]
            blocks.append(f"[{n}] A: {a['name']!r} ({a['source']}, {a.get('lat')},{a.get('lon')}, "
                          f"{a.get('region')}) vs B: {b['name']!r} ({b['source']}, "
                          f"{b.get('lat')},{b.get('lon')}, {b.get('region')})")
        log(f"llm: adjudicating {len(ambiguous)} ambiguous crag pair(s)")
        try:
            verdicts = _claude(MERGE_PROMPT.format(pairs_block="\n".join(blocks)), model)
            for v in verdicts:
                if v.get("same") is True and isinstance(v.get("pair"), int) and v["pair"] < len(ambiguous):
                    i, j = ambiguous[v["pair"]]
                    union(i, j)
                    llm_merges += 1
        except Exception as e:  # conservative: an LLM failure never merges
            log(f"llm: merge adjudication failed ({e}) — leaving pairs unmerged")

    groups: dict[int, list] = {}
    for i, c in enumerate(crags):
        groups.setdefault(find(i), []).append(c)
    return list(groups.values()), llm_merges


def _link_same_routes_across_crags(merged: list[dict]) -> int:
    """The granularity dedupe: same-named routes on DIFFERENT (unmerged) crags
    within 2 km, from different sources, get mutual `same_as` refs. Entities
    stay under their own crags — identity is recorded, not collapsed."""
    index: dict[str, list] = {}
    for c in merged:
        for r in c["routes"]:
            index.setdefault(norm(r["name"]), []).append((c, r))
    linked = 0
    for members in index.values():
        if len(members) < 2:
            continue
        for c, r in members:
            others = []
            for c2, r2 in members:
                if r2 is r or c2 is c:
                    continue
                srcs, srcs2 = {x["source"] for x in r["refs"]}, {x["source"] for x in r2["refs"]}
                d = _dist_m(c, c2)
                if srcs != srcs2 and d is not None and d < 2000:
                    others.extend(x for x in r2["refs"] if x["source"] not in srcs)
            if others:
                r["same_as"] = others
                linked += 1
    return linked


# --- the phase ---------------------------------------------------------------

def llm_curate(primary_run: str, with_runs: list[str], model: str,
               batch_size: int, max_llm_routes: int | None) -> dict:
    run = Run.load(primary_run)
    run_ids = [primary_run] + with_runs
    crags_in = _load_crags(run_ids)
    run.log(f"llm: {len(crags_in)} crags in from {len(run_ids)} run(s)")

    groups, llm_merges = dedupe_crags(crags_in, model, run.log)
    merged = [_merge_crag_group(g) for g in groups]
    routes = [r for c in merged for r in c["routes"]]
    cross = _link_same_routes_across_crags(merged)
    cross += sum(1 for r in routes if len({ref["source"] for ref in r["refs"]}) > 1)
    run.log(f"llm: {len(merged)} crags out ({llm_merges} LLM-confirmed merges), "
            f"{len(routes)} routes ({cross} matched cross-source)")

    # -- tagging
    enums = {"protection": sorted(schema.PROTECTION_GRADES),
             "hazards": sorted(schema.HAZARDS), "character": sorted(schema.CHARACTER),
             "feature": sorted(schema.FEATURES), "incline": sorted(schema.INCLINES)}
    taggable = [r for r in routes if (r["description"] or "").strip()]
    no_text = len(routes) - len(taggable)
    capped = None
    if max_llm_routes is not None and len(taggable) > max_llm_routes:
        capped = f"max_llm_routes={max_llm_routes}: tagged first {max_llm_routes} of {len(taggable)} taggable routes"
        taggable = taggable[:max_llm_routes]
    tagged = repaired_total = 0
    for start in range(0, len(taggable), batch_size):
        chunk = taggable[start:start + batch_size]
        block = "\n".join(
            f"[{i}] {r['name']} ({next((g['value'] for g in r['grade_by_source'].values() if g), 'grade unknown')}): {r['description'][:1200]}"
            for i, r in enumerate(chunk))
        results = _claude(PROMPT.format(routes_block=block, **{k: ", ".join(v) for k, v in enums.items()}), model)
        if len(results) != len(chunk):
            raise RuntimeError(f"llm returned {len(results)} tags for {len(chunk)} routes")
        for r, raw_tag in zip(chunk, results):
            tag, repairs = repair_tags(raw_tag, r["description"])
            tag["repairs"] = repairs
            repaired_total += len(repairs)
            r["tags"] = tag
            tagged += 1
        run.log(f"llm: tagged {tagged}/{len(taggable)} routes ({repaired_total} repairs so far)")

    problems = [p for c in merged for p in validate_curated(c)]
    if problems:
        raise RuntimeError(f"llm-curated output failed taxonomy validation: {problems[:5]}")

    out = {
        "runs": run_ids, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": model, "status": "llm-curated",   # explicitly pre-human
        "counts": {"crags_in": len(crags_in), "crags_out": len(merged),
                   "llm_confirmed_merges": llm_merges,
                   "routes": len(routes), "cross_source_routes": cross,
                   "routes_tagged": tagged, "routes_no_text": no_text,
                   "tag_repairs": repaired_total, "capped": capped},
        "crags": merged,
    }
    (run.dir / "llm-curated").mkdir(exist_ok=True)
    _atomic_write(run.dir / "llm-curated" / "inventory.json", out)
    run.log(f"llm: published llm-curated/inventory.json — {out['counts']}")
    return out["counts"]

"""Chatter CLI — per-crag web mentions via SerpAPI, the OTHER output type
(kept out of the scrape inventory by the 2026-08-11 design ruling: different
tool, different schema — added 2026-08-12).

Query shape is the winner of the July 2026 experiment (corpus/tools/
serp_query_test*.py, "E-combined" over 12 crags x 4 variants):
    "<crag>" climbing (site:ukclimbing.com OR site:reddit.com OR
    site:instagram.com OR site:facebook.com OR site:youtube.com OR site:tiktok.com)
against google.co.uk / gl=uk / hl=en / tbs=qdr:<window>. UK-biased on purpose
— that's where the corpus lives today; widen per-region when needed.

Same run-directory contract as the scrape: raw/serp/*.json holds each verbatim
SerpAPI response, parsed/chatter.json holds schema-validated docs. Every doc
is mechanical (title/snippet/url/date verbatim from the result) — deciding
what a post is ABOUT is judgment and lives in the link step (mechanical name
matching now, LLM later).

The SerpAPI key is shared with the trip flight monitor (repo-root .env):
every run checks account quota first and refuses to leave fewer than
MIN_QUOTA_LEFT searches unless --force.

doc = {
    source: "serpapi-google",
    seed,                # the crag name this query was about
    query,               # the full q sent
    position,            # organic rank
    title, url, site, snippet,     # verbatim
    published_at,        # ISO date parsed from SerpAPI's date string | None
    published_raw,       # SerpAPI's own date string | None (kept verbatim)
}
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .runstore import Run

SOURCE_ID = "serpapi-google"
MIN_QUOTA_LEFT = 25
SITES = "site:ukclimbing.com OR site:reddit.com OR site:instagram.com OR site:facebook.com OR site:youtube.com OR site:tiktok.com"

DOC_KEYS = {"source", "seed", "query", "position", "title", "url", "site",
            "snippet", "published_at", "published_raw"}


def doc_problems(d: dict) -> list[str]:
    problems = []
    if set(d) != DOC_KEYS:
        problems.append(f"doc keys off: extra={set(d) - DOC_KEYS} missing={DOC_KEYS - set(d)}")
    if not d.get("url"):
        problems.append("doc with no url")
    if d.get("published_at") and not re.match(r"^\d{4}-\d{2}-\d{2}$", d["published_at"]):
        problems.append(f"published_at not ISO date: {d['published_at']!r}")
    return problems


def load_key() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("SERPAPI_KEY="):
            return line.strip().split("=", 1)[1]
    raise RuntimeError("SERPAPI_KEY not found in repo-root .env")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def quota_left(key: str) -> int:
    acct = _get(f"https://serpapi.com/account.json?api_key={key}")
    return int(acct.get("plan_searches_left") or acct.get("total_searches_left") or 0)


def build_query(name: str) -> str:
    return f'"{name}" climbing ({SITES})'


def _published(date_str: str | None) -> str | None:
    """SerpAPI dates are '2 days ago' / '3 weeks ago' / 'Jul 15, 2026' —
    mechanical conversion to an ISO date, None when unparseable."""
    if not date_str:
        return None
    s = date_str.strip()
    m = re.match(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"minute": 0, "hour": 0, "day": n, "week": n * 7, "month": n * 30}[unit]
        if unit in ("minute", "hour"):
            days = 0
        return (dt.date.today() - dt.timedelta(days=days)).isoformat()
    for fmt in ("%b %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _docs_from_response(seed: str, query: str, payload: dict) -> list[dict]:
    docs = []
    for r in payload.get("organic_results") or []:
        url = r.get("link")
        if not url:
            continue
        docs.append({
            "source": SOURCE_ID,
            "seed": seed,
            "query": query,
            "position": r.get("position"),
            "title": r.get("title") or "",
            "url": url,
            "site": urllib.parse.urlparse(url).netloc,
            "snippet": r.get("snippet") or "",
            "published_at": _published(r.get("date")),
            "published_raw": r.get("date"),
        })
    return docs


def run_chatter(seeds: list[str], window: str, num: int, force: bool) -> Run:
    key = load_key()
    left = quota_left(key)
    if not force and left - len(seeds) < MIN_QUOTA_LEFT:
        raise RuntimeError(
            f"only {left} SerpAPI searches left; {len(seeds)} needed would drop below "
            f"the {MIN_QUOTA_LEFT} reserved for the flight monitor — --force to override")

    run = Run.create(None, ["serp"], {"window": window, "num": num}, {}, kind="chatter")
    run.log(f"chatter: {len(seeds)} seed(s), window={window}, quota_left={left}")
    docs, queries = [], []
    for seed in seeds:
        q = build_query(seed)
        params = {"engine": "google", "google_domain": "google.co.uk", "gl": "uk",
                  "hl": "en", "num": str(num), "tbs": f"qdr:{window}",
                  "q": q, "api_key": key}
        payload = _get("https://serpapi.com/search.json?" + urllib.parse.urlencode(params))
        item = {"kind": "serp", "id": seed}
        run.save_raw("serp", item, payload)
        new = _docs_from_response(seed, q, payload)
        for d in new:
            problems = doc_problems(d)
            if problems:
                raise RuntimeError(f"chatter schema violation ({d.get('url')}): {problems}")
        docs.extend(new)
        queries.append({"seed": seed, "q": q, "docs": len(new)})
        run.log(f"chatter: {seed} -> {len(new)} doc(s)")
        time.sleep(1.0)

    payload = {
        "run_id": run.run_id, "kind": "chatter", "source": SOURCE_ID,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "window": window, "queries": queries,
        "counts": {"docs": len(docs)},
        "docs": docs,
    }
    from .runstore import _atomic_write
    _atomic_write(run.dir / "parsed" / "chatter.json", payload)
    for s in ("serp",):
        run.set_status(s, "done")
    run.log(f"chatter: done — {len(docs)} docs across {len(seeds)} seed(s)")
    return run


# --- link step ---------------------------------------------------------------

def _corpus_crags() -> list[dict]:
    path = Path(__file__).resolve().parent.parent / "corpus" / "record" / "areas.json"
    rows = json.loads(path.read_text())["areas"]
    return [{"name": r["name"], "where": "corpus", "source_id": str(r["id"])}
            for r in rows if r["kind"] in ("crag", "sector") and r.get("name")]


def _scrape_crags(run_ids: list[str]) -> list[dict]:
    out = []
    for rid in run_ids:
        run = Run.load(rid)
        for f in (run.dir / "parsed").glob("*.json"):
            inv = json.loads(f.read_text())
            for c in inv.get("crags") or []:
                out.append({"name": c["name"], "where": f"run:{rid}:{c['source']}",
                            "source_id": c["source_id"]})
    return out


def link_chatter(chatter_run_id: str, against: list[str]) -> dict:
    """Mechanical linking: match known crag names (corpus record + scrape-run
    inventories) against each doc's title+snippet by case-insensitive
    word-boundary search (names <4 chars skipped — too collision-prone).
    Seeds are classified for the ingest decision: in corpus / scraped-only /
    not-ingested (= candidate for a scrape run). Anything smarter than string
    matching (which crag a vague post REALLY means) is the LLM phase's job."""
    run = Run.load(chatter_run_id)
    parsed = json.loads((run.dir / "parsed" / "chatter.json").read_text())
    known = _corpus_crags() + _scrape_crags(against)

    doc_links = []
    for d in parsed["docs"]:
        text = f"{d['title']} {d['snippet']}"
        matched = []
        for k in known:
            if len(k["name"]) < 4:
                continue
            if re.search(rf"\b{re.escape(k['name'])}\b", text, re.I):
                matched.append({**k, "via": "text"})
            elif k["name"].strip().lower() == d["seed"].strip().lower():
                matched.append({**k, "via": "seeded"})
        doc_links.append({"url": d["url"], "seed": d["seed"], "matched": matched})

    seeds = []
    for q in parsed["queries"]:
        name = q["seed"].strip().lower()
        in_corpus = any(k["name"].strip().lower() == name for k in known if k["where"] == "corpus")
        in_runs = sorted({k["where"] for k in known
                          if k["where"] != "corpus" and k["name"].strip().lower() == name})
        status = ("in-corpus" if in_corpus else
                  "scraped-only" if in_runs else "not-ingested")
        seeds.append({"seed": q["seed"], "corpus": in_corpus, "scrape_runs": in_runs,
                      "status": status, "docs": q["docs"]})

    out = {
        "chatter_run": chatter_run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "against_runs": against,
        "known_crags": len(known),
        "seeds": seeds,
        "doc_links": doc_links,
        "counts": {
            "docs": len(doc_links),
            "docs_linked": sum(1 for d in doc_links if d["matched"]),
            "docs_unlinked": sum(1 for d in doc_links if not d["matched"]),
            "ingest_candidates": [s["seed"] for s in seeds if s["status"] == "not-ingested"],
        },
    }
    from .runstore import _atomic_write
    _atomic_write(run.dir / "links.json", out)
    return out

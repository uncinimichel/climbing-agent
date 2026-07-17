#!/usr/bin/env python3
"""Round 2 of the SerpAPI query experiment (see serp_query_test.py for round 1).

Tests two questions:
  E  - can one combined query replace A-broad + C-forums? (site: filters restrict,
       so E measures what open-web recall the combination loses)
  L  - do non-UK crags get better results from their local Google domain and
       language (google.es "escalada", google.fr "escalade", ...) than from the
       round-1 google.co.uk baseline?

Raw responses land next to round 1 in db/.raw_cache/serp-query-tests/ and are
never committed. Run cost: 12 (E) + 4 (L-local) + 4 (L-en) = 20 searches,
quota-guarded like round 1.
"""
import json, os, sys, time, urllib.parse, urllib.request, datetime, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DATE = "2026-07-17-round2"
OUT_DIR = os.path.join(ROOT, ".raw_cache", "serp-query-tests", RUN_DATE)
MIN_QUOTA_LEFT = 250

CRAGS = [
    ("fair-head", "Fair Head"), ("pigeon-rock", "Pigeon Rock"),
    ("tryfan", "Tryfan"), ("dinorwig", "Dinorwig"),
    ("avon-gorge", "Avon Gorge"), ("bosigran", "Bosigran"),
    ("scafell", "Scafell"), ("old-man-of-hoy", "Old Man of Hoy"),
    ("penon-de-ifach", "Peñón de Ifach"), ("freyr", "Freyr"),
    ("calanques", "Calanques"), ("devils-tower", "Devils Tower"),
]
E_TEMPLATE = ('"{name}" climbing (site:ukclimbing.com OR site:reddit.com OR '
              'site:instagram.com OR site:facebook.com OR site:youtube.com OR site:tiktok.com)')
UK_PARAMS = {"engine": "google", "google_domain": "google.co.uk", "gl": "uk",
             "hl": "en", "num": "20", "tbs": "qdr:w2"}

# (slug, local query, google_domain, gl, hl, english query for L-en control)
LOCAL = [
    ("penon-de-ifach", '"Peñón de Ifach" escalada', "google.es", "es", "es", '"Peñón de Ifach" climbing'),
    ("calanques",      '"Calanques" escalade',      "google.fr", "fr", "fr", '"Calanques" climbing'),
    ("freyr",          '"Freyr" escalade',           "google.be", "be", "fr", '"Freyr" climbing'),
    ("devils-tower",   '"Devils Tower" climbing',    "google.com", "us", "en", None),  # en == local
]

def load_key():
    with open(os.path.join(os.path.dirname(ROOT), ".env")) as f:
        for line in f:
            if line.startswith("SERPAPI_KEY="):
                return line.strip().split("=", 1)[1]
    sys.exit("SERPAPI_KEY not found in .env")

def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)

def rel_date_to_days(s):
    s = s.strip()
    m = re.match(r"(\d+)\s+(hour|day|week)s?\s+ago", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return 0 if unit == "hour" else (n if unit == "day" else n * 7)
    for fmt in ("%b %d, %Y", "%d %b %Y"):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            return (datetime.date(2026, 7, 17) - d).days
        except ValueError:
            pass
    return None

def run_search(key, q, params, tag, slug, manifest, summary):
    p = dict(params, q=q, api_key=key)
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(p)
    try:
        data = get_json(url)
    except Exception as e:
        print(f"{slug} {tag}: ERROR {e}", flush=True)
        summary.setdefault(slug, {})[tag] = {"error": str(e)}
        return
    raw_path = os.path.join(OUT_DIR, f"{slug}__{tag}.json")
    with open(raw_path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    rows = []
    for r in data.get("organic_results", []):
        days = rel_date_to_days(r["date"]) if r.get("date") else None
        rows.append({"pos": r.get("position"), "title": r.get("title"),
                     "link": r.get("link"),
                     "domain": urllib.parse.urlparse(r.get("link", "")).netloc,
                     "date": r.get("date"), "days_ago": days,
                     "snippet": (r.get("snippet") or "")[:300]})
    dated = [r for r in rows if r["days_ago"] is not None and r["days_ago"] <= 14]
    summary.setdefault(slug, {})[tag] = {
        "query": q, "params": {k: v for k, v in params.items() if k != "num"},
        "total": len(rows), "dated_within_14d": len(dated),
        "domains": sorted({r["domain"] for r in rows}), "results": rows}
    manifest["searches"].append({"crag": slug, "tag": tag, "q": q,
                                 "google_domain": params["google_domain"],
                                 "gl": params["gl"], "hl": params["hl"],
                                 "raw_file": os.path.basename(raw_path)})
    print(f"{slug} {tag}: {len(rows)} results, {len(dated)} dated<=14d", flush=True)
    time.sleep(1.5)

def main():
    key = load_key()
    acct = get_json(f"https://serpapi.com/account.json?api_key={key}")
    left = acct.get("total_searches_left", 0)
    cost = len(CRAGS) + sum(1 for l in LOCAL) + sum(1 for l in LOCAL if l[5])
    print(f"Account: {acct.get('plan_name')} | left={left} | this run costs {cost}")
    if left - cost < MIN_QUOTA_LEFT:
        sys.exit(f"ABORT: would leave {left - cost} < {MIN_QUOTA_LEFT}")

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {"run_date": RUN_DATE, "e_template": E_TEMPLATE,
                "uk_params": UK_PARAMS, "quota_before": left, "searches": []}
    summary = {}

    for slug, name in CRAGS:
        run_search(key, E_TEMPLATE.format(name=name), UK_PARAMS, "E-combined",
                   slug, manifest, summary)
    for slug, local_q, dom, gl, hl, en_q in LOCAL:
        params = dict(UK_PARAMS, google_domain=dom, gl=gl, hl=hl)
        run_search(key, local_q, params, "L-local", slug, manifest, summary)
        if en_q:
            run_search(key, en_q, params, "L-en", slug, manifest, summary)

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    acct2 = get_json(f"https://serpapi.com/account.json?api_key={key}")
    print(f"DONE. Quota left: {acct2.get('total_searches_left')}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""One-off experiment: which Google query shape best surfaces recent per-crag
chatter via SerpAPI? Compares 4 query variants x 12 test crags over a 2-week
window. Raw responses land in db/.raw_cache/serp-query-tests/ (never committed);
a summary JSON is written alongside for the report.

Budget note: the SerpAPI key is shared with the trip flight monitor. This run
costs exactly len(CRAGS) x len(VARIANTS) searches (checked against account
quota before starting; aborts if fewer than MIN_QUOTA_LEFT would remain).
"""
import json, os, sys, time, urllib.parse, urllib.request, datetime, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DATE = "2026-07-17"
OUT_DIR = os.path.join(ROOT, ".raw_cache", "serp-query-tests", RUN_DATE)
MIN_QUOTA_LEFT = 250  # leave this many searches for the flight monitor

# --- exact inputs (documented for review) -----------------------------------
CRAGS = [
    ("fair-head", "Fair Head"),
    ("pigeon-rock", "Pigeon Rock"),
    ("tryfan", "Tryfan"),
    ("dinorwig", "Dinorwig"),
    ("avon-gorge", "Avon Gorge"),
    ("bosigran", "Bosigran"),
    ("scafell", "Scafell"),
    ("old-man-of-hoy", "Old Man of Hoy"),
    ("penon-de-ifach", "Peñón de Ifach"),
    ("freyr", "Freyr"),
    ("calanques", "Calanques"),
    ("devils-tower", "Devils Tower"),
]
VARIANTS = {
    "A-broad":      '"{name}" climbing',
    "B-conditions": '{name} climbing conditions',
    "C-forums":     '"{name}" climbing (site:ukclimbing.com OR site:reddit.com OR site:ukbouldering.com)',
    "D-social":     '"{name}" (site:instagram.com OR site:tiktok.com OR site:youtube.com OR site:x.com OR site:facebook.com)',
}
COMMON_PARAMS = {
    "engine": "google",
    "google_domain": "google.co.uk",
    "gl": "uk",
    "hl": "en",
    "num": "20",
    "tbs": "qdr:w2",  # past 2 weeks
}
# -----------------------------------------------------------------------------

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
    """SerpAPI 'date' fields look like 'Jul 12, 2026' or '2 days ago'."""
    s = s.strip()
    m = re.match(r"(\d+)\s+(hour|day|week)s?\s+ago", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return {"hour": 0, "day": n, "week": n * 7}[unit] if unit != "day" else n
    for fmt in ("%b %d, %Y", "%d %b %Y"):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            return (datetime.date(2026, 7, 17) - d).days
        except ValueError:
            pass
    return None

def main():
    key = load_key()
    acct = get_json(f"https://serpapi.com/account.json?api_key={key}")
    left = acct.get("total_searches_left", 0)
    cost = len(CRAGS) * len(VARIANTS)
    print(f"Account: {acct.get('plan_name')} | left={left} | this run costs {cost}")
    if left - cost < MIN_QUOTA_LEFT:
        sys.exit(f"ABORT: would leave {left - cost} < {MIN_QUOTA_LEFT} for flight monitor")

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {"run_date": RUN_DATE, "common_params": COMMON_PARAMS,
                "variants": VARIANTS, "crags": [n for _, n in CRAGS],
                "quota_before": left, "searches": []}
    summary = {}

    for slug, name in CRAGS:
        summary[slug] = {}
        for vkey, template in VARIANTS.items():
            q = template.format(name=name)
            params = dict(COMMON_PARAMS, q=q, api_key=key)
            url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
            try:
                data = get_json(url)
            except Exception as e:
                print(f"{slug} {vkey}: ERROR {e}", flush=True)
                summary[slug][vkey] = {"error": str(e)}
                continue
            raw_path = os.path.join(OUT_DIR, f"{slug}__{vkey}.json")
            with open(raw_path, "w") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
            organic = data.get("organic_results", [])
            rows = []
            for r in organic:
                days = rel_date_to_days(r["date"]) if r.get("date") else None
                rows.append({"pos": r.get("position"), "title": r.get("title"),
                             "link": r.get("link"),
                             "domain": urllib.parse.urlparse(r.get("link", "")).netloc,
                             "date": r.get("date"), "days_ago": days,
                             "snippet": (r.get("snippet") or "")[:300]})
            dated = [r for r in rows if r["days_ago"] is not None and r["days_ago"] <= 14]
            summary[slug][vkey] = {
                "query": q, "total": len(rows), "dated_within_14d": len(dated),
                "domains": sorted({r["domain"] for r in rows}),
                "results": rows,
            }
            manifest["searches"].append({"crag": name, "variant": vkey, "q": q,
                                         "raw_file": os.path.basename(raw_path),
                                         "organic_count": len(rows)})
            print(f"{slug} {vkey}: {len(rows)} results, {len(dated)} dated<=14d", flush=True)
            time.sleep(1.5)

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    acct2 = get_json(f"https://serpapi.com/account.json?api_key={key}")
    print(f"DONE. Quota left: {acct2.get('total_searches_left')}")

if __name__ == "__main__":
    main()

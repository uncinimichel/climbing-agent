#!/usr/bin/env python3
"""Fetch "recent chatter" (Google results from the last 2 weeks, via SerpAPI)
for the TOP-10 ranked venues, into cache/crag-chatter.json — which IS committed
(unlike venue-env.json): it holds only what the site publishes anyway (title,
link, short snippet, date), never raw API responses.

Query design comes from the 2026-07-17 query shoot-out (db/.raw_cache/
serp-query-tests/): per venue, one broad query ("<crag>" climbing, google.co.uk)
plus either the UKC/Reddit forums probe (UK & Ireland crags) or a local-language
query on the crag's own Google domain (continental crags). Combined queries were
tested and rejected — site: OR-lists reshuffle rankings and lose ~70% of results.

Budget: 10 venues x 2 queries, refreshed only when a venue's entry is older
than REFRESH_DAYS — so ~20 searches/week from the shared SerpAPI plan. The run
is quota-guarded (keeps MIN_QUOTA_LEFT for the flight monitor) and never fails
the build: on any problem it leaves the previous cache in place and exits 0.
"""
from __future__ import annotations
import json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "cache" / "crag-chatter.json"
RANK_HISTORY = ROOT / "trip-ni-july-2026" / "rank-history.json"
SHEET_CSV = ROOT / "climbing-trips.csv"

TOP_N = 10
REFRESH_DAYS = 6.5          # weekly cadence, with slack for the daily cron
MIN_QUOTA_LEFT = 180        # never starve the flight monitor
MAX_ITEMS_PER_VENUE = 8
WINDOW = "qdr:w2"           # past two weeks

UK_IE = {"england", "wales", "scotland", "northern ireland", "n. ireland", "ireland", "uk"}
# country -> (google_domain, gl, hl, local word for climbing)
LOCALE = {
    "spain": ("google.es", "es", "es", "escalada"),
    "france": ("google.fr", "fr", "fr", "escalade"),
    "belgium": ("google.be", "be", "fr", "escalade"),
    "italy": ("google.it", "it", "it", "arrampicata"),
    "austria": ("google.at", "at", "de", "klettern"),
    "germany": ("google.de", "de", "de", "klettern"),
    "switzerland": ("google.ch", "ch", "de", "klettern"),
    "croatia": ("google.hr", "hr", "hr", "penjanje"),
    "norway": ("google.no", "no", "no", "klatring"),
    "portugal": ("google.pt", "pt", "pt", "escalada"),
    "slovakia": ("google.sk", "sk", "sk", "lezenie"),
    "slovenia": ("google.si", "si", "sl", "plezanje"),
    "greece": ("google.gr", "gr", "el", "αναρρίχηση"),
}
UK_PARAMS = {"engine": "google", "google_domain": "google.co.uk", "gl": "uk",
             "hl": "en", "num": "20", "tbs": WINDOW}
FORUMS_SITES = "(site:ukclimbing.com OR site:reddit.com OR site:ukbouldering.com)"

SOCIAL_DOMAINS = ("instagram.", "facebook.", "tiktok.", "youtube.", "youtu.be", "x.com", "twitter.")
FORUM_DOMAINS = ("ukclimbing.", "reddit.", "ukbouldering.", "camptocamp.", "forum")

# Google localizes relative dates per hl= ("hace 2 días", "il y a 8 jours", ...).
REL_DATE = re.compile(
    r"(\d+)\s*(hour|day|week|día|dia|jour|semaine|heure|tag|woche|stunde|giorn|settiman|or[ae])",
    re.IGNORECASE)


def dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def top_ranked() -> list[str]:
    hist = json.loads(RANK_HISTORY.read_text())
    latest = sorted(hist.keys())[-1]
    return list(hist[latest])[:TOP_N]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def country_lookup() -> "callable":
    """shortName -> country. venues.json names match rank-history exactly;
    the sheet's Area column is looser ('Picos Europa', 'Mournes'), so fall back
    to normalized token-subset matching there."""
    import csv
    exact, sheet = {}, {}
    vjson = ROOT / "trip-ni-july-2026" / "venues.json"
    if vjson.exists():
        data = json.loads(vjson.read_text())
        for v in (data if isinstance(data, list) else data.get("venues", [])):
            if v.get("name") and v.get("country"):
                exact[v["name"]] = v["country"]
    if SHEET_CSV.exists():
        rows = list(csv.reader(open(SHEET_CSV, newline="")))
        if len(rows) >= 3 and "Area" in rows[1] and "Country" in rows[1]:
            i_a, i_c = rows[1].index("Area"), rows[1].index("Country")
            for row in rows[2:]:
                if len(row) > max(i_a, i_c) and row[i_a].strip():
                    sheet[_norm(row[i_a])] = row[i_c].strip()

    def lookup(short_name: str) -> str:
        if short_name in exact:
            return exact[short_name]
        n = _norm(short_name)
        if n in sheet:
            return sheet[n]
        toks = set(n.split())
        for area_n, country in sheet.items():
            a_toks = set(area_n.split())
            if a_toks and (a_toks <= toks or toks <= a_toks):
                return country
        return ""

    return lookup


def search_name(short_name: str) -> str:
    """'West Cornwall (Bosigran)' -> 'Bosigran'; 'Mournes, NI' -> 'Mournes'."""
    m = re.search(r"\(([^)]+)\)", short_name)
    name = m.group(1) if m else short_name
    return re.sub(r",\s*NI$", "", name).strip()


def queries_for(short_name: str, country: str):
    """Yield (tag, query, params) per the shoot-out recipe."""
    name = search_name(short_name)
    yield ("broad", f'"{name}" climbing', UK_PARAMS)
    c = (country or "").strip().lower()
    if c in UK_IE or not c:
        yield ("forums", f'"{name}" climbing {FORUMS_SITES}', UK_PARAMS)
    elif c in LOCALE:
        dom, gl, hl, word = LOCALE[c]
        params = dict(UK_PARAMS, google_domain=dom, gl=gl, hl=hl)
        yield ("local", f'"{name}" {word}', params)
    # unknown non-UK country: broad only


def days_ago(date_str: str | None) -> int | None:
    if not date_str:
        return None
    s = date_str.strip()
    m = REL_DATE.search(s)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit.startswith(("hour", "heure", "stunde", "ora", "ore")):
            return 0
        if unit.startswith(("week", "semaine", "woche", "settiman")):
            return n * 7
        return n
    for fmt in ("%b %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            d = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - d).days)
        except ValueError:
            pass
    return None


def classify(domain: str) -> str:
    d = domain.lower()
    if any(x in d for x in SOCIAL_DOMAINS):
        return "social"
    if any(x in d for x in FORUM_DOMAINS):
        return "forum"
    return "web"


def fetch_venue(key: str, short_name: str, country: str):
    items, inputs, seen = [], [], set()
    for tag, q, params in queries_for(short_name, country):
        p = dict(params, q=q, api_key=key)
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(p)
        data = get_json(url)
        inputs.append({"tag": tag, "q": q,
                       "google_domain": params["google_domain"], "gl": params["gl"],
                       "hl": params["hl"], "tbs": params["tbs"]})
        for r in data.get("organic_results", []):
            link = r.get("link") or ""
            if not link or link in seen:
                continue
            seen.add(link)
            domain = urllib.parse.urlparse(link).netloc.replace("www.", "")
            items.append({
                "title": (r.get("title") or "")[:140],
                "link": link,
                "domain": domain,
                "src": classify(domain),
                "date": r.get("date"),
                "days_ago": days_ago(r.get("date")),
                "snippet": (r.get("snippet") or "")[:220],
                "via": tag,
            })
        time.sleep(1.5)
    # freshest first (undated results are still inside the 2-week window: last)
    items.sort(key=lambda x: (x["days_ago"] is None, x["days_ago"] or 0))
    return items[:MAX_ITEMS_PER_VENUE], inputs


def main():
    dotenv()
    key = os.environ.get("SERPAPI_KEY")
    cache = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
        except Exception:
            cache = {}
    venues_cache = cache.get("venues", {})

    if not key:
        print("chatter: no SERPAPI_KEY — keeping previous cache")
        return 0

    try:
        ranked = top_ranked()
    except Exception as e:
        print(f"chatter: cannot read rank history ({e}) — keeping previous cache")
        return 0

    now = datetime.now(timezone.utc)
    stale = []
    for name in ranked:
        ent = venues_cache.get(name)
        if not ent:
            stale.append(name)
            continue
        try:
            age = (now - datetime.fromisoformat(ent["fetched_at"])).total_seconds() / 86400
        except Exception:
            age = 999
        if age >= REFRESH_DAYS:
            stale.append(name)
    if not stale:
        print("chatter: all top-10 venues fresh — nothing to do")
        return 0

    country_of = country_lookup()
    cost = sum(len(list(queries_for(n, country_of(n)))) for n in stale)
    try:
        acct = get_json(f"https://serpapi.com/account.json?api_key={key}")
        left = acct.get("total_searches_left", 0)
    except Exception as e:
        print(f"chatter: account check failed ({e}) — keeping previous cache")
        return 0
    if left - cost < MIN_QUOTA_LEFT:
        print(f"chatter: quota too tight (left={left}, cost={cost}, "
              f"reserve={MIN_QUOTA_LEFT}) — keeping previous cache")
        return 0

    print(f"chatter: refreshing {len(stale)} venue(s), ~{cost} searches (left={left})")
    for name in stale:
        try:
            items, inputs = fetch_venue(key, name, country_of(name))
        except Exception as e:
            print(f"chatter: {name}: fetch failed ({e}) — keeping previous entry")
            continue
        venues_cache[name] = {
            "fetched_at": now.isoformat(timespec="seconds"),
            "search_name": search_name(name),
            "country": country_of(name),
            "query_inputs": inputs,
            "items": items,
        }
        print(f"chatter: {name}: {len(items)} items "
              f"({sum(1 for i in items if i['days_ago'] is not None)} dated)")

    cache = {"generated": now.isoformat(timespec="seconds"),
             "window": "past 2 weeks (tbs=qdr:w2)",
             "venues": venues_cache}
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n")
    print(f"chatter: wrote {CACHE_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

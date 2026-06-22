#!/usr/bin/env python3
"""Fetch cheapest flights per date combo via SerpApi's Google Flights engine and
write prices + view/booking links into flights-latest.json.

Reads SERPAPI_KEY from the environment (GitHub Actions secret) or a local,
gitignored .env file. Self-skips (exit 0, no changes) if the key is absent, so
the report still builds without it. No third-party dependencies.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
FLIGHTS_CFG = json.loads((ROOT / "flights.json").read_text())
DATA_PATH = ROOT / "flights-latest.json"


def load_dotenv():
    f = REPO_ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_dotenv()
KEY = os.environ.get("SERPAPI_KEY")
# One call per combo: Google Flights accepts comma-separated airports, so all
# London airports + both Belfast airports are covered in a SINGLE search
# (keeps us inside the SerpApi monthly quota: 3 combos = 3 searches/day).
DEP = ",".join(FLIGHTS_CFG["route"]["origin_airports"])
ARR = ",".join(FLIGHTS_CFG["route"]["dest_airports"])


def _get(url):
    with urllib.request.urlopen(url, timeout=45) as r:
        return json.load(r)


def serp_google_flights(out_date, back_date):
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": DEP, "arrival_id": ARR,
        "outbound_date": out_date, "return_date": back_date,
        "currency": "GBP", "hl": "en", "gl": "uk", "type": "1",
        "adults": FLIGHTS_CFG["route"]["passengers"], "api_key": KEY,
    })
    data = _get(f"https://serpapi.com/search.json?{q}")
    best = None
    for o in (data.get("best_flights") or []) + (data.get("other_flights") or []):
        price = o.get("price")
        if price is None:
            continue
        legs = o.get("flights") or []
        if best is None or price < best["price"]:
            best = {
                "price": price,
                "airline": legs[0].get("airline") if legs else "?",
                "from": legs[0].get("departure_airport", {}).get("id") if legs else "?",
                "to": legs[0].get("arrival_airport", {}).get("id") if legs else "?",
                "stops": max(0, len(legs) - 1),
            }
    google_url = (data.get("search_metadata") or {}).get("google_flights_url")
    return best, google_url, data.get("error")


def skyscanner_url(dep, arr, out_date, back_date):
    def yymmdd(s):
        return f"{date.fromisoformat(s):%y%m%d}"
    return (f"https://www.skyscanner.net/transport/flights/"
            f"{dep.lower()}/{arr.lower()}/{yymmdd(out_date)}/{yymmdd(back_date)}/")


def main():
    if not KEY:
        print("SERPAPI_KEY not set — skipping flight fetch (report still builds).")
        return
    data = json.loads(DATA_PATH.read_text())
    for c in FLIGHTS_CFG["combos"]:
        entry = data["combos"].setdefault(c["id"], {})
        try:
            best, google_url, err = serp_google_flights(c["out"], c["back"])
        except Exception as e:
            entry["notes"] = f"fetch error: {e}"
            print(f"  {c['id']}: error {e}")
            continue
        if best:
            stops = "direct" if best["stops"] == 0 else f"{best['stops']} stop(s)"
            entry.update({
                "cheapest_gbp": round(best["price"]),
                "airline": best["airline"],
                "out_airport": best["from"],
                "back_airport": best["to"],
                "stops": stops,
                "view_url": google_url or skyscanner_url(best["from"], best["to"], c["out"], c["back"]),
                "book_url": skyscanner_url(best["from"], best["to"], c["out"], c["back"]),
                "notes": f"{best['airline']}, {stops}, from {best['from']} — live Google Flights",
            })
            print(f"  {c['id']}: £{round(best['price'])} {best['airline']} ({stops}) from {best['from']}")
        else:
            entry["cheapest_gbp"] = None
            entry["notes"] = err or "no offers returned"
            print(f"  {c['id']}: no offers ({err})")
    data["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC (Google Flights / SerpApi)")
    DATA_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print("Updated flights-latest.json")


if __name__ == "__main__":
    main()

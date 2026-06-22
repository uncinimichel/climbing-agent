#!/usr/bin/env python3
"""Optionally auto-fetch cheapest flight prices via the Amadeus self-service API
and write them into flights-latest.json.

Self-skips (exit 0, no changes) when AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET
are not set — so the daily report still works without a key.

Get a FREE key at https://developers.amadeus.com (Self-Service, ~2 min), then add
the two values as GitHub Actions secrets:
  gh secret set AMADEUS_CLIENT_ID
  gh secret set AMADEUS_CLIENT_SECRET
Default host is the free test environment; override with AMADEUS_HOST if you have
production access. No dependencies — standard library only.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLIGHTS_CFG = json.loads((ROOT / "flights.json").read_text())
DATA_PATH = ROOT / "flights-latest.json"

CID = os.environ.get("AMADEUS_CLIENT_ID")
SECRET = os.environ.get("AMADEUS_CLIENT_SECRET")
HOST = os.environ.get("AMADEUS_HOST", "https://test.api.amadeus.com")


def get_token():
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CID, "client_secret": SECRET,
    }).encode()
    req = urllib.request.Request(
        f"{HOST}/v1/security/oauth2/token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def cheapest_offer(token, origin, dest, out_date, back_date):
    q = urllib.parse.urlencode({
        "originLocationCode": origin, "destinationLocationCode": dest,
        "departureDate": out_date, "returnDate": back_date,
        "adults": FLIGHTS_CFG["route"]["passengers"], "currencyCode": "GBP",
        "max": 5,
    })
    req = urllib.request.Request(
        f"{HOST}/v2/shopping/flight-offers?{q}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            offers = json.load(r).get("data", [])
    except Exception:
        return None
    best = None
    for o in offers:
        price = float(o["price"]["grandTotal"])
        airline = (o.get("validatingAirlineCodes") or ["?"])[0]
        if best is None or price < best[0]:
            best = (price, airline)
    return best


def main():
    if not (CID and SECRET):
        print("Amadeus credentials not set — skipping flight fetch (report still builds).")
        return
    token = get_token()
    data = json.loads(DATA_PATH.read_text())
    origins = ["LON"]                                   # London city code = all airports
    dests = FLIGHTS_CFG["route"]["dest_airports"]       # BFS, BHD
    for c in FLIGHTS_CFG["combos"]:
        best = None
        for o in origins:
            for dst in dests:
                r = cheapest_offer(token, o, dst, c["out"], c["back"])
                if r and (best is None or r[0] < best[0]):
                    best = (r[0], r[1], o, dst)
        entry = data["combos"].setdefault(c["id"], {})
        if best:
            entry.update({
                "cheapest_gbp": round(best[0]), "airline": best[1],
                "out_airport": f"{best[2]}→{best[3]}", "back_airport": f"{best[3]}→{best[2]}",
                "notes": "live Amadeus quote",
            })
        else:
            entry["notes"] = "no offers returned for these dates"
    data["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC (Amadeus live)")
    DATA_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print("Updated flights-latest.json from Amadeus.")


if __name__ == "__main__":
    main()

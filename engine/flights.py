"""Flights (Google Flights via SerpApi) — moved from update_report.py's
attach_flights/traveller_flight/serp_flights, parameterized on TripContext and
split so pricing is a pure function (price_top_venues) instead of a function
that mutates a module-level FLIGHTS_DATA global and writes flights-latest.json
as a side effect — the caller decides where the result goes.

For the TOP-N ranked venues we price a representative round-trip for every
traveller (ctx.traveller_keys) into that venue's airport, with view/book
links. A venue's travel dict can mark a traveller local/drive. To stay within the
SerpApi quota we price only the top N venues, one representative combo each.

quota_guard/flight_cache are the quota.QuotaGuard/quota.FlightCache seams (see
quota.py) — the cron driver passes the permissive no-op implementations so its
behavior is unchanged; a real budget-tracking implementation is milestone M3.
"""
import sys
import urllib.parse
from datetime import date

from .http import get_json, redact
from .quota import AlwaysAllowQuotaGuard, NullFlightCache


def skyscanner_url(dep, arr, out_date, back_date):
    def yymmdd(s):
        return f"{date.fromisoformat(s):%y%m%d}"
    return (f"https://www.skyscanner.net/transport/flights/"
            f"{dep.lower()}/{arr.lower()}/{yymmdd(out_date)}/{yymmdd(back_date)}/")


def _hhmm(t):
    # "2026-07-24 06:25" -> "06:25"
    return t[-5:] if t and len(t) >= 5 else "—"


def serp_flights(dep, arr, out_date, back_date, passengers, serpapi_key):
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": dep, "arrival_id": arr,
        "outbound_date": out_date, "return_date": back_date,
        "currency": "GBP", "hl": "en", "gl": "uk", "type": "1",
        "adults": passengers, "api_key": serpapi_key,
    })
    data = get_json(f"https://serpapi.com/search.json?{q}", retries=2, redact_secret=serpapi_key)
    opts = []
    for o in (data.get("best_flights") or []) + (data.get("other_flights") or []):
        price = o.get("price")
        legs = o.get("flights") or []
        if price is None or not legs:
            continue
        dep_ap = legs[0].get("departure_airport", {})
        arr_ap = legs[-1].get("arrival_airport", {})
        opts.append({
            "price": round(price), "airline": legs[0].get("airline", "?"),
            "from": dep_ap.get("id", dep.split(",")[0]), "to": arr_ap.get("id", arr),
            "dep": _hhmm(dep_ap.get("time")), "arr": _hhmm(arr_ap.get("time")),
            "stops": max(0, len(legs) - 1),
        })
    if not opts:
        return None
    # rank by best value: price plus a £40 penalty per stop (a cheap 1-stop can
    # beat a pricey nonstop, but stops are penalised). Bolded option = best value.
    opts.sort(key=lambda x: x["price"] + 40 * x["stops"])
    seen, uniq = set(), []
    for o in opts:
        k = (o["from"], o["dep"], o["price"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    top = uniq[:3]
    google = (data.get("search_metadata") or {}).get("google_flights_url")
    return {
        "mode": "fly", "to": arr, "options": top,
        "view_url": google or skyscanner_url(top[0]["from"], arr, out_date, back_date),
        "book_url": skyscanner_url(top[0]["from"], arr, out_date, back_date),
    }


def traveller_flight(venue, who, ctx, quota_guard=None, flight_cache=None):
    """Return a flight cell dict for one traveller to this venue."""
    quota_guard = quota_guard or AlwaysAllowQuotaGuard()
    flight_cache = flight_cache or NullFlightCache()
    t = venue.get("travel", {}).get(who, {})
    mode = t.get("mode")
    if mode in ("local", "drive"):
        return {"mode": mode}
    out_date, back_date = ctx.rep_combo["out"], ctx.rep_combo["back"]
    origin = ctx.origin[who]
    if mode == "fly" and ctx.serpapi_key:
        route_key = f"{origin}->{t.get('to')}"
        dates_key = f"{out_date}|{back_date}"
        cached = flight_cache.get(route_key, dates_key)
        if cached is not None:
            return cached
        if quota_guard.can_spend(1):
            try:
                f = serp_flights(origin, t["to"], out_date, back_date,
                                  ctx.flights_cfg["route"]["passengers"], ctx.serpapi_key)
                if f:
                    quota_guard.record_spend(1)
                    flight_cache.set(route_key, dates_key, f)
                    return f
            except Exception as e:
                print(f"[warn] flight lookup failed ({who} -> {t.get('to')}): {redact(e, ctx.serpapi_key)}",
                      file=sys.stderr)
    # no key / quota refused / no result / error: still offer a search link so it's actionable
    if mode == "fly":
        return {"mode": "fly", "options": [], "to": t.get("to"),
                "book_url": skyscanner_url(origin.split(",")[0], t["to"], out_date, back_date)}
    return {"mode": "unknown"}


def price_top_venues(ranked, ctx, quota_guard=None, flight_cache=None, prev_prices=None):
    """Price flights for the top-N ranked venues (both travellers). Mutates
    each result's r["flights"] in place (apply_composite reads it back) and
    returns the {venue_name: flights} dict the caller persists (flights-latest
    .json for the cron; a trip's S3/DynamoDB record for a Lambda-computed trip).

    A run with no live price (no SerpApi key, quota refused, or a failed/empty
    lookup) reuses the last-known-good prices from `prev_prices` instead of
    falling back to bare links — this is the same degrade path
    engine.quota.QuotaGuard's "serve stale" behavior (§3 of the plan)
    generalizes."""
    prev = prev_prices or {}
    cache = {}
    for r in ranked[:ctx.top_n_flights]:
        if not r.get("ok") or r["score"] < 0:
            continue
        v = r["venue"]
        if r.get("flights"):          # already priced in an earlier pass this run
            cache[v["name"]] = r["flights"]
            continue
        flights = {}
        for w in ctx.traveller_keys:
            f = traveller_flight(v, w, ctx, quota_guard, flight_cache)
            if not f.get("options"):
                cached = (prev.get(v["name"]) or {}).get(w)
                if cached and cached.get("options"):
                    f = dict(cached, cached=True)   # reuse last-known prices
            flights[w] = f
        r["flights"] = flights
        cache[v["name"]] = r["flights"]
    return cache

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
from datetime import date, timedelta

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


def _guarded_search(origin, dest, out_date, back_date, ctx, quota_guard, flight_cache, label):
    """One SerpApi round-trip search behind the shared (route, dates) cache and
    the quota guard — the single spend path for baseline AND flex pricing.
    Returns the priced dict, or None (cache miss + quota refused / no result /
    error — the caller decides the fallback)."""
    route_key, dates_key = f"{origin}->{dest}", f"{out_date}|{back_date}"
    f = flight_cache.get(route_key, dates_key)
    if f is not None:
        return f
    if not quota_guard.can_spend(1):
        return None
    try:
        f = serp_flights(origin, dest, out_date, back_date,
                          ctx.flights_cfg["route"]["passengers"], ctx.serpapi_key)
    except Exception as e:
        print(f"[warn] flight lookup failed ({label}): {redact(e, ctx.serpapi_key)}", file=sys.stderr)
        return None
    if f:
        quota_guard.record_spend(1)
        flight_cache.set(route_key, dates_key, f)
    return f


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
        f = _guarded_search(origin, t["to"], out_date, back_date, ctx,
                             quota_guard, flight_cache, f"{who} -> {t.get('to')}")
        if f:
            return f
    # no key / quota refused / no result / error: still offer a search link so it's actionable
    if mode == "fly":
        return {"mode": "fly", "options": [], "to": t.get("to"),
                "book_url": skyscanner_url(origin.split(",")[0], t["to"], out_date, back_date)}
    return {"mode": "unknown"}


def flex_alternatives(venue, ctx, quota_guard=None, flight_cache=None,
                      prev_flex=None, today=None):
    """±flex_days whole-trip shifts for ONE venue (decision #33 §Date
    flexibility): same trip length, out and back moved together — 'leave a day
    earlier/later'. SerpApi's google_flights engine has no flexible-date
    search and its Deals engine can't pin an arrival airport, so each shift is
    its own (bounded) search: ≤ 2·flex_days calls per flying traveller, and
    the caller only asks for the top-ranked venue.

    Every alternative always carries a date-filled Skyscanner link (free, no
    key needed); a live price is added when key + quota allow. When a shift
    can't be priced this run, its last-known price is reused from `prev_flex`
    (the previous run's flights-latest.json 'flex' block — caller must only
    pass it when it belongs to the same venue).

    Returns {traveller_key: [{shift, out, back, book_url, price?, view_url?,
    cached?}, ...]} or None when flex is off / nobody flies."""
    n = int(getattr(ctx, "flex_days", 0) or 0)
    if n <= 0:
        return None
    quota_guard = quota_guard or AlwaysAllowQuotaGuard()
    flight_cache = flight_cache or NullFlightCache()
    out0 = date.fromisoformat(ctx.rep_combo["out"])
    back0 = date.fromisoformat(ctx.rep_combo["back"])
    today = today or date.today()
    prev = prev_flex or {}
    result = {}
    for who in ctx.traveller_keys:
        t = venue.get("travel", {}).get(who, {})
        if t.get("mode") != "fly" or not t.get("to"):
            continue
        origin = ctx.origin[who]
        alts = []
        for shift in range(-n, n + 1):
            if shift == 0:
                continue          # baseline dates are priced by the normal pass
            out, back = out0 + timedelta(days=shift), back0 + timedelta(days=shift)
            if out <= today:
                continue
            alt = {"shift": shift, "out": out.isoformat(), "back": back.isoformat(),
                   "book_url": skyscanner_url(origin.split(",")[0], t["to"],
                                               out.isoformat(), back.isoformat())}
            f = (_guarded_search(origin, t["to"], alt["out"], alt["back"], ctx,
                                  quota_guard, flight_cache, f"flex {who} {shift:+d}d -> {t.get('to')}")
                 if ctx.serpapi_key else None)
            if f and f.get("options"):
                alt["price"] = f["options"][0]["price"]
                alt["view_url"] = f.get("view_url") or alt["book_url"]
            else:
                pv = next((a for a in (prev.get(who) or [])
                           if a.get("shift") == shift and a.get("price") is not None), None)
                if pv:
                    alt["price"] = pv["price"]
                    alt["view_url"] = pv.get("view_url") or alt["book_url"]
                    alt["cached"] = True
            alts.append(alt)
        if alts:
            result[who] = alts
    return result or None


def best_flex_saving(alts, base_price):
    """The cheapest priced ±day alternative strictly cheaper than the baseline
    price, with its saving — or None. The one definition behind the markdown
    report line and the admin Manage line (the dashboard JS mirrors it
    client-side in flexHtml)."""
    priced = [a for a in (alts or []) if a.get("price") is not None]
    if base_price is None or not priced:
        return None
    best = min(priced, key=lambda a: a["price"])
    if best["price"] >= base_price:
        return None
    return dict(best, saving=base_price - best["price"])


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

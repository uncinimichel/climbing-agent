"""Accommodation — OpenStreetMap Overpass (free, no key). Moved verbatim from
update_report.py, parameterized on TripContext (for the rep combo's dates) and
explicit Cache instances instead of module-level globals.

Real named places to stay near each venue, in three shapes: self-catered
houses/apartments (Airbnb-style), campsites (bring your own tent + kit) and
hotels/hostels/huts (one room, 2 adults). OSM carries no prices, so each
lodging type gets a typical nightly estimate (clearly labelled est., for 2
people) which also feeds the travel component of the composite score. Results
are disk-cached and committed like the climatology — lodging stock changes
slowly and Overpass rate-limits bursts.
"""
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .geo import haversine_km
from .http import USER_AGENT, get_json, redact
from .models import short_name

STAY_RADIUS_KM = 15
STAY_ADULTS = 2
STAY_PER_CAT = 3                     # options shown per category
OSM_STAY_CAT = {                     # OSM tourism=* -> dashboard category
    "apartment": "house", "chalet": "house", "guest_house": "house",
    "camp_site": "camp",
    "hotel": "hotel", "hostel": "hotel", "alpine_hut": "hotel", "motel": "hotel",
}
STAY_TYPE_LBL = {
    "apartment": "Apartment", "chalet": "Chalet", "guest_house": "Guest house",
    "camp_site": "Campsite", "hotel": "Hotel", "hostel": "Hostel",
    "alpine_hut": "Mountain hut", "motel": "Motel",
}
# Mainstream OTAs (Booking.com, Hotels.com, Airbnb) essentially never list
# alpine huts/refuges — they're booked direct or through mountain federations
# (FEDME, FFCAM, CAI...) — so an OTA search for one just returns junk or
# nothing, which reads as "broken" even though the URL loads fine. Same
# reasoning as excluding campsites: don't offer a search an OTA can't answer.
NO_OTA_KINDS = {"camp_site", "alpine_hut"}
# typical £/night for TWO people — rough planning estimates, not live quotes
STAY_EST_NIGHT = {
    "apartment": 95, "chalet": 100, "guest_house": 85, "camp_site": 20,
    "hotel": 115, "hostel": 55, "alpine_hut": 70, "motel": 75,
}
CAMP_NOTE = "unserviced pitch — bring your own tent, mats and cooking kit"

LINK_RECHECK_DAYS = 14
LINK_DEAD_NOW = {404, 410}          # confirmed dead on a single check
LINK_DEAD_DAY = 86400

OVERPASS_HOSTS = ["https://overpass-api.de/api/interpreter",
                  "https://overpass.kumi.systems/api/interpreter",
                  "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]


def _amazon(q):
    return "https://www.amazon.co.uk/s?k=" + urllib.parse.quote(q)


def _booking_url(q, out_date, back_date):
    """Booking.com search pre-filled with the trip dates + 2 adults, 1 room."""
    return "https://www.booking.com/searchresults.html?" + urllib.parse.urlencode({
        "ss": q, "checkin": out_date, "checkout": back_date,
        "group_adults": STAY_ADULTS, "no_rooms": 1, "group_children": 0})


def _airbnb_url(q, out_date, back_date):
    """Airbnb area search pre-filled with the trip dates + 2 adults."""
    return (f"https://www.airbnb.co.uk/s/{urllib.parse.quote(q)}/homes?"
            + urllib.parse.urlencode({"adults": STAY_ADULTS,
                                      "checkin": out_date, "checkout": back_date}))


def _hotels_url(q, out_date, back_date):
    """Hotels.com search pre-filled with the trip dates + 2 adults, 1 room."""
    return "https://www.hotels.com/Hotel-Search?" + urllib.parse.urlencode({
        "destination": q, "startDate": out_date, "endDate": back_date,
        "rooms": 1, "adults": STAY_ADULTS})


def _turbo_url(lat, lon):
    """overpass-turbo deep-link that auto-runs the venue's lodging query (&R):
    every place to stay pin-pointed on a real map, centred on the crag."""
    kinds = "|".join(sorted(OSM_STAY_CAT))
    q = ("[out:json][timeout:30];"
         f'nwr["tourism"~"^({kinds})$"]["name"](around:{STAY_RADIUS_KM * 1000},{lat},{lon});'
         "out center;")
    return f"https://overpass-turbo.eu/?Q={urllib.parse.quote(q)}&C={lat};{lon};11&R"


def link_is_dead(url, link_health_cache=None):
    """Per-stay 'Website' buttons point at whatever OSM's website tag says, and
    that drifts — small operators' sites die, move, or get replaced. A dead
    direct link is worse than no link (a 'Booking.com' button that's just a
    search never looks broken; a 'Website' button to a 404 does). So every
    such URL is health-checked and the result cached, re-checked every
    LINK_RECHECK_DAYS so a site that comes back isn't hidden forever.

    Only 404/410 (this exact page is confirmed gone) and a DNS resolution
    failure (the domain itself doesn't exist) count as dead on the first
    check — both are unambiguous regardless of bot protection (Cloudflare/
    Akamai routinely answer non-browser requests with 503, not just
    401/403/429 — the exact same "can't verify, not actually dead" case).
    Everything else that fails (timeouts, connection errors, 5xx) only
    counts after it fails again on a LATER day, so one bad network moment
    can't nuke a fine link."""
    if link_health_cache is None:
        return False
    now = time.time()
    cached = link_health_cache.get(url, {})
    if now - cached.get("t", 0) < LINK_RECHECK_DAYS * 86400:
        return cached.get("dead", False)
    dns_fail = False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        with urllib.request.urlopen(req, timeout=10):
            dead, ambiguous_fail = False, False
    except urllib.error.HTTPError as e:
        dead, ambiguous_fail = e.code in LINK_DEAD_NOW, e.code not in LINK_DEAD_NOW
    except urllib.error.URLError as e:
        dns_fail = isinstance(e.reason, socket.gaierror)
        dead, ambiguous_fail = dns_fail, not dns_fail
    except Exception:
        dead, ambiguous_fail = False, True   # timeout, connection reset, bad SSL, ...
    if ambiguous_fail:
        last_fail_day = cached.get("fail_day")
        today = int(now // LINK_DEAD_DAY)
        # only escalate to dead once the SAME url has failed on two DIFFERENT
        # days — a single flaky run (ours or the site's) never removes a link
        dead = bool(last_fail_day is not None and last_fail_day != today)
        link_health_cache.set(url, {"dead": dead, "t": now,
                                     "fail_day": last_fail_day if dead else today})
    else:
        link_health_cache.set(url, {"dead": dead, "t": now})
    return dead


def overpass_stays(lat, lon, cache=None):
    """Named lodging within STAY_RADIUS_KM of the venue from Overpass, nearest
    first. One request per venue, then served from the committed disk cache.
    The public endpoints load-shed under bursts, so: gentle pacing between
    uncached fetches + a mirror fallback."""
    ck = f"{lat},{lon}|r{STAY_RADIUS_KM}|v1"
    cached = cache.get(ck) if cache else None
    if cached is not None:
        return cached
    kinds = "|".join(sorted(OSM_STAY_CAT))
    q = ("[out:json][timeout:30];"
         f'nwr["tourism"~"^({kinds})$"]["name"](around:{STAY_RADIUS_KM * 1000},{lat},{lon});'
         "out center 80;")
    d, last = None, None
    for host in OVERPASS_HOSTS:
        try:
            d = get_json(host + "?data=" + urllib.parse.quote(q), retries=2)
            break
        except Exception as e:
            last = e
    if d is None:
        raise RuntimeError(f"all Overpass mirrors failed: {redact(last)}")
    time.sleep(1)   # politeness between uncached venue queries
    out = []
    for el in d.get("elements", []):
        t = el.get("tags", {})
        kind, name = t.get("tourism"), (t.get("name") or "").strip()
        la = el.get("lat") or (el.get("center") or {}).get("lat")
        lo = el.get("lon") or (el.get("center") or {}).get("lon")
        if kind not in OSM_STAY_CAT or not name or la is None or lo is None:
            continue
        out.append({"name": name, "kind": kind,
                    "dist": round(haversine_km(lat, lon, la, lo), 1),
                    "web": t.get("website") or t.get("contact:website") or ""})
    out.sort(key=lambda s: s["dist"])
    if cache:
        cache.set(ck, out)
    return out


def stay_options(v, ctx, stays_cache=None, link_health_cache=None):
    """Grouped stays payload for one venue. Overpass failing degrades to the
    date-filled search links only (empty list) — it never fails the build."""
    out_date, back_date = ctx.rep_combo["out"], ctx.rep_combo["back"]
    area = f"{short_name(v['name'])}, {v['country']}"
    try:
        raw = overpass_stays(v["lat"], v["lon"], stays_cache)
    except Exception as e:
        print(f"[warn] stays lookup failed for {v['name']}: {redact(e)}", file=sys.stderr)
        raw = []
    picks, seen = [], set()
    for cat in ("house", "camp", "hotel"):     # houses first: Michel's preference order
        n = 0
        for s in raw:
            if OSM_STAY_CAT[s["kind"]] != cat or s["name"].lower() in seen:
                continue                        # skip other cats + node/way duplicates
            if n >= STAY_PER_CAT:
                break
            seen.add(s["name"].lower())
            n += 1
            web = s["web"] if s["web"].startswith("https://") else ""
            if web and link_is_dead(web, link_health_cache):
                web = ""
            # engines that actually list this category: houses on Airbnb,
            # hotels/hostels/huts on Booking.com + Hotels.com — a specific
            # campsite name rarely resolves on any of the three, so camp
            # keeps just its (verified) own website + map.
            q = f"{s['name']}, {area}"
            picks.append({
                "name": s["name"], "cat": cat, "type": STAY_TYPE_LBL[s["kind"]],
                "dist": s["dist"], "est": STAY_EST_NIGHT[s["kind"]],
                "note": CAMP_NOTE if cat == "camp" else "",
                "web": web,
                "airbnb": _airbnb_url(q, out_date, back_date) if cat == "house" and s["kind"] not in NO_OTA_KINDS else "",
                "book": _booking_url(q, out_date, back_date) if cat in ("house", "hotel") and s["kind"] not in NO_OTA_KINDS else "",
                "hotels": _hotels_url(q, out_date, back_date) if cat == "hotel" and s["kind"] not in NO_OTA_KINDS else "",
                "maps": ("https://www.google.com/maps/search/?api=1&query="
                         + urllib.parse.quote(f"{s['name']} {area}")),
            })
    cheapest = min(picks, key=lambda p: p["est"]) if picks else None
    return {
        "list": picks, "radius": STAY_RADIUS_KM, "adults": STAY_ADULTS,
        "cheapest": ({"est": cheapest["est"], "type": cheapest["type"]} if cheapest else None),
        "search": {"airbnb": _airbnb_url(area, out_date, back_date),
                   "booking": _booking_url(area, out_date, back_date),
                   "hotels": _hotels_url(area, out_date, back_date),
                   "camps": ("https://www.google.com/maps/search/?api=1&query="
                             + urllib.parse.quote(f"campsite near {area}")),
                   "map": _turbo_url(v["lat"], v["lon"])},
    }

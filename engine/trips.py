"""trips.json loader — the trip registry (decision #33, milestone M1).

`trips.json` at the repo root is the single list of trips the pipeline knows
about, and the schema is deliberately the future API contract (decision #33:
files + JSON for now, DB + API later — rows here become table rows then).

Date semantics — two distinct concepts, kept apart on purpose:
  * `start`/`end` here = the candidate climbing window (what venues.json's
    `target_window` used to be): drives weather scoring, graph window, period
    label. trips.json WINS over a trip dir's venues.json `target_window`;
    the latter is legacy and ignored once the trip is registered here.
  * The *representative flight dates* shown in the header pills still come
    from the trip dir's flights.json `combos` (rep_combo = most nights).

`travellers` is carried and validated here from M1 but only consumed from M2
(traveller generalisation) — until then the pipeline still keys off
flights.json's traveller_origins/traveller_coords.

Validation raises ValueError with pointed, human messages: the local admin
server (M5) surfaces these verbatim as form errors.
"""
import json
import re
from datetime import date

from .models import TripContext

SCHEMA_VERSION = 1
STATUSES = ("live", "draft", "ended")
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _err(slug, msg):
    where = f"trip '{slug}'" if slug else "trips.json"
    raise ValueError(f"{where}: {msg}")


def _parse_date(slug, field, value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        _err(slug, f"'{field}' must be an ISO date (YYYY-MM-DD), got {value!r}")


def validate_trip(trip):
    """Validate one trip entry; returns it unchanged. Raises ValueError."""
    slug = trip.get("slug")
    if not slug or not _SLUG_RE.match(slug):
        _err(None, f"every trip needs a kebab-case 'slug', got {slug!r}")
    if not (trip.get("name") or "").strip():
        _err(slug, "'name' is required")
    if trip.get("status") not in STATUSES:
        _err(slug, f"'status' must be one of {'/'.join(STATUSES)}, got {trip.get('status')!r}")
    start = _parse_date(slug, "start", trip.get("start"))
    end = _parse_date(slug, "end", trip.get("end"))
    if end < start:
        _err(slug, f"'end' ({end}) is before 'start' ({start})")
    travellers = trip.get("travellers")
    if not isinstance(travellers, list) or not travellers:
        _err(slug, "'travellers' must be a non-empty list")
    seen = set()
    for t in travellers:
        key = t.get("key")
        if not key or not _SLUG_RE.match(key):
            _err(slug, f"traveller needs a kebab-case 'key', got {key!r}")
        if key in seen:
            _err(slug, f"duplicate traveller key '{key}'")
        seen.add(key)
        if not (t.get("name") or "").strip():
            _err(slug, f"traveller '{key}' needs a 'name'")
        homes = t.get("homes")
        if not isinstance(homes, list) or not homes:
            _err(slug, f"traveller '{key}' needs at least one home (city + lat/lon)")
        for h in homes:
            if not isinstance(h.get("lat"), (int, float)) or not isinstance(h.get("lon"), (int, float)):
                _err(slug, f"traveller '{key}' home {h.get('city')!r} needs numeric lat/lon")
        airports = t.get("airports")
        if not isinstance(airports, list) or not all(isinstance(a, str) and a for a in airports):
            _err(slug, f"traveller '{key}' needs 'airports' as a list of IATA codes "
                       "(may be empty only for a driving-only traveller)")
    if not isinstance(trip.get("sheet_merge", False), bool):
        _err(slug, "'sheet_merge' must be a boolean (merge the Google-Sheet venue list "
                   "into this trip — only meaningful for the trip the sheet curates)")
    flex = trip.get("flex_days", 0)
    if not isinstance(flex, int) or not 0 <= flex <= 3:
        _err(slug, f"'flex_days' must be an integer 0–3 (± days around the trip "
                   f"for flight/stay alternatives), got {flex!r}")
    return trip


def load_trips(repo_root):
    """Parse + validate repo_root/trips.json; returns the list of trip dicts."""
    path = repo_root / "trips.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        _err(None, f"not found at {path}")
    except ValueError as e:
        _err(None, f"invalid JSON: {e}")
    if data.get("schema") != SCHEMA_VERSION:
        _err(None, f"unsupported schema {data.get('schema')!r} (this code reads {SCHEMA_VERSION})")
    trips = data.get("trips")
    if not isinstance(trips, list) or not trips:
        _err(None, "'trips' must be a non-empty list")
    slugs = [t.get("slug") for t in trips]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        _err(None, f"duplicate slugs: {sorted(dupes)}")
    return [validate_trip(t) for t in trips]


def trip_dir(repo_root, trip):
    """The trip's data directory (venues.json, flights.json, caches, history).
    Legacy trips carry an explicit 'dir'; new trips default to trips/<slug>/."""
    return repo_root / trip.get("dir", f"trips/{trip['slug']}")


def get_trip(repo_root, slug):
    for t in load_trips(repo_root):
        if t["slug"] == slug:
            return t
    _err(None, f"no trip with slug '{slug}'")


def trip_for_dir(repo_root, directory):
    """Self-identification for per-trip drivers: the registered trip whose data
    dir is `directory` — so the NI driver never hardcodes its own slug twice."""
    directory = directory.resolve()
    for t in load_trips(repo_root):
        if trip_dir(repo_root, t).resolve() == directory:
            return t
    _err(None, f"no trip registered for directory {directory}")


def context_for(trip, venues, flights_cfg, serpapi_key=None, top_n_flights=4):
    """TripContext from a registry entry. trips.json is the source of truth for
    the trip's name and climbing window; `venues` is the (possibly sheet-merged)
    venue list the caller loaded from the trip dir."""
    return TripContext(
        trip_name=trip.get("title") or trip["name"],
        target_start=date.fromisoformat(trip["start"]),
        target_end=date.fromisoformat(trip["end"]),
        venues=venues,
        flights_cfg=flights_cfg,
        serpapi_key=serpapi_key,
        top_n_flights=top_n_flights,
        travellers=trip["travellers"],
        flex_days=trip.get("flex_days", 0),
    )

"""Trip admin — the localhost forms behind trips.json (decision #33 M5).

Serves the three approved screens (trips list / new trip / manage trip) and
reads/writes the repo-root trips.json registry through engine.trips'
validation, so a bad edit is rejected with the same human message the
pipeline would give. Binds to localhost — this is an admin tool, not a
public site; nothing here deploys.

Run:  agent/.venv/bin/uvicorn server:app --port 8764      (from admin/)
Then open http://127.0.0.1:8764

What it writes:
- trips.json (always) — the registry the daily pipeline reads.
- trips/<slug>/venues.json + flights.json (on create) — scaffolded from the
  venue catalogue and the trip's travellers/dates. New trips render once the
  M3 MULTI_TRIP flag is on; the registry entry is valid either way.
- <trip dir>/flights.json combos (on date change) — the representative
  flight dates follow the trip window, so the header pills and pricing move
  with your edit.

Deleting a trip removes the registry entry only; the trip's directory (its
history) stays on disk. Nothing is git-committed automatically — review with
`git diff` and commit when happy.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import sheet_venues, trips as trips_mod  # noqa: E402

app = FastAPI(title="climbing trip admin — localhost only")
STATIC = Path(__file__).resolve().parent / "static"
TRIPS_F = ROOT / "trips.json"

# Airport suggestions for the cities that actually come up; anything else the
# form asks you to type IATA codes yourself (deriving nearest airports
# properly needs an airport dataset — deliberately out of scope, see plan).
CITY_AIRPORTS = {
    "london": ["LGW", "LHR", "LTN", "STN", "LCY"],
    "belfast": ["BFS", "BHD"],
    "dublin": ["DUB"],
    "manchester": ["MAN"],
    "birmingham": ["BHX"],
    "bristol": ["BRS"],
    "edinburgh": ["EDI"],
    "glasgow": ["GLA"],
    "leeds": ["LBA"],
    "newcastle upon tyne": ["NCL"],
    "sheffield": ["MAN", "LBA"],
}


def _read_registry() -> dict:
    return json.loads(TRIPS_F.read_text())


def _write_registry(data: dict) -> None:
    for t in data["trips"]:
        trips_mod.validate_trip(t)
    slugs = [t["slug"] for t in data["trips"]]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate slugs")
    TRIPS_F.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _catalogue() -> list[dict]:
    """Every venue dict we know about — each trip dir's venues.json merged
    with the curated Google-Sheet rows, exactly the list the pipeline ranks
    (42 areas today, not just the 13 hand-written NI entries). First
    occurrence of a name wins."""
    seen, out = set(), []
    csv = ROOT / "climbing-trips.csv"
    for t in _read_registry()["trips"]:
        vf = trips_mod.trip_dir(ROOT, t) / "venues.json"
        if not vf.exists():
            continue
        base = json.loads(vf.read_text()).get("venues", [])
        merged = sheet_venues.build_venues(base, csv) if csv.exists() else base
        for v in merged:
            if v["name"] not in seen:
                seen.add(v["name"])
                out.append(v)
    return out


def _resolve_picks(slug: str, names: list[str]) -> list[dict]:
    """Catalogue dicts for the picked names — unknown names and an empty pick
    list are errors, so a typo can't silently produce a venue-less trip."""
    if not names:
        raise ValueError(f"trip '{slug}': pick at least one area")
    cat = {v["name"]: v for v in _catalogue()}
    missing = [n for n in names if n not in cat]
    if missing:
        raise ValueError(f"trip '{slug}': unknown areas {missing}")
    return [cat[n] for n in names]


def _scaffold_trip_dir(trip: dict, venues: list[dict]) -> None:
    d = trips_mod.trip_dir(ROOT, trip)
    d.mkdir(parents=True, exist_ok=True)
    (d / "venues.json").write_text(json.dumps({
        "trip": trip.get("title") or trip["name"],
        "target_window": {"start": trip["start"], "end": trip["end"],
                          "_comment": "LEGACY — trips.json is the authority (decision #33)."},
        "notes": "Scaffolded by admin/server.py; venues copied from the catalogue.",
        "venues": venues,
    }, ensure_ascii=False, indent=2) + "\n")
    _write_flights_cfg(d, trip)


def _write_flights_cfg(d: Path, trip: dict) -> None:
    """flights.json for a trip: route from the travellers, one representative
    combo spanning the trip window (the pipeline's rep_combo)."""
    from datetime import date
    nights = (date.fromisoformat(trip["end"]) - date.fromisoformat(trip["start"])).days
    f = d / "flights.json"
    cfg = json.loads(f.read_text()) if f.exists() else {}
    route = cfg.setdefault("route", {})
    route["passengers"] = route.get("passengers", 1)
    route["traveller_origins"] = {t["key"]: t["airports"] for t in trip["travellers"]}
    route["traveller_coords"] = {t["key"]: [[h["lat"], h["lon"]] for h in t["homes"]]
                                  for t in trip["travellers"]}
    cfg["combos"] = [{"out": trip["start"], "back": trip["end"], "nights": nights}]
    f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


class TripIn(BaseModel):
    trip: dict
    venues: list[str] = []          # names, used on create to scaffold venues.json


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/trips")
def list_trips():
    data = _read_registry()
    csv = ROOT / "climbing-trips.csv"
    for t in data["trips"]:
        d = trips_mod.trip_dir(ROOT, t)
        vf = d / "venues.json"
        if vf.exists():
            base = json.loads(vf.read_text()).get("venues", [])
            # sheet-curated trips (NI) rank the merged list; scaffolded trips
            # rank exactly their own venues.json (engine/driver.trip_context)
            merged = (sheet_venues.build_venues(base, csv)
                      if t.get("sheet_merge") and csv.exists() else base)
            t["_venueNames"] = [v["name"] for v in merged]
        else:
            t["_venueNames"] = []
        t["_dirExists"] = d.exists()
        t["_flexLine"] = _flex_line(d)
    return data


def _flex_line(d: Path) -> str | None:
    """Human line for the trip's latest ±day finding, from flights-latest.json
    — what the dashboard's green pill says, for the Manage screen."""
    try:
        f = json.loads((d / "flights-latest.json").read_text())
    except Exception:
        return None
    fx = f.get("flex") or {}
    trav, venue = fx.get("travellers") or {}, fx.get("venue")
    base_all = (f.get("venues") or {}).get(venue) or {}
    bits = []
    for who, alts in trav.items():
        priced = [a for a in alts if a.get("price") is not None]
        opts = (base_all.get(who) or {}).get("options") or []
        base = opts[0].get("price") if opts else None
        if priced and base is not None:
            best = min(priced, key=lambda a: a["price"])
            if best["price"] < base:
                d_ = best["shift"]
                lbl = f"{-d_}d earlier" if d_ < 0 else f"{d_}d later"
                bits.append(f"{who.title()} {lbl}: £{best['price']} (save £{base - best['price']})")
    return f"{venue} — " + "; ".join(bits) if bits else None


@app.get("/api/venues")
def venue_catalogue():
    return [{"name": v["name"], "country": v.get("country", "")} for v in _catalogue()]


@app.get("/api/geocode")
def geocode(q: str):
    """Open-Meteo geocoding proxy (free, no key): city text -> candidates."""
    url = ("https://geocoding-api.open-meteo.com/v1/search?count=5&language=en&format=json&name="
           + urllib.parse.quote(q.strip()))
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            res = json.loads(r.read()).get("results") or []
    except Exception:
        res = []          # offline / provider down → "no match", not a 500
    return [{"city": x["name"], "country": x.get("country", ""),
             "lat": round(x["latitude"], 4), "lon": round(x["longitude"], 4),
             "airports": CITY_AIRPORTS.get(x["name"].lower(), [])} for x in res]


@app.post("/api/trips")
def create_trip(body: TripIn):
    data = _read_registry()
    trip = body.trip
    if any(t["slug"] == trip.get("slug") for t in data["trips"]):
        raise HTTPException(400, f"a trip with slug '{trip.get('slug')}' already exists")
    try:
        trips_mod.validate_trip(trip)
        venues = _resolve_picks(trip["slug"], body.venues)   # reject typos BEFORE any write
        data["trips"].append(trip)
        _write_registry(data)
        _scaffold_trip_dir(trip, venues)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "slug": trip["slug"]}


@app.put("/api/trips/{slug}")
def update_trip(slug: str, body: TripIn):
    data = _read_registry()
    idx = next((i for i, t in enumerate(data["trips"]) if t["slug"] == slug), None)
    if idx is None:
        raise HTTPException(404, f"no trip '{slug}'")
    old, new = data["trips"][idx], body.trip
    new["slug"] = slug                                   # slug is the identity; not editable
    new["dir"] = old.get("dir", f"trips/{slug}")
    for k in ("title", "sheet_merge"):                   # server-owned; a client that
        if k in old and k not in new:                    # doesn't echo them must not
            new[k] = old[k]                              # silently strip them
    try:
        trips_mod.validate_trip(new)
        data["trips"][idx] = new
        _write_registry(data)
        d = trips_mod.trip_dir(ROOT, new)
        if d.exists() and (old["start"], old["end"], old["travellers"]) != \
                          (new["start"], new["end"], new["travellers"]):
            _write_flights_cfg(d, new)                   # rep dates follow the window
        if body.venues is not None and body.venues != []:
            _apply_venue_picks(new, body.venues)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


def _apply_venue_picks(trip: dict, names: list[str]) -> None:
    """Rewrite the trip's venues.json venue list from catalogue picks.
    Sheet-curated trips are refused — their list belongs to the spreadsheet."""
    if trip.get("sheet_merge"):
        raise ValueError(f"trip '{trip['slug']}': its venue list is curated by the "
                         "Google Sheet — edit the spreadsheet, not the picker")
    d = trips_mod.trip_dir(ROOT, trip)
    vf = d / "venues.json"
    if not vf.exists():
        raise ValueError(f"trip '{trip['slug']}': no venues.json to update")
    cfg = json.loads(vf.read_text())
    cfg["venues"] = _resolve_picks(trip["slug"], names)
    vf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


@app.delete("/api/trips/{slug}")
def delete_trip(slug: str):
    data = _read_registry()
    n = len(data["trips"])
    data["trips"] = [t for t in data["trips"] if t["slug"] != slug]
    if len(data["trips"]) == n:
        raise HTTPException(404, f"no trip '{slug}'")
    if not data["trips"]:
        raise HTTPException(400, "refusing to delete the last trip — the registry must stay non-empty")
    _write_registry(data)
    return {"ok": True, "note": "registry entry removed; the trip directory and its history stay on disk"}

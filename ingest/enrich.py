"""Static enrichment — the phase BETWEEN crawl and LLM (Michel's ordering,
2026-08-12): everything here is mechanical, derived from coordinates and
source-stated facts; no LLM anywhere.

    python -m ingest enrich <run-id>

Reads runs/<id>/parsed/<source>.json, writes enriched/<source>.json — the same
crags plus an `enrichment` object each:

    climate      monthly normals from the Open-Meteo ERA5 archive (last 12
                 complete months): mean daily max/min temp, precip days
                 (>=1mm), mean daily max wind. Raw responses kept under raw/.
                 (Open-Meteo verified against BBC/met.no 2026-07-15, ~2-3°C.)
    season       dry_warm_months: months where mean tmax is 8..26°C and
                 precip days <= 12 — a documented mechanical rule of thumb,
                 not judgment; consumers can re-derive from `climate`.
    sun_window   taxonomy code derived from the crag's source-stated aspect
                 (N->shade, E->morning, W->afternoon, S->all-day, quadrant
                 combos to the nearer pure case, "all"->all-day). Null when
                 the source gave no aspect — never guessed from geometry.
    tide         NOT here: there is no free mechanical per-crag tide source;
                 tidal risk arrives in the LLM phase as the taxonomy `tidal`
                 hazard, evidence-quoted from route prose. Recorded as null
                 with this reason, so the gap is visible, not silent.

Coords are rounded to ~2km (0.02 deg) and one climate call serves every crag
in that cell — Fair Head's five crags cost one request, not five.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request

from . import schema
from .runstore import Run, _atomic_write

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# compass -> taxonomy sun_window (coarse, documented; quadrants snap to the
# nearer pure case). Source aspects seen live: N/NE/E/SE/S/SW/W/NW/"all".
SUN_WINDOW_FROM_ASPECT = {
    "N": "shade", "NNE": "shade", "NNW": "shade",
    "NE": "morning", "E": "morning", "ENE": "morning", "ESE": "morning",
    "SE": "all-day", "S": "all-day", "SSE": "all-day", "SSW": "all-day",
    "SW": "afternoon", "W": "afternoon", "WSW": "afternoon", "WNW": "afternoon",
    "NW": "afternoon",
    "ALL": "all-day",
}


def _months_window() -> tuple[str, str]:
    """Last 12 complete calendar months."""
    first_of_this = dt.date.today().replace(day=1)
    end = first_of_this - dt.timedelta(days=1)
    start = (first_of_this - dt.timedelta(days=366)).replace(day=1)
    return start.isoformat(), end.isoformat()


def _fetch_climate(lat: float, lon: float) -> dict:
    start, end = _months_window()
    params = {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "start_date": start, "end_date": end,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "timezone": "auto",
    }
    url = ARCHIVE_URL + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except (TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _monthly(payload: dict) -> dict:
    days = payload["daily"]["time"]
    tmax, tmin = payload["daily"]["temperature_2m_max"], payload["daily"]["temperature_2m_min"]
    prec, wind = payload["daily"]["precipitation_sum"], payload["daily"]["wind_speed_10m_max"]
    buckets: dict[str, dict] = {}
    for i, day in enumerate(days):
        m = day[5:7]
        b = buckets.setdefault(m, {"tmax": [], "tmin": [], "wet": 0, "wind": [], "n": 0})
        b["n"] += 1
        if tmax[i] is not None: b["tmax"].append(tmax[i])
        if tmin[i] is not None: b["tmin"].append(tmin[i])
        if wind[i] is not None: b["wind"].append(wind[i])
        if (prec[i] or 0) >= 1.0: b["wet"] += 1
    out = {}
    for m, b in sorted(buckets.items()):
        out[m] = {
            "tmax_mean_c": round(sum(b["tmax"]) / len(b["tmax"]), 1) if b["tmax"] else None,
            "tmin_mean_c": round(sum(b["tmin"]) / len(b["tmin"]), 1) if b["tmin"] else None,
            "precip_days": b["wet"],
            "wind_max_mean_kmh": round(sum(b["wind"]) / len(b["wind"]), 1) if b["wind"] else None,
        }
    return out


def _dry_warm_months(monthly: dict) -> list[int]:
    """Warm enough (tmax 8..26C) and among the DRIEST of those months (within
    5 wet days of the driest candidate) — relative, because an absolute wet-day
    cutoff that suits Spain declares all of Ireland unclimbable (first version
    did exactly that: <=12 days matched zero Fair Head months)."""
    candidates = {int(m): v["precip_days"] for m, v in monthly.items()
                  if v["tmax_mean_c"] is not None and 8.0 <= v["tmax_mean_c"] <= 26.0}
    if not candidates:
        return []
    driest = min(candidates.values())
    return sorted(m for m, wet in candidates.items() if wet <= driest + 5)


def sun_window(aspect: str | None) -> str | None:
    if not aspect:
        return None
    code = SUN_WINDOW_FROM_ASPECT.get(aspect.strip().upper())
    assert code is None or code in schema.SUN_WINDOWS
    return code


def enrich_run(run_id: str) -> dict:
    run = Run.load(run_id)
    (run.dir / "enriched").mkdir(exist_ok=True)
    cells: dict[tuple, dict] = {}   # rounded coord cell -> climate payload
    summary = {}
    start, end = _months_window()
    for f in sorted((run.dir / "parsed").glob("*.json")):
        inv = json.loads(f.read_text())
        if inv.get("kind") == "chatter":
            continue
        n_ok = 0
        for c in inv.get("crags") or []:
            enr = {"sun_window": sun_window(c.get("aspect")),
                   "sun_window_derived_from": f"aspect:{c['aspect']}" if c.get("aspect") else None,
                   "climate": None, "season": None,
                   "tide": None,
                   "tide_note": "no free mechanical per-crag tide source; tidal risk comes from the LLM phase as an evidence-quoted 'tidal' hazard"}
            if c.get("lat") is not None and c.get("lon") is not None:
                cell = (round(c["lat"] / 0.02) * 0.02, round(c["lon"] / 0.02) * 0.02)
                if cell not in cells:
                    payload = _fetch_climate(cell[0], cell[1])
                    cells[cell] = payload
                    run.save_raw("enrich-openmeteo", {"kind": "climate", "id": f"{cell[0]:.2f},{cell[1]:.2f}"}, payload)
                    run.log(f"enrich: climate cell {cell[0]:.2f},{cell[1]:.2f} fetched")
                    time.sleep(0.5)
                monthly = _monthly(cells[cell])
                enr["climate"] = {"source": "open-meteo-era5-archive",
                                  "period": [start, end], "monthly": monthly}
                enr["season"] = {"dry_warm_months": _dry_warm_months(monthly),
                                 "rule": "tmax_mean 8..26C, precip_days within 5 of the driest such month"}
                n_ok += 1
            c["enrichment"] = enr
        inv["enriched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        _atomic_write(run.dir / "enriched" / f.name, inv)
        summary[f.stem] = {"crags": len(inv.get("crags") or []), "with_climate": n_ok}
        run.log(f"enrich: {f.name} -> {n_ok}/{len(inv.get('crags') or [])} crags with climate "
                f"({len(cells)} climate cell(s) fetched so far)")
    return summary

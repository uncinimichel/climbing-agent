"""Unit tests for engine.trips — the trips.json registry (decision #33 M1).

The zero-drift test is the important one: the NI trip's TripContext built via
the registry must equal what update_report.py used to build directly from
venues.json's `target_window` — proving M1 changed plumbing, not behavior.
"""
import copy
import json
from datetime import date
from pathlib import Path

import pytest

from engine import trips

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

VALID = {
    "slug": "test-trip",
    "name": "Test",
    "status": "draft",
    "start": "2026-09-05",
    "end": "2026-09-12",
    "travellers": [
        {"key": "michel", "name": "Michel",
         "homes": [{"city": "London", "lat": 51.5, "lon": -0.13}],
         "airports": ["LGW"]},
    ],
}


def _bad(**overrides):
    t = copy.deepcopy(VALID)
    t.update(overrides)
    return t


def test_valid_trip_passes():
    assert trips.validate_trip(copy.deepcopy(VALID))["slug"] == "test-trip"


@pytest.mark.parametrize("broken, needle", [
    (_bad(slug="Bad Slug!"), "kebab-case"),
    (_bad(name="  "), "'name'"),
    (_bad(status="paused"), "live/draft/ended"),
    (_bad(start="22/07/2026"), "ISO date"),
    (_bad(end="2026-09-01"), "before 'start'"),
    (_bad(travellers=[]), "non-empty list"),
    (_bad(travellers=[{"key": "x", "name": "X", "homes": [], "airports": []}]), "home"),
    (_bad(travellers=[{"key": "x", "name": "X",
                       "homes": [{"city": "Y", "lat": "51", "lon": 0}], "airports": []}]),
     "numeric lat/lon"),
    (_bad(travellers=[VALID["travellers"][0], VALID["travellers"][0]]), "duplicate traveller"),
])
def test_invalid_trips_fail_with_pointed_messages(broken, needle):
    with pytest.raises(ValueError, match=needle):
        trips.validate_trip(broken)


def test_duplicate_slugs_rejected(tmp_path):
    two = {"schema": 1, "trips": [copy.deepcopy(VALID), copy.deepcopy(VALID)]}
    (tmp_path / "trips.json").write_text(json.dumps(two))
    with pytest.raises(ValueError, match="duplicate slugs"):
        trips.load_trips(tmp_path)


def test_unknown_schema_rejected(tmp_path):
    (tmp_path / "trips.json").write_text(json.dumps({"schema": 99, "trips": [VALID]}))
    with pytest.raises(ValueError, match="unsupported schema"):
        trips.load_trips(tmp_path)


def test_repo_registry_is_valid_and_ni_resolves():
    reg = trips.load_trips(REPO_ROOT)
    ni = trips.get_trip(REPO_ROOT, "ni-july-2026")
    assert ni in reg
    d = trips.trip_dir(REPO_ROOT, ni)
    assert d.is_dir() and (d / "venues.json").exists() and (d / "flights.json").exists()
    assert trips.trip_for_dir(REPO_ROOT, d)["slug"] == "ni-july-2026"


def test_default_dir_for_new_trips():
    assert trips.trip_dir(REPO_ROOT, {"slug": "alps-2027"}) == REPO_ROOT / "trips" / "alps-2027"


def test_ni_context_matches_legacy_construction():
    """Zero-drift: registry-built context == the old venues.json-driven one."""
    ni = trips.get_trip(REPO_ROOT, "ni-july-2026")
    d = trips.trip_dir(REPO_ROOT, ni)
    venues_cfg = json.loads((d / "venues.json").read_text())
    flights_cfg = json.loads((d / "flights.json").read_text())
    ctx = trips.context_for(ni, venues_cfg["venues"], flights_cfg, top_n_flights=10)

    assert ctx.trip_name == venues_cfg["trip"]
    assert ctx.target_start == date.fromisoformat(venues_cfg["target_window"]["start"])
    assert ctx.target_end == date.fromisoformat(venues_cfg["target_window"]["end"])
    # derived values the render layer actually consumes
    assert ctx.period_lbl and ctx.trip_days == (ctx.target_end - ctx.target_start).days + 1
    assert ctx.rep_out_lbl and ctx.rep_back_lbl

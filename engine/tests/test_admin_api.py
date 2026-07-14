"""API tests for admin/server.py (decision #33 M5) — run against a temp copy
of the registry + a scratch trip dir, never the real trips.json.

Needs fastapi/httpx (the shared agent/.venv):
    agent/.venv/bin/python -m pytest engine/tests/test_admin_api.py
Plain python3 runs skip cleanly, so CI without fastapi stays green.
"""
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "admin"))
server = importlib.import_module("server")

NI = json.loads((REPO_ROOT / "trips.json").read_text())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Server pointed at a scratch repo: real NI registry copied in, plus the
    NI trip dir's venues/flights configs (no caches, no history)."""
    (tmp_path / "trips.json").write_text(json.dumps(NI, indent=2))
    ni_dir = tmp_path / "trip-ni-july-2026"
    ni_dir.mkdir()
    for f in ("venues.json", "flights.json"):
        shutil.copy(REPO_ROOT / "trip-ni-july-2026" / f, ni_dir / f)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "TRIPS_F", tmp_path / "trips.json")
    return TestClient(server.app)


def _draft(slug="test-alps"):
    return {"trip": {
        "slug": slug, "name": "Test Alps", "status": "draft",
        "start": "2026-09-05", "end": "2026-09-12", "flex_days": 1,
        "travellers": [{"key": "michel", "name": "Michel",
                        "homes": [{"city": "London", "lat": 51.5, "lon": -0.13}],
                        "airports": ["LGW"]}]},
        "venues": ["Fair Head, NI"]}


def test_list_includes_ni_with_extras(client):
    d = client.get("/api/trips").json()
    ni = d["trips"][0]
    assert ni["slug"] == "ni-july-2026" and ni["_dirExists"]
    assert len(ni["_venueNames"]) >= 13


def test_catalogue_is_sheet_merged(client):
    names = [v["name"] for v in client.get("/api/venues").json()]
    assert "Fair Head, NI" in names
    assert len(names) >= 13          # sheet merge only when climbing-trips.csv present


def test_create_scaffolds_dir_and_registry(client, tmp_path):
    r = client.post("/api/trips", json=_draft())
    assert r.status_code == 200, r.text
    reg = json.loads((tmp_path / "trips.json").read_text())
    assert [t["slug"] for t in reg["trips"]] == ["ni-july-2026", "test-alps"]
    v = json.loads((tmp_path / "trips" / "test-alps" / "venues.json").read_text())
    assert [x["name"] for x in v["venues"]] == ["Fair Head, NI"]
    f = json.loads((tmp_path / "trips" / "test-alps" / "flights.json").read_text())
    assert f["combos"] == [{"out": "2026-09-05", "back": "2026-09-12", "nights": 7}]
    assert f["route"]["traveller_origins"] == {"michel": ["LGW"]}


def test_create_duplicate_slug_rejected(client):
    assert client.post("/api/trips", json=_draft()).status_code == 200
    r = client.post("/api/trips", json=_draft())
    assert r.status_code == 400 and "already exists" in r.json()["detail"]


def test_update_dates_rewrites_combos(client, tmp_path):
    client.post("/api/trips", json=_draft())
    body = _draft()
    body["trip"].update(start="2026-09-06", end="2026-09-13", status="live")
    r = client.put("/api/trips/test-alps", json=body)
    assert r.status_code == 200, r.text
    f = json.loads((tmp_path / "trips" / "test-alps" / "flights.json").read_text())
    assert f["combos"][0]["out"] == "2026-09-06"
    reg = json.loads((tmp_path / "trips.json").read_text())
    assert reg["trips"][1]["status"] == "live"


def test_update_invalid_is_rejected_and_registry_untouched(client, tmp_path):
    bad = _draft()
    bad["trip"]["status"] = "paused"
    r = client.put("/api/trips/ni-july-2026", json=bad)
    assert r.status_code == 400 and "live/draft/ended" in r.json()["detail"]
    reg = json.loads((tmp_path / "trips.json").read_text())
    assert reg["trips"][0]["status"] == "live"      # unchanged


def test_delete_keeps_dir_and_refuses_last_trip(client, tmp_path):
    client.post("/api/trips", json=_draft())
    assert client.delete("/api/trips/test-alps").status_code == 200
    assert (tmp_path / "trips" / "test-alps").exists()          # history stays
    r = client.delete("/api/trips/ni-july-2026")
    assert r.status_code == 400 and "last trip" in r.json()["detail"]


def test_slug_and_dir_are_not_editable_via_put(client, tmp_path):
    body = _draft("ni-july-2026")
    body["venues"] = []                      # NI is sheet-curated; no picks
    body["trip"]["slug"] = "sneaky-rename"
    body["trip"]["dir"] = "somewhere-else"
    assert client.put("/api/trips/ni-july-2026", json=body).status_code == 200
    reg = json.loads((tmp_path / "trips.json").read_text())
    assert reg["trips"][0]["slug"] == "ni-july-2026"
    assert reg["trips"][0]["dir"] == "trip-ni-july-2026"


def test_put_venue_picks_update_scaffolded_trip(client, tmp_path):
    client.post("/api/trips", json=_draft())
    body = _draft()
    body["venues"] = ["Fair Head, NI", "Mournes, NI"]
    r = client.put("/api/trips/test-alps", json=body)
    assert r.status_code == 200, r.text
    v = json.loads((tmp_path / "trips" / "test-alps" / "venues.json").read_text())
    assert [x["name"] for x in v["venues"]] == ["Fair Head, NI", "Mournes, NI"]


def test_put_venue_picks_refused_for_sheet_trip(client):
    ni = client.get("/api/trips").json()["trips"][0]
    body = {"trip": {k: v for k, v in ni.items() if not k.startswith("_")},
            "venues": ["Fair Head, NI"]}
    r = client.put("/api/trips/ni-july-2026", json=body)
    assert r.status_code == 400 and "curated by the" in r.json()["detail"]


def test_put_unknown_area_rejected(client):
    client.post("/api/trips", json=_draft())
    body = _draft()
    body["venues"] = ["Atlantis Sea Cliffs"]
    r = client.put("/api/trips/test-alps", json=body)
    assert r.status_code == 400 and "unknown areas" in r.json()["detail"]


def test_listing_venue_counts_respect_sheet_merge(client):
    client.post("/api/trips", json=_draft())
    trips_ = client.get("/api/trips").json()["trips"]
    by = {t["slug"]: t for t in trips_}
    assert len(by["ni-july-2026"]["_venueNames"]) >= 13     # merged when csv present
    assert by["test-alps"]["_venueNames"] == ["Fair Head, NI"]   # exactly its own list


def test_put_preserves_title_and_sheet_merge(client, tmp_path):
    """A client that doesn't echo server-owned fields must not strip them —
    losing sheet_merge would silently shrink NI from 42 ranked areas to 13."""
    body = _draft("ni-july-2026")
    body["venues"] = []                      # NI is sheet-curated; no picks
    body["trip"]["status"] = "live"          # minimal client payload, no title/sheet_merge
    assert client.put("/api/trips/ni-july-2026", json=body).status_code == 200
    ni = json.loads((tmp_path / "trips.json").read_text())["trips"][0]
    assert ni.get("sheet_merge") is True
    assert ni.get("title", "").startswith("Climbing trip")


def test_create_rejects_unknown_or_empty_picks(client, tmp_path):
    bad = _draft("typo-trip")
    bad["venues"] = ["Atlantis Sea Cliffs"]
    r = client.post("/api/trips", json=bad)
    assert r.status_code == 400 and "unknown areas" in r.json()["detail"]
    empty = _draft("empty-trip")
    empty["venues"] = []
    r = client.post("/api/trips", json=empty)
    assert r.status_code == 400 and "at least one area" in r.json()["detail"]
    # neither half-written trip may linger in the registry
    reg = json.loads((tmp_path / "trips.json").read_text())
    assert [t["slug"] for t in reg["trips"]] == ["ni-july-2026"]


def test_flex_line_surfaces_saving(client, tmp_path):
    (tmp_path / "trip-ni-july-2026" / "flights-latest.json").write_text(json.dumps({
        "venues": {"Gredos": {"michel": {"options": [{"price": 148}]}}},
        "flex": {"venue": "Gredos",
                 "travellers": {"michel": [{"shift": -1, "price": 101}]}}}))
    ni = client.get("/api/trips").json()["trips"][0]
    assert ni["_flexLine"] == "Gredos — Michel 1d earlier: £101 (save £47)"

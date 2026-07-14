"""End-to-end test for MULTI_TRIP=1 (#33 M3 stage 3): a scratch second trip
is added to the real registry, the real entrypoint runs once, and both
dashboards must come out right — NI still owns the site root, the scratch
trip renders to trips/<slug>/, keyless. The registry and scratch dir are
restored/removed afterwards no matter what.

The scratch trip reuses two NI venues and the NI dates so every weather
lookup hits the shared repo-root cache/ — the test proves the sharing layer
(no fresh fetches for a brand-new trip) as well as the loop.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPDATE_REPORT = REPO_ROOT / "trip-ni-july-2026" / "scripts" / "update_report.py"
TRIPS_F = REPO_ROOT / "trips.json"
SCRATCH = REPO_ROOT / "trips" / "test-mt"

SCRATCH_TRIP = {
    "slug": "test-mt", "name": "Test MT", "status": "live",
    "start": "2026-07-24", "end": "2026-07-28", "flex_days": 0,
    "travellers": [{"key": "rob", "name": "Rob",
                    "homes": [{"city": "Sheffield", "lat": 53.383, "lon": -1.4659}],
                    "airports": ["MAN"]}],
}


def _window_data(html):
    m = re.search(r"window\.DATA=(\{.*?\});window\.TAGT", html, re.S)
    assert m, "no window.DATA blob"
    return json.loads(m.group(1))


def test_multi_trip_renders_both_dashboards():
    registry_before = TRIPS_F.read_text()
    ni_venues = json.loads((REPO_ROOT / "trip-ni-july-2026" / "venues.json").read_text())["venues"]
    picks = [v for v in ni_venues if v["name"] in ("Fair Head, NI", "Mournes, NI")] or ni_venues[:2]
    try:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        (SCRATCH / "venues.json").write_text(json.dumps(
            {"trip": "Test MT", "venues": picks}, indent=2))
        (SCRATCH / "flights.json").write_text(json.dumps({
            "route": {"passengers": 1, "traveller_origins": {"rob": ["MAN"]},
                      "traveller_coords": {"rob": [[53.383, -1.4659]]}},
            "combos": [{"out": "2026-07-24", "back": "2026-07-28", "nights": 4}]}, indent=2))
        reg = json.loads(registry_before)
        reg["trips"].append(SCRATCH_TRIP)
        TRIPS_F.write_text(json.dumps(reg, indent=2))

        result = subprocess.run(
            [sys.executable, str(UPDATE_REPORT)], cwd=REPO_ROOT,
            env={**os.environ, "SERPAPI_KEY": "", "MULTI_TRIP": "1"},
            capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "[ni-july-2026] wrote index.html" in result.stdout
        assert "[test-mt] wrote trips/test-mt/index.html" in result.stdout

        # site root still belongs to NI, untouched shape
        root = _window_data((REPO_ROOT / "index.html").read_text())
        assert len(root["venues"]) > 30
        assert root["trip"]["pills"][0] == "✈ Michel · London"

        # the scratch trip got its own full dashboard, keyless, its own traveller
        mt = _window_data((SCRATCH / "index.html").read_text())
        assert len(mt["venues"]) == len(picks)
        assert mt["trip"]["pills"][0] == "✈ Rob · Sheffield"
        assert mt["trip"]["travellers"] == [{"key": "rob", "name": "Rob", "from": "Sheffield"}]
        fl = json.loads((SCRATCH / "flights-latest.json").read_text())
        assert "no key" in fl["checked_at"]           # secondary trips never spend quota
        assert (SCRATCH / "daily-report.md").exists()
        # no per-venue pages / sitemap for secondary trips (M4 decides their shape)
        assert not (SCRATCH / "venues").exists()
    finally:
        TRIPS_F.write_text(registry_before)
        shutil.rmtree(SCRATCH, ignore_errors=True)
        if SCRATCH.parent.exists() and not any(SCRATCH.parent.iterdir()):
            SCRATCH.parent.rmdir()


if __name__ == "__main__":
    test_multi_trip_renders_both_dashboards()
    print("OK")

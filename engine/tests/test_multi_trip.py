"""End-to-end test for the flagless multi-trip pipeline (#33 M3/M4).

The registry is temporarily set to two trips — NI (ended) + a scratch live
trip — the real entrypoint runs once, and everything must come out right:
each trip renders to trips/<slug>/index.html (NI no longer owns the root), the
repo root becomes the trip picker linking to both, and the scratch trip is
keyless. The registry and scratch dir are restored/removed afterwards.

The scratch trip reuses two NI venues and the NI dates so every weather lookup
hits the shared repo-root cache/ — proving the sharing layer as well as the loop.
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
NI_OUT = REPO_ROOT / "trips" / "ni-july-2026"

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


def test_multi_trip_renders_picker_and_dashboards():
    registry_before = TRIPS_F.read_text()
    root_before = (REPO_ROOT / "index.html").read_text()
    ni_venues = json.loads((REPO_ROOT / "trip-ni-july-2026" / "venues.json").read_text())["venues"]
    picks = [v for v in ni_venues if v["name"] in ("Fair Head, NI", "Mournes, NI")] or ni_venues[:2]
    ni = json.loads(registry_before)
    ni_entry = {**next(t for t in ni["trips"] if t["slug"] == "ni-july-2026"), "status": "ended"}
    try:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        (SCRATCH / "venues.json").write_text(json.dumps(
            {"trip": "Test MT", "venues": picks}, indent=2))
        (SCRATCH / "flights.json").write_text(json.dumps({
            "route": {"passengers": 1, "traveller_origins": {"rob": ["MAN"]},
                      "traveller_coords": {"rob": [[53.383, -1.4659]]}},
            "combos": [{"out": "2026-07-24", "back": "2026-07-28", "nights": 4}]}, indent=2))
        TRIPS_F.write_text(json.dumps({"schema": 1, "trips": [ni_entry, SCRATCH_TRIP]}, indent=2))

        result = subprocess.run(
            [sys.executable, str(UPDATE_REPORT)], cwd=REPO_ROOT,
            env={**os.environ, "SERPAPI_KEY": ""},
            capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "[ni-july-2026] wrote trips/ni-july-2026/index.html" in result.stdout
        assert "[test-mt] wrote trips/test-mt/index.html" in result.stdout
        assert "[picker] wrote index.html" in result.stdout

        # root is the trip picker. It lists only LIVE trips — the ended NI trip
        # is excluded (its dashboard still renders below), the live one is listed.
        root = (REPO_ROOT / "index.html").read_text()
        assert "window.DATA" not in root
        assert 'href="trips/test-mt/index.html"' in root and "Test MT" in root
        assert 'href="trips/ni-july-2026/index.html"' not in root
        assert "Northern Ireland" not in root

        # NI dashboard moved to trips/ni-july-2026/, keeps its shape + traveller
        ni_dash = _window_data((NI_OUT / "index.html").read_text())
        assert len(ni_dash["venues"]) > 30
        assert ni_dash["trip"]["pills"][0] == "✈ Michel · London"
        ni_html = (NI_OUT / "index.html").read_text()
        assert 'canonical" href="https://uncinimichel.github.io/climbing-agent/trips/ni-july-2026/"' in ni_html

        # the scratch trip got its own full dashboard, keyless, its own traveller
        mt = _window_data((SCRATCH / "index.html").read_text())
        assert len(mt["venues"]) == len(picks)
        assert mt["trip"]["pills"][0] == "✈ Rob · Sheffield"
        assert mt["trip"]["travellers"] == [{"key": "rob", "name": "Rob", "from": "Sheffield"}]
        html = (SCRATCH / "index.html").read_text()
        assert '"../../knowledge/index.html"' in html      # nav ../-prefixed (depth 2)
        assert 'href="knowledge/' not in html              # no root-relative leftovers
        assert 'href="../../venues/' in html               # footer venue links
        assert 'canonical" href="https://uncinimichel.github.io/climbing-agent/trips/test-mt/"' in html
        fl = json.loads((SCRATCH / "flights-latest.json").read_text())
        assert "no key" in fl["checked_at"]           # keyless run never spends quota
        assert (SCRATCH / "daily-report.md").exists()
        assert not (SCRATCH / "venues").exists()       # no per-venue pages for trip dashboards
    finally:
        TRIPS_F.write_text(registry_before)
        (REPO_ROOT / "index.html").write_text(root_before)
        shutil.rmtree(SCRATCH, ignore_errors=True)
        if SCRATCH.parent.exists() and not any(SCRATCH.parent.iterdir()):
            SCRATCH.parent.rmdir()


if __name__ == "__main__":
    test_multi_trip_renders_picker_and_dashboards()
    print("OK")

#!/usr/bin/env python3
"""Daily build entrypoint (see knowledge/roadmap/decisions.md #25/#33).

The whole pipeline lives in engine/driver.py — this script just resolves
which trips to render:

  default        — the trip owning this directory (NI), to the site root.
                   Exactly the pre-M3 behavior.
  MULTI_TRIP=1   — every `live` trip in trips.json, nearest departure first.
                   The nearest trip spends SerpApi quota; the others run
                   keyless (distance estimates + last-known prices). The trip
                   owning this directory keeps the site root; the rest render
                   to trips/<slug>/index.html. Off in the cron until the NI
                   trip ends (28 Jul) — decision #33 M3.

Outputs per trip: index.html (root or trips/<slug>/), daily-report.md,
history/<date>.md, flights-latest.json, rank-history.json.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from engine import driver, trips  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent


def _dotenv():
    f = REPO_ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_dotenv()
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")


def main():
    shared = driver.load_shared(REPO_ROOT)
    print(f"multi-pitch climbs loaded: {len(shared['mp_climbs'])}")
    home = trips.trip_for_dir(REPO_ROOT, ROOT)

    if os.environ.get("MULTI_TRIP") == "1":
        live = sorted((t for t in trips.load_trips(REPO_ROOT) if t["status"] == "live"),
                      key=lambda t: t["start"])
        for i, t in enumerate(live):
            driver.run_trip(t, REPO_ROOT, shared,
                            serpapi_key=SERPAPI_KEY if i == 0 else None,
                            site_root=(t["slug"] == home["slug"]))
    else:
        driver.run_trip(home, REPO_ROOT, shared, serpapi_key=SERPAPI_KEY, site_root=True)


if __name__ == "__main__":
    main()

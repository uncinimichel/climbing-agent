#!/usr/bin/env python3
"""Daily build entrypoint (see knowledge/roadmap/decisions.md #25/#33).

The whole pipeline lives in engine/driver.py. This script renders EVERY trip in
trips.json to its own trips/<slug>/index.html, then writes the repo-root trip
picker linking to them. There is no feature flag — the pipeline always follows
the registry, so adding a trip to trips.json is all it takes to make it appear.

Flight quota: only the nearest-departing `live` trip spends SerpApi quota; every
other trip (and any `ended` trip) renders keyless — distance estimates + last
known prices. Per trip we also write daily-report.md, history/<date>.md,
flights-latest.json and rank-history.json into the trip's own directory.
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

    all_trips = trips.load_trips(REPO_ROOT)
    live = sorted((t for t in all_trips if t["status"] == "live"), key=lambda t: t["start"])
    nearest = live[0]["slug"] if live else None  # only the soonest live trip prices flights

    # display order: soonest first, live before ended
    ordered = sorted(all_trips, key=lambda t: (t["status"] == "ended", t["start"]))
    summaries = []
    for t in ordered:
        _, data = driver.run_trip(
            t, REPO_ROOT, shared,
            serpapi_key=SERPAPI_KEY if t["slug"] == nearest else None)
        summaries.append((t, data))

    driver.render_index(REPO_ROOT, summaries)


if __name__ == "__main__":
    main()

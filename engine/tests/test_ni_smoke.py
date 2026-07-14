"""Lightweight regression check for the P0 engine/ refactor (see
knowledge/roadmap/decisions.md #25): runs the NI cron's real driver
(trip-ni-july-2026/scripts/update_report.py) against the currently-committed
venues.json/flights.json/caches and asserts it completes cleanly and produces
the expected shape — not a byte-for-byte golden-file diff (deliberately not
built; see the plan's Context section on why that's not worth it for a
deprioritized path), just "the refactor didn't break the pipeline."

SERPAPI_KEY is forced to an explicit empty string (present-but-falsy) rather
than merely unset, because update_report.py's `_dotenv()` uses
`os.environ.setdefault` — an unset var would get silently refilled from the
repo's real .env file, making this test spend live SerpApi quota. An empty
string is present, so setdefault leaves it alone, and
`ctx.serpapi_key`/`if mode == "fly" and ctx.serpapi_key` both fall through to
the link-only fallback exactly as a "no key" run does today.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPDATE_REPORT = REPO_ROOT / "trip-ni-july-2026" / "scripts" / "update_report.py"
INDEX_HTML = REPO_ROOT / "index.html"


def _extract_window_data(html):
    m = re.search(r"window\.DATA=(\{.*?\});window\.TAGT", html, re.S)
    assert m, "index.html has no window.DATA blob"
    return json.loads(m.group(1))


def test_update_report_runs_clean_and_shape_matches():
    result = subprocess.run(
        [sys.executable, str(UPDATE_REPORT)],
        cwd=REPO_ROOT,
        env={**os.environ, "SERPAPI_KEY": ""},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"update_report.py exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "wrote index.html" in result.stdout

    data = _extract_window_data(INDEX_HTML.read_text(encoding="utf-8"))
    venues = data["venues"]
    assert len(venues) > 30, f"expected a few dozen venues, got {len(venues)}"

    required_keys = {"rank", "delta", "isNew", "name", "shortName", "country", "score",
                     "wx", "series", "flights", "stays", "tags", "breakdown"}
    for v in venues:
        missing = required_keys - v.keys()
        assert not missing, f"venue {v.get('name')!r} is missing keys: {missing}"

    ranks = [v["rank"] for v in venues]
    assert ranks == sorted(ranks), "venues should be emitted in rank order"

    for who in ("michel", "dan"):
        for v in venues:
            assert who in v["flights"], f"venue {v['name']!r} missing flights.{who}"


if __name__ == "__main__":
    test_update_report_runs_clean_and_shape_matches()
    print("OK")

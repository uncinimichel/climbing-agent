"""Day-over-day ranking movement.

Each daily run records its final venue order (best-first, by venue name) in
trip-ni-july-2026/rank-history.json — {"YYYY-MM-DD": ["Lundy", ...]}. Comparing
today's order against the most recent earlier day gives every venue a position
delta (+2 = climbed two places since the last run), shown next to the rank on
the dashboard and in the markdown report. The full markdown snapshots in
history/<date>.md stay the human-readable record; this file is just the
machine-readable order so the delta doesn't need to parse markdown.

Same-day re-runs (push-triggered CI builds) overwrite today's entry, so the
comparison is always against the previous day, not the previous run.
"""
import json


def load(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def apply(path, today, ranked):
    """Annotate each result in `ranked` (best-first) with its movement vs the
    most recent recorded day before `today`, then record today's order:
      rank_delta — positions gained (+) or lost (-), 0 = unchanged,
                   None = no earlier day to compare against
      rank_new   — True when the venue wasn't in the previous day's list
    """
    history = load(path)
    prev_days = sorted(d for d in history if d < today)
    prev = ({name: n for n, name in enumerate(history[prev_days[-1]], 1)}
            if prev_days else {})
    for n, r in enumerate(ranked, 1):
        name = r["venue"]["name"]
        r["rank_delta"] = (prev[name] - n) if name in prev else None
        r["rank_new"] = bool(prev) and name not in prev
    history[today] = [r["venue"]["name"] for r in ranked]
    path.write_text(json.dumps(history, indent=1, ensure_ascii=False) + "\n")

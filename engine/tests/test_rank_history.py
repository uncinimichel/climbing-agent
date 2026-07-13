"""Unit tests for engine.rank_history — the day-over-day movement annotations
that feed the ▲/▼ badges on the dashboard and in the markdown report."""
import json

from engine import rank_history


def _ranked(*names):
    return [{"venue": {"name": n}} for n in names]


def test_first_ever_run_has_no_deltas(tmp_path):
    p = tmp_path / "rank-history.json"
    ranked = _ranked("A", "B")
    rank_history.apply(p, "2026-07-01", ranked)
    assert [r["rank_delta"] for r in ranked] == [None, None]
    assert all(not r["rank_new"] for r in ranked)
    assert json.loads(p.read_text()) == {"2026-07-01": ["A", "B"]}


def test_deltas_vs_previous_day(tmp_path):
    p = tmp_path / "rank-history.json"
    p.write_text(json.dumps({"2026-07-01": ["A", "B", "C"]}))
    ranked = _ranked("C", "A", "D")   # C 3→1, A 1→2, D new, B dropped
    rank_history.apply(p, "2026-07-02", ranked)
    assert ranked[0]["rank_delta"] == 2
    assert ranked[1]["rank_delta"] == -1
    assert ranked[2]["rank_delta"] is None and ranked[2]["rank_new"]
    assert json.loads(p.read_text())["2026-07-02"] == ["C", "A", "D"]


def test_same_day_rerun_still_compares_to_yesterday(tmp_path):
    p = tmp_path / "rank-history.json"
    p.write_text(json.dumps({"2026-07-01": ["A", "B"],
                             "2026-07-02": ["B", "A"]}))
    ranked = _ranked("A", "B")   # re-run on the 2nd: vs the 1st, not vs 09:00's run
    rank_history.apply(p, "2026-07-02", ranked)
    assert [r["rank_delta"] for r in ranked] == [0, 0]
    assert json.loads(p.read_text())["2026-07-02"] == ["A", "B"]


def test_compares_to_most_recent_earlier_day_not_adjacent(tmp_path):
    p = tmp_path / "rank-history.json"
    p.write_text(json.dumps({"2026-06-28": ["B", "A"],
                             "2026-07-01": ["A", "B"]}))
    ranked = _ranked("B", "A")
    rank_history.apply(p, "2026-07-03", ranked)   # gap: cron missed 2 days
    assert ranked[0]["rank_delta"] == 1   # B was 2nd on 07-01
    assert ranked[1]["rank_delta"] == -1

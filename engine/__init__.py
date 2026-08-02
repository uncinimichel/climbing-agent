"""DEPRECATED import surface — kept so nothing outside had to move.

The engine was one climbing-shaped package. It is now split by what the code
actually knows about:

    core/            sport-agnostic tools — weather providers + derived metrics,
                     travel (flights, stays), cache, http, geo, quota, scoring
                     primitives, the trip context, and the Sport port
    domains/<sport>/ everything that only makes sense for one sport

Every name that used to be importable as `engine.X` still is, forwarding to its
new home, so update_report.py, fetch_env.py, backtest_ranking.py, admin/server.py
and the tests keep working unchanged. New code should import from `core.*` and
`domains.<sport>.*` directly — that is where the docs and the type of change you
are making will point you.
"""

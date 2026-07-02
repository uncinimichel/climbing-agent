# Testing plan — a regression net for the daily build

**Status: ⛔ *(planned)* — no tests exist yet.** This is the plan to add them. The goal is
narrow and defensive: **let us change `update_report.py` without breaking the two things
that matter — calling the APIs and generating the HTML/Markdown.** Source of truth for all
behaviour described here is [`trip-ni-july-2026/scripts/update_report.py`](../../trip-ni-july-2026/scripts/update_report.py).

Expands roadmap Stage 0 item 10 ([`roadmap/roadmap.md`](../roadmap/roadmap.md)). Run the
suite as a gate before the deploy step in [`weather.yml`](../../.github/workflows/weather.yml).

## Why this is cheap to do here

The engine already has the two seams testing needs — no big refactor required:

1. **One network chokepoint.** Every external call — Open-Meteo `forecast` / `climatology` /
   `seasonal`, SerpApi flights, and the multi-pitch.com climb DB — funnels through
   `_get(url)` (`update_report.py:165`). Monkeypatch that one function and the whole
   pipeline runs **offline and deterministic**.
2. **Time is already injected.** `build_html` / `build_md` take `now` as a parameter, so
   the generated output is reproducible once the network is mocked and the date is frozen.
   (Only `main()` calls `datetime.now()` internally — `:1057`.)

This matches the repo's **determinism** convention ([`CONVENTIONS.md`](../CONVENTIONS.md)):
climatology scoring must give two identical runs, so it is testable by construction.

## Framework & dependencies

- **Stdlib `unittest`, no new dependencies.** The engine is deliberately stdlib-only and CI
  runs bare `python3`; `python3 -m unittest discover tests` needs zero installs. Pytest is a
  later option only if we want parametrize/fixtures — not worth a dependency now.
- **Offline by default.** The fast suite never touches the network, so it can't consume
  SerpApi quota or flake on an outage — consistent with **quota discipline** and
  **degrade-never-crash**.

## The five test types (most-valuable first)

1. **Golden-master (snapshot) — the primary regression guard.**
   Freeze `now`, feed recorded API JSON through a fake `_get`, and assert
   `build_html(...)` / `build_md(...)` match a checked-in `expected_index.html` /
   `expected_report.md` byte-for-byte. Any unintended change to the template, a link, or a
   score shows up as a failing diff. This is what protects "the HTML still generates."

2. **Pure-function unit tests — precise logic coverage.** No I/O; test known input → known
   output on the business logic:
   - Scoring: `day_score`, `climo_score`, `evaluate` (rain/storm caps, temp penalties),
     `rank` (score order + `prio_num` tiebreak).
   - Text/normalisation: `_norm`, `_grade_norm`, `grade_range`, `wx_band`, `match_sheet_row`.
   - Geo/format: `_haversine` (known city pairs), `_hhmm`, `skyscanner_url`.

3. **Parser / API-contract tests — guards the "calling the API" side.** Feed a *recorded
   real* Open-Meteo and SerpApi response into `forecast`, `climatology`, `seasonal`,
   `serp_flights` and assert the right fields are extracted. Catches parsing regressions;
   with fresh fixtures, catches upstream schema drift too.

4. **End-to-end smoke test.** Run `main()` with `_get` mocked and the output path constants
   (`INDEX` / `DAILY` / `HISTORY`, `:35`) redirected to a temp dir. Assert: clean exit, a
   non-empty `index.html`, the embedded `window.DATA` JSON parses, and the HTML is
   well-formed (stdlib `html.parser`). Also assert the **degrade path**: with `_get` raising,
   the build still completes with a weaker basis rather than crashing.

5. **Opt-in live contract test.** A test that actually hits Open-Meteo/SerpApi to detect
   real API changes. Skipped by default (env flag); run weekly or on demand — never in the
   PR suite, to protect quota.

## Layout

```
tests/
  fixtures/            # recorded API JSON + expected_index.html / expected_report.md
  test_scoring.py      # type 2
  test_parsers.py      # type 3
  test_golden.py       # types 1 + 4
  record_fixtures.py   # manual: refresh fixtures from live APIs
  test_live.py         # type 5 (skipped unless LIVE=1)
```

## Phases

- **Phase 1 — pure-function unit tests (type 2).** No fixtures, no mocking, no source
  changes. Immediate safety net.
- **Phase 2 — record fixtures + golden-master (types 1, 4).** The real regression guard for
  API-driven HTML/MD output.
- **Phase 3 — parser/contract tests (type 3) + CI.** Add a **separate `tests.yml`** on
  `push`/`pull_request` that runs only the offline suite. Keep it *out* of the `weather.yml`
  build job so tests never burn SerpApi quota or commit to `main`; gate deploy on it.
- **Phase 4 — opt-in live test (type 5).**

## Refactor cost

**Phases 1–3 need no source changes** — tests monkeypatch `_get` and the module-level path
constants directly. One *optional* tidy-up: let `main()` accept an injected `now` (default
`datetime.now(timezone.utc)`) so the smoke test is fully deterministic.

## Invariants worth asserting (beyond snapshots)

These encode the conventions, so a refactor can't silently violate them:
- **Determinism:** two `rank()` runs on the same input give identical order.
- **Degrade-never-crash:** any single `_get` failure still yields a complete page.
- **Quota cap:** flights are priced for at most `TOP_N_FLIGHTS` venues.
- **No secrets / key-free build:** with `SERPAPI_KEY` unset, the build completes and emits
  search links instead of prices.

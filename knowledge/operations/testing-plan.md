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
   `seasonal` / marine tide, SerpApi flights, and the multi-pitch.com climb DB — funnels
   through the single `_get(url)` in `update_report.py` (and, since decision #24,
   `fetch_env.py` reuses it via the same module). Monkeypatch that one function and the
   whole pipeline runs **offline and deterministic**.
2. **Time is already injected.** `build_html` / `build_md` take `now` as a parameter, so
   the generated output is reproducible once the network is mocked and the date is frozen.
   (`main()` is where the run's `datetime.now()` originates.)

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
   (`INDEX` / `DAILY` / `HISTORY`) redirected to a temp dir. Assert: clean exit, a
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

## Site & data integrity — mechanizing the manual inspections *(planned)*

Every check done by eye while building the corpus / inspector / data-map (decision
[#27](../roadmap/decisions.md)) is mechanizable — stdlib-only, offline, deterministic. A
machine won't skip one. Proposed `engine/tests/test_site_integrity.py` (the pipeline smoke,
type 4 above, already exists as [`test_ni_smoke.py`](../../engine/tests/test_ni_smoke.py)).
Each row is a check I currently run by hand → the assertion that replaces it.

**A · Corpus data integrity** (`db/corpus.json` + the served copy)
- Valid JSON; has `schemaVersion` / `areas[]` / `routes[]` / `counts`.
- `counts.*` equal the real lengths + status splits (`routes`, `routesCurated`=publish, `routesSeeded`=draft).
- **Referential:** every `route.area` resolves to an `areas[]` id — no dangling refs.
- **Closed-enum:** every `disciplines`/`features`/`character`/`hazards`/`incline`/`gradeSys`/`protection` value is in the taxonomy (cross-checked against [`tag-spec.json`](../data/tag-spec.json) / [`taxonomy.md`](../data/taxonomy.md)) — off-dictionary → fail, mirroring the DB's FK guard (#18).
- `status` ∈ {publish, draft, quarantined}; `dataGrade` ∈ 1–7 or null; lat/lon in range or null.
- **No drift:** `db/corpus.json` byte-equals `knowledge/data/corpus.json` (the deployed copy).

**B · Link integrity** — kills the "`…/source-of-truth.html` 404" class. Crawl every committed
`knowledge/**/*.html` **and the `render.py` nav template** for `href`/`src`; each relative
target must exist on disk. (External URLs → the live smoke, G.)

**C · HTML structure** — each standalone page (`corpus-inspector`, `data-dependencies`)
parses with `html.parser`; exactly one `<script>`/`<style>`; has doctype, `<title>`, viewport
meta. `data-dependencies`: **every `EDGES` node id exists as an element id** (the check I run
by hand each time).

**D · Knowledge-index completeness** — every `knowledge/**/*.md` has a `TITLES` entry and
appears in a `GROUPS` group, and every `GROUPS` key resolves to a real page. Catches "added a
doc, forgot to list it."

**E · Generator determinism** — `build_knowledge.py` run twice → identical output;
`render_page(...)` output contains the nav links; `build_corpus.py` importable and, with a
stubbed multi-pitch fetch, yields both curated and seeded rows.

**F · Render smoke** *(browser, CI-gated — skip if no Chrome)* — the mechanical form of the
screenshots: headless-load `corpus-inspector.html`, assert **no uncaught console errors** and
card count == `counts.routes`; load `data-dependencies.html`, assert N edge `<path>` elements
drawn. Asserts *"it rendered,"* not pixels.

**G · Post-deploy live smoke** — the *"automatically after deployed"* gate: a job that runs
**after** the Pages deploy and `curl`s the live URLs, asserting `200` + a marker string:
`/` contains the Inspector + Data-map nav links · `/knowledge/corpus-inspector.html` &
`/knowledge/data-dependencies.html` → 200 · `/knowledge/data/corpus.json` → 200, parses,
counts match.

**Wiring:** A–E run offline in the **separate `tests.yml`** (Phase 3) on push — cheap, no
SerpApi, gates deploy. F is opt-in (needs a browser). **G is a new `verify-deploy` job that
runs after `deploy-pages`** in [`weather.yml`](../../.github/workflows/weather.yml). This is
the ordering you asked for: build → deploy → **then** the live checks. *(CI wiring in
`weather.yml` is the trip-planner process's file — coordinate before adding G.)*

# Conventions

How to write docs and code in this repo, so the knowledge base stays trustworthy and the
engine stays maintainable. Read this before contributing (human or agent).

## Documentation conventions

- **Vision vs reality, always separated.** State the North Star, then label what's real
  with ✅ live · ⚠️ partial · ⛔ *(planned)*. Never let aspiration read as fact — the
  antidote is [`architecture/current-state.md`](architecture/current-state.md).
- **This folder is reference, not a changelog.** Durable "how/why" lives here; the trip's
  running state lives in `trip-ni-july-2026/` (report, history, log). Don't duplicate.
- **One concept per file**, cross-linked. Prefer linking to repeating.
- **Keep it in sync with code.** If you change scoring, the workflow, or a schema, update
  the matching doc in the same change. Stale docs are worse than none.
- **Cite the source of truth.** When a doc describes behaviour, point at the file that
  implements it (`update_report.py`, `weather.yml`, `venues.json`).
- **Log non-obvious calls** in [`roadmap/decisions.md`](roadmap/decisions.md).
- **Honest uncertainty.** Where a number is a weak signal (sub-seasonal outlook), say so.

## Code conventions

- **Config over code.** Add venues/dates/routes by editing `venues.json` / `flights.json`,
  never by hard-coding in the script. The script reads config to decide what to do.
- **Outputs are generated — never hand-edit** `index.html`, `daily-report.md`,
  `history/*`, or `*-latest.json`. Edit the generator (`update_report.py`) instead.
- **Determinism where it's verified.** Climatology scoring must be reproducible (two runs
  → identical order). Don't introduce nondeterminism into the ranking base.
- **Degrade, never crash.** Any external source can fail; define the fallback (weaker
  basis, search link, cached value). The daily build must not hard-fail on an outage.
- **Quota discipline.** Guard paid APIs with a constant cap (`TOP_N_FLIGHTS`); log what
  was dropped rather than silently truncating.
- **Match the surrounding style.** Mirror the existing naming, comment density, and idiom
  in `update_report.py`.

## Secrets & privacy

- **No secrets in committed files.** `SERPAPI_KEY` lives in a GitHub Actions secret +
  gitignored `.env`. The build must run without it.
- **No personal data in the public repo.** The repo is public for free Pages; PII (e.g.
  home address) stays in Claude's local memory only.
- **Social scraping (planned):** respect platform ToS + privacy; emit only aggregated,
  non-personal condition summaries — never raw personal captures into the repo.

## Git / workflow

- **Docs-only commits skip the expensive build** (`paths-ignore: ['**.md']` in the
  workflow) — so editing this knowledge base won't burn SerpApi quota. Good.
- Commit or push only when asked; branch off `main` first if you do.
- The daily job commits as `trip-bot`; a no-change run commits nothing.

## Naming

- Knowledge files: lowercase-kebab, grouped by the numbered/topic folders above.
- Data dictionary values: closed enums from [`data/taxonomy.md`](data/taxonomy.md) — never
  invent an off-dictionary value.
- Venues: keep a stable `name`; carry `lat`/`lon`, `priority`, `rock`, `style`, `why`.

## For AI agents picking up this repo

1. Read `README.md` → `architecture/current-state.md` → the relevant layer in
   `architecture/phases.md`.
2. Check `data/schemas.md` and `operations/` before writing code.
3. Prefer config edits to code edits.
4. Run the [verification checklist](operations/runbook.md) after changes.
5. Log decisions; keep vision and reality clearly separated.
6. When the task touches Claude/Anthropic APIs, consult the `/claude-api` reference.

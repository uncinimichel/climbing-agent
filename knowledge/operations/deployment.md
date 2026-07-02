# Deployment

The engine is **fully serverless and free** — it runs in GitHub Actions on a schedule and
publishes to GitHub Pages. No laptop, no paid server, no Claude in the daily loop.

## The daily job — `.github/workflows/weather.yml`

### Triggers
- `schedule: "0 6 * * *"` — daily at **06:00 UTC**.
- `push` to `main` — rebuild + redeploy, but `paths-ignore: ['**.md']` so docs-only
  commits don't burn SerpApi quota.
- `workflow_dispatch` — manual "Run workflow" button.

All three run the same build.

### Permissions & concurrency
```yaml
permissions:
  contents: write   # commit the updated report back
  pages: write      # deploy to GitHub Pages
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: true   # avoid overlapping deploys
```

### Jobs
1. **build** (`ubuntu-latest`):
   - `actions/checkout@v4`
   - `actions/setup-python@v5` (Python 3.12)
   - Run `python3 trip-ni-july-2026/scripts/update_report.py` with
     `SERPAPI_KEY` from secrets in `env`.
   - Commit changed outputs (`index.html`, `.nojekyll`, `daily-report.md`, `history/`,
     `flights-latest.json`) as user `trip-bot`; **no-change → no commit**.
   - `actions/upload-pages-artifact@v3` (path `.`).
2. **deploy** (`needs: build`): `actions/deploy-pages@v4` → publishes to Pages.

### Output
<https://uncinimichel.github.io/climbing-agent/> — public, mobile.

## Secrets

| Secret | Where | Purpose |
|---|---|---|
| `SERPAPI_KEY` | GitHub Actions secret **+** gitignored local `.env` | Google Flights via SerpApi. Masked in logs. |

- **Weather APIs need no key** (Open-Meteo).
- `.env` is **gitignored** — never commit it. No secret should appear in any committed
  file.
- **Rotate the key:**
  `gh secret set SERPAPI_KEY --repo uncinimichel/climbing-agent` and update local `.env`.
  (The key was once pasted in chat → rotating is advisable.)

## Hosting / Pages

- **GitHub Pages**, `build_type = workflow` (deploy from the Action, not a branch).
- The repo is **public** (required for free rendered Pages). No personal data lives in the
  repo — the home address is only in Claude's local memory, never committed.
- `.nojekyll` disables Jekyll processing so the raw HTML is served as-is.

## State model

The **repo is the database**:
- `flights-latest.json` — latest snapshot (persists across weather-only runs).
- `history/YYYY-MM-DD.md` + git log — the permanent, append-only archive.

## Operational cautions

- **SerpApi quota** — top-4 venues × 2 travellers ≈ up to 8 searches/day. Balance is
  finite; top up near the trip, or lower `TOP_N_FLIGHTS` / run less often to throttle.
- **Scheduled jobs can lag** a few minutes and are **paused after ~60 days of repo
  inactivity** — not a risk here (it commits daily).
- **Node20→24 deprecation** on some actions is a warning only; bump versions when
  convenient (backlog item).

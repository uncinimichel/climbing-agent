#!/usr/bin/env python3
"""Log the SerpApi quota each run and render a live HTML dashboard.

SerpApi's `account.json` endpoint reports remaining search quota and **does not
itself consume a search** — so this is free to call on every build. We append a
timestamped record to `trip-ni-july-2026/serpapi-usage.json` (a capped history)
and regenerate `knowledge/operations/serpapi-quota.html`, reusing the knowledge
site's theme so it publishes with the rest of the pages.

Golden rule (external-apis.md): a source failing must never fail the build. If the
key is missing or the endpoint errors, we log a warning, refresh the page in an
"unknown" state, and exit 0.

Run: python3 trip-ni-july-2026/scripts/serpapi_quota.py
"""
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Reuse the knowledge site's page shell (nav bar + CSS) so this page matches.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_knowledge import page  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = REPO_ROOT / "trip-ni-july-2026" / "serpapi-usage.json"
HTML_PATH = REPO_ROOT / "knowledge" / "operations" / "serpapi-quota.html"
ACCOUNT_URL = "https://serpapi.com/account.json?api_key="
MAX_HISTORY = 180  # ~6 months of daily runs


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


def _redact(s):
    s = str(s)
    return s.replace(SERPAPI_KEY, "***") if SERPAPI_KEY else s


def fetch_account():
    """Return the account dict, or None on any failure (never raises)."""
    if not SERPAPI_KEY:
        print("[warn] serpapi_quota: SERPAPI_KEY not set — skipping fetch.", file=sys.stderr)
        return None
    url = ACCOUNT_URL + SERPAPI_KEY
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — degrade on anything
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"[warn] serpapi_quota: account.json failed: {_redact(e)}", file=sys.stderr)
    return None


def load_log():
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {
        "comment": "SerpApi (Google Flights) quota, sampled each run via account.json "
                   "(consumes no search). Newest entries appended; capped history.",
        "history": [],
    }


def record(acct):
    """Build one history row from the account response (or an 'unknown' row)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not acct:
        return {"at": now, "ok": False, "plan": None, "per_month": None,
                "left": None, "total_left": None, "month_usage": None, "hour": None}
    return {
        "at": now,
        "ok": True,
        "plan": acct.get("plan_name"),
        "per_month": acct.get("searches_per_month"),
        "left": acct.get("plan_searches_left"),
        "total_left": acct.get("total_searches_left"),
        "month_usage": acct.get("this_month_usage"),
        "hour": acct.get("this_hour_searches"),
        "hour_limit": acct.get("account_rate_limit_per_hour"),
    }


# ── HTML rendering ───────────────────────────────────────────────────────────
def _tone(frac):
    """Green / amber / red var name by fraction of monthly quota remaining."""
    if frac is None:
        return "--chalk3"
    if frac > 0.5:
        return "--go"
    if frac >= 0.2:
        return "--amb"
    return "--wet"


def _num(v):
    return "—" if v is None else html.escape(str(v))


def render(log):
    hist = log.get("history", [])
    latest = hist[-1] if hist else None

    body = ['<h1>🛰️ SerpApi Quota — Live</h1>',
            '<p>Remaining <strong>Google Flights</strong> search quota, sampled on every '
            'build via SerpApi\'s <code>account.json</code> (which itself costs no search). '
            'Flight pricing degrades to "search ↗" links once this hits zero — the build '
            'never fails. See <a href="external-apis.html">External APIs</a>.</p>']

    if latest and latest.get("ok"):
        per = latest.get("per_month")
        left = latest.get("left")
        used = latest.get("month_usage")
        frac = (left / per) if (per and left is not None) else None
        pct_used = round(100 * used / per) if (per and used is not None) else None
        tone = _tone(frac)
        bar_pct = round(100 * (used / per)) if (per and used is not None) else 0
        bar_pct = max(0, min(100, bar_pct))

        body.append(
            '<div style="background:var(--ink2);border:1px solid var(--seam);'
            'border-radius:var(--r-lg);padding:20px 22px;margin:1.2em 0">'
            f'<div style="font-family:\'Syne\',sans-serif;font-size:34px;font-weight:800;'
            f'color:var({tone})">{_num(left)} <span style="font-size:16px;color:var(--chalk2);'
            f'font-weight:600">/ {_num(per)} searches left</span></div>'
            f'<div style="color:var(--chalk2);font-size:13px;margin:4px 0 14px">'
            f'{_num(used)} used this month · plan: {_num(latest.get("plan"))} · '
            f'checked {html.escape(latest.get("at",""))}</div>'
            f'<div style="height:10px;background:var(--ink4);border-radius:6px;overflow:hidden">'
            f'<div style="height:100%;width:{bar_pct}%;background:var({tone})"></div></div>'
            f'<div style="color:var(--chalk3);font-size:12px;margin-top:6px;'
            f'font-family:\'DM Mono\',monospace">{pct_used if pct_used is not None else "?"}% of '
            f'monthly quota used · hour rate limit {_num(latest.get("hour_limit"))}/h</div>'
            '</div>')
    else:
        body.append(
            '<div style="background:var(--ink2);border:1px solid var(--seam);'
            'border-radius:var(--r-lg);padding:20px 22px;margin:1.2em 0;color:var(--chalk2)">'
            '<strong style="color:var(--amb)">Quota unknown</strong> — the last sample failed '
            '(key missing or endpoint error). Flight cells fall back to search links until the '
            'next successful check.</div>')

    # history table (newest first)
    rows = ['<h2>History</h2>',
            '<div class="tw"><table><thead><tr>'
            '<th>Checked (UTC)</th><th>Left</th><th>Used (month)</th>'
            '<th>Per month</th><th>Plan</th></tr></thead><tbody>']
    for r in reversed(hist[-40:]):
        if r.get("ok"):
            rows.append(
                f'<tr><td>{html.escape(r.get("at",""))}</td><td>{_num(r.get("left"))}</td>'
                f'<td>{_num(r.get("month_usage"))}</td><td>{_num(r.get("per_month"))}</td>'
                f'<td>{_num(r.get("plan"))}</td></tr>')
        else:
            rows.append(
                f'<tr><td>{html.escape(r.get("at",""))}</td>'
                f'<td colspan="4" style="color:var(--chalk3)">check failed</td></tr>')
    rows.append('</tbody></table></div>')
    body += rows

    crumb = ('<a href="../index.html">📚 knowledge</a> / operations / '
             '<b style="color:var(--chalk2)">serpapi-quota.html</b>')
    return page("SerpApi Quota", "\n".join(body), 2, crumb)


def main():
    acct = fetch_account()
    log = load_log()
    log.setdefault("history", []).append(record(acct))
    log["history"] = log["history"][-MAX_HISTORY:]
    LOG_PATH.write_text(json.dumps(log, indent=2) + "\n")
    HTML_PATH.write_text(render(log), encoding="utf-8")
    latest = log["history"][-1]
    if latest.get("ok"):
        print(f"SerpApi quota: {latest['left']}/{latest['per_month']} left "
              f"({latest['month_usage']} used this month) → {HTML_PATH.name}")
    else:
        print(f"SerpApi quota: check failed (logged) → {HTML_PATH.name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the trip dashboard from free Open-Meteo weather + flight data.

Outputs:
  index.html (repo root)            concise, ranked, self-contained HTML for GitHub Pages
  trip-ni-july-2026/daily-report.md short markdown mirror (renders on github.com)
  trip-ni-july-2026/history/<date>.md permanent dated snapshot

Ranking: every venue is scored on the forecast for the TARGET WINDOW when it is
within the 16-day horizon; until then it falls back to the NEAREST queryable
forecast day (closest to the trip) as an explicitly-labelled proxy. No deps, no
API key — standard library only, runs on a bare GitHub Actions runner.
"""
import json
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # trip-ni-july-2026/
REPO_ROOT = ROOT.parent                            # repo root (for index.html)
HISTORY = ROOT / "history"
DAILY = ROOT / "daily-report.md"
INDEX = REPO_ROOT / "index.html"

_cfg = json.loads((ROOT / "venues.json").read_text())
TRIP_NAME = _cfg["trip"]
TARGET_START = date.fromisoformat(_cfg["target_window"]["start"])
TARGET_END = date.fromisoformat(_cfg["target_window"]["end"])
VENUES = _cfg["venues"]
FLIGHTS_CFG = json.loads((ROOT / "flights.json").read_text())
FLIGHTS_DATA = json.loads((ROOT / "flights-latest.json").read_text())

WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "showers", 81: "showers", 82: "violent showers",
    95: "thunderstorm", 96: "thunderstorm+hail", 99: "thunderstorm+hail",
}


def fetch(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,windspeed_10m_max"
        "&timezone=auto&forecast_days=16"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def day_score(code, mm, prob):
    """0 (washed out) .. 100 (perfect)."""
    s = 100.0 - (prob or 0) * 0.8 - (mm or 0) * 6
    if code is not None and code >= 61:
        s = min(s, 25)
    if code in (95, 96, 99):
        s = min(s, 15)
    return max(0.0, min(100.0, s))


def evaluate(v):
    """Return dict with score, weather summary, the date(s) used, and mode."""
    try:
        d = fetch(v["lat"], v["lon"])["daily"]
    except Exception as e:
        return {"venue": v, "ok": False, "error": str(e), "score": -1}

    days = d["time"]
    valid = [i for i in range(len(days)) if d["temperature_2m_max"][i] is not None]
    in_win = [i for i in valid if TARGET_START <= date.fromisoformat(days[i]) <= TARGET_END]
    if in_win:
        idx = in_win
        mode = "target window"
        used_label = f"{days[idx[0]]} … {days[idx[-1]]}"
    elif valid:
        idx = [valid[-1]]              # nearest queryable day to the trip
        mode = "nearest available"
        used_label = days[idx[0]]
    else:
        return {"venue": v, "ok": False, "error": "no forecast days", "score": -1}

    scores = [day_score(d["weathercode"][i], d["precipitation_sum"][i],
                        d["precipitation_probability_max"][i]) for i in idx]
    tmax = sum(d["temperature_2m_max"][i] for i in idx) / len(idx)
    prob = max((d["precipitation_probability_max"][i] or 0) for i in idx)
    codes = [d["weathercode"][i] for i in idx]
    sky = WMO.get(max(set(codes), key=codes.count), "?")
    return {
        "venue": v, "ok": True, "score": round(sum(scores) / len(scores)),
        "tmax": round(tmax), "rain_prob": prob, "sky": sky,
        "used_label": used_label, "mode": mode,
        "horizon": days[-1],
    }


def prio_num(v):
    for ch in v.get("priority", "9"):
        if ch.isdigit():
            return int(ch)
    return 9


def rank(results):
    ok = [r for r in results if r.get("ok")]
    ok.sort(key=lambda r: (-r["score"], prio_num(r["venue"])))
    return ok + [r for r in results if not r.get("ok")]


def cheapest_flight():
    priced = [(d["cheapest_gbp"], cid) for cid, d in FLIGHTS_DATA["combos"].items()
              if d.get("cheapest_gbp") is not None]
    return min(priced) if priced else None


# ---- HTML -----------------------------------------------------------------
def badge(score):
    if score < 0:
        return "#888", "n/a"
    if score >= 70:
        return "#1a7f37", f"{score}"     # green
    if score >= 45:
        return "#bf8700", f"{score}"     # amber
    return "#cf222e", f"{score}"         # red


def build_html(ranked, now, proxy_note):
    rows = []
    for n, r in enumerate(ranked, 1):
        v = r["venue"]
        if not r.get("ok"):
            rows.append(f"<tr><td>{n}</td><td>{v['name']}</td><td colspan=5 class='muted'>fetch failed</td></tr>")
            continue
        color, label = badge(r["score"])
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, "")
        rows.append(
            f"<tr><td class='rk'>{medal}{n}</td>"
            f"<td><b>{v['name']}</b><div class='sub'>{v['country']} · {v.get('style','')}</div></td>"
            f"<td><span class='score' style='background:{color}'>{label}</span></td>"
            f"<td>{r['tmax']}°C</td><td>{r['rain_prob']}%</td><td>{r['sky']}</td>"
            f"<td class='sub'>{v.get('hub','')}</td></tr>"
        )
    table = "\n".join(rows)

    top = ranked[0] if ranked and ranked[0].get("ok") else None
    top_html = (
        f"<div class='pick'><span class='pin'>📍 Top pick right now</span>"
        f"<h2>{top['venue']['name']} <small>({top['venue']['country']})</small></h2>"
        f"<p>{top['venue'].get('why','')}</p>"
        f"<p class='sub'>Score {top['score']}/100 · {top['tmax']}°C · {top['rain_prob']}% rain · {top['sky']}</p></div>"
        if top else "<div class='pick'><p>No forecast available.</p></div>"
    )

    # flights
    fr = FLIGHTS_CFG["route"]
    cf = cheapest_flight()
    frows = "".join(
        f"<tr><td>{c['out']}→{c['back']}</td><td>{c['nights']}n</td>"
        f"<td>{('£'+str(FLIGHTS_DATA['combos'][c['id']]['cheapest_gbp'])) if FLIGHTS_DATA['combos'][c['id']].get('cheapest_gbp') is not None else '—'}</td>"
        f"<td class='sub'>{FLIGHTS_DATA['combos'][c['id']].get('notes','')}</td></tr>"
        for c in FLIGHTS_CFG["combos"]
    )
    cheap_line = (f"Cheapest: <b>{cf[1]} £{cf[0]}</b>" if cf
                  else f"Indicative ~£80–120 return (Ryanair/easyJet) — live check nearer the date")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Climbing Trip Planner — Michel &amp; Dan, ~24 Jul 2026</title>
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
margin:0;padding:18px;max-width:760px;margin:auto;color:#1c2024;background:#fff}}
@media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}
.card{{background:#161b22;border-color:#30363d}} th{{color:#9da7b3}} tr{{border-color:#21262d}}}}
h1{{font-size:20px;margin:0 0 2px}} h2{{margin:.1em 0;font-size:18px}}
.lead{{color:#57606a;margin:.2em 0 14px;font-size:13px}}
.warn{{background:#fff8c5;border:1px solid #d4a72c;color:#54470b;padding:8px 11px;
border-radius:8px;font-size:13px;margin:0 0 14px}}
@media(prefers-color-scheme:dark){{.warn{{background:#272115;color:#e3d8a8;border-color:#6b5d2a}}}}
.card{{border:1px solid #d0d7de;border-radius:10px;padding:12px 14px;margin:0 0 14px;background:#f6f8fa}}
.pick{{border-left:5px solid #1a7f37}}
.pin{{font-size:12px;font-weight:700;color:#1a7f37;text-transform:uppercase;letter-spacing:.04em}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{text-align:left;padding:7px 6px;border-bottom:1px solid #eaeef2;vertical-align:top}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#57606a}}
.rk{{font-weight:700;white-space:nowrap}}
.sub{{color:#7d8590;font-size:12px}}
.score{{display:inline-block;min-width:34px;text-align:center;color:#fff;font-weight:700;
padding:2px 6px;border-radius:6px}}
.muted{{color:#7d8590}}
footer{{color:#7d8590;font-size:12px;margin-top:8px}}
</style></head><body>
<h1>🧗 Climbing Trip Planner — where should Michel &amp; Dan go?</h1>
<p class="lead">Multi-pitch trip around <b>Fri 24 – Tue 28 Jul 2026</b> · ranked best-first by forecast ·
updated {now:%Y-%m-%d %H:%M UTC}</p>
<div class="warn">{proxy_note}</div>
{top_html}
<div class="card">
<table>
<tr><th>#</th><th>Venue</th><th>Score</th><th>Max°C</th><th>Rain</th><th>Sky</th><th>Getting there</th></tr>
{table}
</table>
<p class="sub">Score 0–100 (higher = drier/better). 🥇 = best option right now.</p>
</div>
<div class="card">
<h2>✈️ Flights — London ⇄ Belfast</h2>
<p class="sub">{fr['passengers']} pax · 3–4 nights · target ≤ £{FLIGHTS_CFG['target_price_gbp']} · {cheap_line}</p>
<table><tr><th>Dates</th><th>Nights</th><th>Price</th><th>Notes</th></tr>{frows}</table>
</div>
<footer>Weather: Open-Meteo (free). Flights: indicative / on-demand (no free price API).
Source &amp; history: github.com/uncinimichel/climbing-agent</footer>
</body></html>
"""


def build_md(ranked, now, proxy_note):
    lines = [f"# {TRIP_NAME}", "",
             f"**Updated:** {now:%Y-%m-%d %H:%M UTC} · ranked best-first.", "",
             f"> {proxy_note}", "", "## 🏆 Ranking", "",
             "| # | Venue | Score | Max°C | Rain% | Sky | Getting there |",
             "|---|---|---|---|---|---|---|"]
    for n, r in enumerate(ranked, 1):
        v = r["venue"]
        if not r.get("ok"):
            lines.append(f"| {n} | {v['name']} | n/a | | | fetch failed | |")
            continue
        lines.append(f"| {n} | {v['name']} | {r['score']} | {r['tmax']} | {r['rain_prob']} | {r['sky']} | {v.get('hub','')} |")
    cf = cheapest_flight()
    lines += ["", "## ✈️ Flights (London ⇄ Belfast, 3–4 nights)", "",
              ("Cheapest: " + f"{cf[1]} £{cf[0]}" if cf else "Indicative ~£80–120 return; live check nearer the date."),
              "", "| Dates | Nights | Price | Notes |", "|---|---|---|---|"]
    for c in FLIGHTS_CFG["combos"]:
        d = FLIGHTS_DATA["combos"][c["id"]]
        p = f"£{d['cheapest_gbp']}" if d.get("cheapest_gbp") is not None else "—"
        lines.append(f"| {c['out']}→{c['back']} | {c['nights']} | {p} | {d.get('notes','')} |")
    lines += ["", "_Full rendered dashboard: see index.html (GitHub Pages)._"]
    return "\n".join(lines) + "\n"


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    results = [evaluate(v) for v in VENUES]
    ranked = rank(results)

    sample = next((r for r in ranked if r.get("ok")), None)
    if sample and sample["mode"] == "target window":
        proxy_note = (f"✅ Trip dates are within forecast range — ranked on the actual "
                      f"target window ({sample['used_label']}).")
    elif sample:
        used = date.fromisoformat(sample["used_label"])
        days_before = (TARGET_START - used).days
        proxy_note = (f"⚠️ Trip dates (22–28 Jul) are still beyond the 16-day forecast limit "
                      f"(forecast reaches {sample['horizon']}). Ranked on the <b>nearest queryable "
                      f"day, {sample['used_label']}</b> — ~{days_before} days before the trip, so "
                      f"<b>indicative only</b>. Re-ranks on real trip-window weather from ~8 Jul.")
    else:
        proxy_note = "⚠️ No forecast data available right now."

    INDEX.write_text(build_html(ranked, now, proxy_note))
    md = build_md(ranked, now, proxy_note)
    DAILY.write_text(md)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(md)
    order = " > ".join(r["venue"]["name"] for r in ranked if r.get("ok"))
    print(f"Wrote index.html, daily-report.md, history/{today}.md")
    print("Ranking:", order)


if __name__ == "__main__":
    main()

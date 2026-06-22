#!/usr/bin/env python3
"""Build the trip dashboard from free weather data + flight prices.

Two free, key-less weather signals (no secrets, repo is public):
  1. CLIMATOLOGY — typical late-July conditions per venue from Open-Meteo's
     historical archive (ERA5). Available NOW, months ahead — this is how we
     "get weather early". Used for ranking until the live forecast reaches the trip.
  2. FORECAST — Open-Meteo 16-day forecast. Takes over the ranking from ~8 July,
     when the trip window enters range.

Outputs: index.html (repo root, for GitHub Pages), trip-ni-july-2026/daily-report.md,
and a permanent trip-ni-july-2026/history/<date>.md snapshot. Stdlib only.
"""
import json
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
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

CLIMO_YEARS = [2021, 2022, 2023, 2024]   # recent years to average for "typical July"
SITE_URL = "https://multi-pitch.com/"    # Michel & Dan's climbing site
SHEET_URL = "https://docs.google.com/spreadsheets/d/1N4Xs-aSGFc8-ibysqpdCvQIfMH4Rjx4n5WQnqITGPC8/edit"
REPO_URL = "https://github.com/uncinimichel/climbing-agent"


def maps_url(v):
    return f"https://www.google.com/maps/search/?api=1&query={v['lat']},{v['lon']}"

WMO = {
    0: "☀️ clear", 1: "🌤️ mostly clear", 2: "⛅ partly cloudy", 3: "☁️ overcast",
    45: "🌫️ fog", 48: "🌫️ rime fog", 51: "🌦️ light drizzle", 53: "🌦️ drizzle",
    55: "🌧️ heavy drizzle", 61: "🌧️ light rain", 63: "🌧️ rain", 65: "🌧️ heavy rain",
    71: "🌨️ light snow", 73: "🌨️ snow", 75: "❄️ heavy snow", 80: "🌦️ showers",
    81: "🌦️ showers", 82: "⛈️ violent showers", 95: "⛈️ thunderstorm",
    96: "⛈️ storm+hail", 99: "⛈️ storm+hail",
}


def _get(url, retries=4):
    """GET JSON with retries — Open-Meteo rate-limits bursts; never silently lose a sample."""
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


# ---- Weather signals ------------------------------------------------------
def forecast(lat, lon):
    return _get(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,windspeed_10m_max,sunrise,sunset"
        "&timezone=auto&forecast_days=16"
    )["daily"]


def climatology(lat, lon):
    """Typical trip-window conditions, averaged over recent years.

    ONE ranged request per venue (not one per year) then filter to the trip
    window client-side — deterministic and avoids the rate-limit/silent-drop
    that made per-year requests non-reproducible.
    """
    d = _get(
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={CLIMO_YEARS[0]}-07-15&end_date={CLIMO_YEARS[-1]}-07-31"
        "&daily=temperature_2m_max,precipitation_sum&timezone=auto"
    )["daily"]
    tmaxs, precs, rain_days, total = [], [], 0, 0
    for t, tx, pr in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"]):
        dd = date.fromisoformat(t)
        if not (dd.month == TARGET_START.month and TARGET_START.day <= dd.day <= TARGET_END.day):
            continue
        if tx is None:
            continue
        total += 1
        tmaxs.append(tx)
        precs.append(pr or 0)
        if (pr or 0) >= 3:              # climbing-meaningful rain, not ERA5 trace/drizzle
            rain_days += 1
    if not total:
        return None
    return {
        "tmax": round(sum(tmaxs) / len(tmaxs)),
        "precip": round(sum(precs) / len(precs), 1),
        "rain_pct": round(100 * rain_days / total),
        "days": total,
    }


def day_score(code, mm, prob):
    s = 100.0 - (prob or 0) * 0.8 - (mm or 0) * 6
    if code is not None and code >= 61:
        s = min(s, 25)
    if code in (95, 96, 99):
        s = min(s, 15)
    return max(0.0, min(100.0, s))


def climo_score(c):
    """Drier typical July -> higher. Mild penalty for cold/hot extremes."""
    s = 100 - c["rain_pct"] * 0.9
    s -= max(0, 10 - c["tmax"]) * 1.5      # too cold
    s -= max(0, c["tmax"] - 32) * 1.5      # too hot
    return max(0, min(100, round(s)))


def evaluate(v):
    res = {"venue": v, "ok": True}
    # climatology (always useful, even months out)
    try:
        res["climo"] = climatology(v["lat"], v["lon"])
    except Exception:
        res["climo"] = None
    # live forecast
    try:
        d = forecast(v["lat"], v["lon"])
    except Exception as e:
        res["fc"] = None
        if not res.get("climo"):
            return {"venue": v, "ok": False, "error": str(e), "score": -1}
    else:
        days = d["time"]
        valid = [i for i in range(len(days)) if d["temperature_2m_max"][i] is not None]
        in_win = [i for i in valid if TARGET_START <= date.fromisoformat(days[i]) <= TARGET_END]
        idx = in_win or ([valid[-1]] if valid else [])
        if idx:
            scores = [day_score(d["weathercode"][i], d["precipitation_sum"][i],
                                d["precipitation_probability_max"][i]) for i in idx]
            codes = [d["weathercode"][i] for i in idx]
            res["fc"] = {
                "score": round(sum(scores) / len(scores)),
                "tmax": round(sum(d["temperature_2m_max"][i] for i in idx) / len(idx)),
                "rain_prob": max((d["precipitation_probability_max"][i] or 0) for i in idx),
                "sky": WMO.get(max(set(codes), key=codes.count), "?"),
                "in_window": bool(in_win),
                "used": (f"{days[idx[0]]}…{days[idx[-1]]}" if in_win else days[idx[0]]),
                "horizon": days[-1],
            }
        else:
            res["fc"] = None

    # ranking score + basis
    fc = res.get("fc")
    if fc and fc["in_window"]:
        res["score"], res["basis"] = fc["score"], "live forecast (trip window)"
    elif res.get("climo"):
        res["score"], res["basis"] = climo_score(res["climo"]), "typical July (climatology)"
    elif fc:
        res["score"], res["basis"] = fc["score"], "nearest-day proxy"
    else:
        res["score"], res["basis"] = -1, "no data"
    return res


def prio_num(v):
    for ch in v.get("priority", "9"):
        if ch.isdigit():
            return int(ch)
    return 9


def rank(results):
    ok = [r for r in results if r.get("ok") and r["score"] >= 0]
    ok.sort(key=lambda r: (-r["score"], prio_num(r["venue"])))
    return ok + [r for r in results if r not in ok]


def cheapest_flight():
    priced = [(d["cheapest_gbp"], cid) for cid, d in FLIGHTS_DATA["combos"].items()
              if d.get("cheapest_gbp") is not None]
    return min(priced) if priced else None


# ---- HTML -----------------------------------------------------------------
def score_color(s):
    if s < 0:
        return "#9aa4b2"
    if s >= 70:
        return "#16a34a"
    if s >= 45:
        return "#d97706"
    return "#dc2626"


def climo_cell(c):
    if not c:
        return "<span class='dim'>—</span>"
    return f"{c['tmax']}°C · <b>{c['rain_pct']}%</b> wet days"


def fc_cell(fc):
    # Only show the live forecast when it actually covers the trip window — a
    # single day 16 days out is not meaningful, so don't display it as a number.
    if not fc or not fc.get("in_window"):
        return "<span class='dim'>from ~8 Jul</span>"
    return f"{fc['sky']} {fc['tmax']}°C · {fc['rain_prob']}% rain"


def build_html(ranked, now, banner):
    rows = []
    for n, r in enumerate(ranked, 1):
        v = r["venue"]
        if not r.get("ok") or r["score"] < 0:
            rows.append(f"<tr><td>{n}</td><td><b>{v['name']}</b></td>"
                        f"<td colspan='4' class='dim'>no data</td></tr>")
            continue
        col = score_color(r["score"])
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, f"{n}")
        rows.append(
            f"<tr><td class='rank'>{medal}</td>"
            f"<td><div class='vname'><a class='vlink' href='{maps_url(v)}' target='_blank' rel='noopener'>{v['name']} 🗺️</a></div>"
            f"<div class='vsub'>{v['country']} · {v.get('style','')}</div></td>"
            f"<td><span class='pill' style='background:{col}'>{r['score']}</span></td>"
            f"<td class='clim'>{climo_cell(r.get('climo'))}</td>"
            f"<td>{fc_cell(r.get('fc'))}</td>"
            f"<td class='vsub'>{v.get('hub','')}</td></tr>"
        )
    table = "\n".join(rows)

    top = ranked[0] if ranked and ranked[0].get("ok") and ranked[0]["score"] >= 0 else None
    if top:
        tv = top["venue"]
        top_html = (
            f"<div class='hero'><div class='hero-tag'>📍 Best option right now</div>"
            f"<div class='hero-name'>{tv['name']} <span class='hero-flag'>{tv['country']}</span></div>"
            f"<div class='hero-why'>{tv.get('why','')}</div>"
            f"<div class='hero-stats'>"
            f"<span class='stat'><span class='snum' style='color:{score_color(top['score'])}'>{top['score']}</span><span class='slab'>score /100</span></span>"
            f"<span class='stat'><span class='snum'>{(top.get('climo') or {}).get('tmax','–')}°</span><span class='slab'>typical July high</span></span>"
            f"<span class='stat'><span class='snum'>{(top.get('climo') or {}).get('rain_pct','–')}%</span><span class='slab'>wet days (July)</span></span>"
            f"</div><div class='hero-basis'>Ranked on: {top['basis']}</div></div>"
        )
    else:
        top_html = "<div class='hero'><div class='hero-why'>No weather data available.</div></div>"

    cf = cheapest_flight()

    def combo_dates(cid):
        c = next((x for x in FLIGHTS_CFG["combos"] if x["id"] == cid), None)
        return f"{c['out'][5:]}→{c['back'][5:]} ({c['nights']}n)" if c else cid

    def flink(d):
        url = d.get("book_url") or d.get("view_url")
        return f"<a href='{url}' target='_blank' rel='noopener'>view / book ↗</a>" if url else "<span class='dim'>—</span>"

    frows = "".join(
        f"<tr><td><b>{c['out'][5:]}→{c['back'][5:]}</b></td><td>{c['nights']} nights</td>"
        f"<td>{('£'+str(FLIGHTS_DATA['combos'][c['id']]['cheapest_gbp'])) if FLIGHTS_DATA['combos'][c['id']].get('cheapest_gbp') is not None else '<span class=dim>—</span>'}</td>"
        f"<td class='vsub'>{FLIGHTS_DATA['combos'][c['id']].get('airline') or ''} {FLIGHTS_DATA['combos'][c['id']].get('stops') or ''}</td>"
        f"<td>{flink(FLIGHTS_DATA['combos'][c['id']])}</td></tr>"
        for c in FLIGHTS_CFG["combos"]
    )
    checked = FLIGHTS_DATA.get("checked_at") or "not yet checked"
    cheap_line = (f"Cheapest: <b>£{cf[0]} return</b> · {combo_dates(cf[1])} · {checked}" if cf
                  else "Indicative <b>~£80–120</b> return (Ryanair/easyJet) — live check nearer the date")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Climbing Trip Planner — Michel &amp; Dan · ~24 Jul 2026</title>
<style>
:root{{
  --bg:#eef1f6; --card:#ffffff; --ink:#1f2733; --dim:#7b8694; --line:#e6eaf0;
  --accent:#2563eb; --shadow:0 1px 3px rgba(16,24,40,.08),0 1px 2px rgba(16,24,40,.04);
}}
@media(prefers-color-scheme:dark){{
  :root{{--bg:#0b0f17;--card:#141a24;--ink:#e7edf5;--dim:#8b97a7;--line:#222c3a;
  --accent:#5b9dff;--shadow:0 1px 3px rgba(0,0,0,.5);}}
}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  padding:24px 16px;}}
.wrap{{max-width:820px;margin:0 auto}}
header{{margin-bottom:18px}}
h1{{font-size:23px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}}
.lead{{color:var(--dim);font-size:14px;margin:0}}
.lead b{{color:var(--ink)}}
.banner{{margin:16px 0;padding:12px 15px;border-radius:12px;font-size:13.5px;line-height:1.45;
  background:#fff7e6;border:1px solid #f3d18a;color:#7a5a12;}}
@media(prefers-color-scheme:dark){{.banner{{background:#241d0e;border-color:#5c4a1e;color:#e7cf94}}}}
.banner.ok{{background:#e9f9ef;border-color:#a6e3bd;color:#176436}}
@media(prefers-color-scheme:dark){{.banner.ok{{background:#0f2418;border-color:#235c39;color:#86e0a6}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--shadow);padding:18px 20px;margin:0 0 18px}}
.card h2{{font-size:15px;text-transform:uppercase;letter-spacing:.05em;color:var(--dim);
  margin:0 0 14px;font-weight:700}}
.hero{{background:linear-gradient(135deg,#2563eb,#1e40af);color:#fff;border:none}}
@media(prefers-color-scheme:dark){{.hero{{background:linear-gradient(135deg,#1e3a8a,#0f2456)}}}}
.hero-tag{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;opacity:.85}}
.hero-name{{font-size:26px;font-weight:800;margin:4px 0 6px;letter-spacing:-.01em}}
.hero-flag{{font-size:14px;font-weight:600;opacity:.85;background:rgba(255,255,255,.16);
  padding:2px 9px;border-radius:20px;vertical-align:middle;margin-left:6px}}
.hero-why{{font-size:14.5px;line-height:1.5;opacity:.95;margin-bottom:16px}}
.hero-stats{{display:flex;gap:26px;flex-wrap:wrap}}
.stat{{display:flex;flex-direction:column}}
.snum{{font-size:24px;font-weight:800;line-height:1}}
.hero .snum{{color:#fff}}
.slab{{font-size:11.5px;opacity:.85;margin-top:3px;text-transform:uppercase;letter-spacing:.03em}}
.hero-basis{{margin-top:14px;font-size:12px;opacity:.8}}
table{{width:100%;border-collapse:separate;border-spacing:0}}
th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim);
  font-weight:700;padding:0 10px 10px;border-bottom:2px solid var(--line)}}
td{{padding:13px 10px;border-bottom:1px solid var(--line);vertical-align:middle;font-size:14px}}
tr:last-child td{{border-bottom:none}}
tbody tr:hover{{background:rgba(37,99,235,.04)}}
.rank{{font-size:18px;font-weight:800;width:40px;text-align:center}}
.vname{{font-weight:700;font-size:15px}}
.vlink{{color:inherit;text-decoration:none}}
.vlink:hover{{color:var(--accent);text-decoration:underline}}
.links{{margin:0 0 6px;font-size:13.5px}}
.links a{{color:var(--accent);text-decoration:none;font-weight:600}}
.links a:hover{{text-decoration:underline}}
.vsub{{color:var(--dim);font-size:12.5px;margin-top:2px}}
.clim{{white-space:nowrap}}
.pill{{display:inline-block;min-width:42px;text-align:center;color:#fff;font-weight:800;
  font-size:15px;padding:5px 10px;border-radius:9px}}
.dim{{color:var(--dim)}}
.legend{{color:var(--dim);font-size:12.5px;margin:14px 2px 0}}
.fcard p{{margin:0 0 12px;color:var(--dim);font-size:13.5px}}
footer{{color:var(--dim);font-size:12px;text-align:center;margin-top:6px;line-height:1.6}}
footer a{{color:var(--accent);text-decoration:none}}
@media(max-width:560px){{
  .vsub{{display:none}} td,th{{padding-left:6px;padding-right:6px}}
  .hero-stats{{gap:18px}}
}}
</style></head><body><div class="wrap">
<header>
<h1>🧗 Climbing Trip Planner — where should Michel &amp; Dan go?</h1>
<p class="lead">Multi-pitch trip <b>Fri 24 – Tue 28 Jul 2026</b> · ranked best-first ·
updated {now:%a %d %b %Y, %H:%M UTC}</p>
<div class="links"><a href="{SITE_URL}" target="_blank" rel="noopener">🧗 multi-pitch.com</a> ·
<a href="{SHEET_URL}" target="_blank" rel="noopener">📋 venue spreadsheet</a> ·
<span class="dim">🗺️ tap a venue for Google Maps</span></div>
</header>
<div class="banner {banner[0]}">{banner[1]}</div>
{top_html}
<div class="card">
<h2>🏔️ Venue ranking</h2>
<table><thead>
<tr><th>#</th><th>Venue</th><th>Score</th><th>Typical July</th><th>Live forecast</th><th>Access</th></tr>
</thead><tbody>
{table}
</tbody></table>
<p class="legend"><b>Score</b> 0–100 (higher = drier/better). <b>Typical July</b> = avg of {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]} (free historical data — available now). <b>Live forecast</b> fills in within ~16 days of the trip.</p>
</div>
<div class="card fcard">
<h2>✈️ Flights — London ⇄ Belfast</h2>
<p>{FLIGHTS_CFG['route']['passengers']} passenger · 3–4 nights · target ≤ £{FLIGHTS_CFG['target_price_gbp']} · {cheap_line}</p>
<table><thead><tr><th>Dates</th><th>Length</th><th>Price</th><th>Airline</th><th>Link</th></tr></thead>
<tbody>{frows}</tbody></table>
</div>
<footer>Weather: Open-Meteo forecast + historical (free). Flights: live Google Flights via SerpApi, updated daily.<br>
<a href="{SITE_URL}" target="_blank" rel="noopener">multi-pitch.com</a> ·
<a href="{SHEET_URL}" target="_blank" rel="noopener">venue spreadsheet</a> ·
<a href="{REPO_URL}" target="_blank" rel="noopener">source &amp; daily history</a></footer>
</div></body></html>
"""


def build_md(ranked, now, banner):
    lines = [f"# {TRIP_NAME}", "",
             f"**Updated:** {now:%Y-%m-%d %H:%M UTC} · ranked best-first.", "",
             f"> {banner[1]}", "", "## 🏆 Ranking", "",
             "| # | Venue | Score | Typical July | Live forecast | Access |",
             "|---|---|---|---|---|---|"]
    for n, r in enumerate(ranked, 1):
        v = r["venue"]
        if not r.get("ok") or r["score"] < 0:
            lines.append(f"| {n} | {v['name']} | – | – | – | {v.get('hub','')} |")
            continue
        c = r.get("climo")
        cstr = f"{c['tmax']}°C, {c['rain_pct']}% wet days" if c else "–"
        fc = r.get("fc")
        fstr = (f"{fc['tmax']}°C, {fc['rain_prob']}% rain" + ("" if fc["in_window"] else " (proxy)")) if fc else "not in range"
        lines.append(f"| {n} | {v['name']} | {r['score']} | {cstr} | {fstr} | {v.get('hub','')} |")
    cf = cheapest_flight()
    cf_dates = next((f"{c['out']}→{c['back']}" for c in FLIGHTS_CFG["combos"] if cf and c["id"] == cf[1]), "")
    lines += ["", "## ✈️ Flights (London ⇄ Belfast, 3–4 nights)", "",
              (f"**Cheapest: £{cf[0]} return** ({cf_dates})" if cf else "Indicative ~£80–120 return; live check nearer the date."),
              "", "| Dates | Nights | Price | Airline | Link |", "|---|---|---|---|---|"]
    for c in FLIGHTS_CFG["combos"]:
        d = FLIGHTS_DATA["combos"][c["id"]]
        p = f"£{d['cheapest_gbp']}" if d.get("cheapest_gbp") is not None else "—"
        url = d.get("book_url") or d.get("view_url")
        link = f"[view / book]({url})" if url else "—"
        lines.append(f"| {c['out']}→{c['back']} | {c['nights']} | {p} | {d.get('airline','')} | {link} |")
    lines += ["", f"**Links:** [multi-pitch.com]({SITE_URL}) · [venue spreadsheet]({SHEET_URL}) · "
              "[live dashboard](https://uncinimichel.github.io/climbing-agent/) · "
              "venue rows on the dashboard link to Google Maps."]
    return "\n".join(lines) + "\n"


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    results = [evaluate(v) for v in VENUES]
    ranked = rank(results)

    in_window = any(r.get("fc") and r["fc"].get("in_window") for r in ranked)
    horizon = next((r["fc"]["horizon"] for r in ranked if r.get("fc")), "?")
    if in_window:
        banner = ("ok", f"✅ Trip dates are within the 16-day forecast — venues ranked on the "
                        f"<b>actual trip-window forecast</b>.")
    else:
        days_out = (TARGET_START - now.date()).days
        banner = ("", f"📅 Trip is {days_out} days out — beyond the 16-day live forecast "
                      f"(reaches {horizon}). Ranked on <b>typical late-July weather</b> "
                      f"(historical averages, {CLIMO_YEARS[0]}–{CLIMO_YEARS[-1]}). The live "
                      f"forecast column fills in automatically from ~8 July.")

    INDEX.write_text(build_html(ranked, now, banner))
    md = build_md(ranked, now, banner)
    DAILY.write_text(md)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(md)
    print(f"Wrote index.html, daily-report.md, history/{today}.md")
    print("Ranking:", " > ".join(r["venue"]["name"] for r in ranked if r.get("ok") and r["score"] >= 0))


if __name__ == "__main__":
    main()

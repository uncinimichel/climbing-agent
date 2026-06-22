#!/usr/bin/env python3
"""Build the trip dashboard: free Open-Meteo weather for every candidate venue
plus the latest flight prices, written to daily-report.md and a permanent dated
history snapshot.

No dependencies, no API key — standard library only, so it runs on a bare
GitHub Actions runner.

Config / data files (all in the trip folder):
  venues.json         candidate venues + target window  -> drives weather queries
  flights.json        flight route + date combos (rules) -> what to price
  flights-latest.json latest prices per combo            -> filled on demand / by API
"""
import json
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "history"
DAILY = ROOT / "daily-report.md"

_cfg = json.loads((ROOT / "venues.json").read_text())
TRIP_NAME = _cfg["trip"]
TARGET_START = date.fromisoformat(_cfg["target_window"]["start"])
TARGET_END = date.fromisoformat(_cfg["target_window"]["end"])
VENUES = _cfg["venues"]

FLIGHTS_CFG = json.loads((ROOT / "flights.json").read_text())
FLIGHTS_DATA = json.loads((ROOT / "flights-latest.json").read_text())

WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent showers", 95: "thunderstorm",
    96: "thunderstorm+hail", 99: "thunderstorm+hail",
}


# --- Weather ---------------------------------------------------------------
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


def score_day(code, precip_mm, precip_prob):
    if code is not None and code >= 61:
        return "❌ wet"
    if (precip_prob or 0) >= 60 or (precip_mm or 0) >= 5:
        return "⚠️ risky"
    if (precip_prob or 0) <= 25 and (precip_mm or 0) < 1:
        return "✅ dry"
    return "➖ mixed"


def venue_block(v):
    try:
        data = fetch(v["lat"], v["lon"])
    except Exception as e:
        return f"### {v['name']}  _(priority {v['priority']})_\n\n_fetch failed: {e}_\n", []

    d = data["daily"]
    days = d["time"]
    lines = [f"### {v['name']}  _(priority {v['priority']})_", ""]
    in_window = []
    table = ["| Date | Sky | Max°C | Min°C | Rain mm | Rain % | Wind km/h | Verdict |",
             "|---|---|---|---|---|---|---|---|"]
    for i, day in enumerate(days):
        dt = date.fromisoformat(day)
        if not (TARGET_START <= dt <= TARGET_END):
            continue
        code = d["weathercode"][i]
        verdict = score_day(code, d["precipitation_sum"][i], d["precipitation_probability_max"][i])
        in_window.append(verdict)
        table.append(
            f"| {day} | {WMO.get(code, code)} | {d['temperature_2m_max'][i]:.0f} | "
            f"{d['temperature_2m_min'][i]:.0f} | {d['precipitation_sum'][i]:.1f} | "
            f"{d['precipitation_probability_max'][i] or 0} | {d['windspeed_10m_max'][i]:.0f} | {verdict} |"
        )
    if in_window:
        lines += table
        dry = sum(1 for x in in_window if x.startswith("✅"))
        lines += ["", f"**Window summary:** {dry}/{len(in_window)} clearly-dry days in {TARGET_START}…{TARGET_END}."]
    else:
        last = days[-1] if days else "?"
        lines.append(f"_Target window {TARGET_START}…{TARGET_END} is beyond the 16-day forecast horizon "
                     f"(forecast currently reaches {last}). Check back closer to the date._")
    lines.append("")
    return "\n".join(lines), in_window


def recommendation(summaries):
    scored = [(sum(1 for x in v if x.startswith("✅")), len(v), name)
              for name, v in summaries.items() if v]
    if not scored:
        return ("⏳ Target window not yet in forecast range — no go/no-go call possible. "
                "Forecasts reach 16 days out; meaningful from ~8 July.")
    scored.sort(reverse=True)
    best_dry, total, best = scored[0]
    if best_dry == 0:
        return f"⚠️ No venue shows clearly-dry days yet. Best so far: **{best}**. Keep watching."
    return (f"📍 Leaning **{best}** — {best_dry}/{total} dry days in the window. "
            "(NI preferred when dry; switch to a backup only if NI is washed out.)")


# --- Flights ---------------------------------------------------------------
def flights_block():
    r = FLIGHTS_CFG["route"]
    target = FLIGHTS_CFG.get("target_price_gbp")
    data = FLIGHTS_DATA["combos"]
    checked = FLIGHTS_DATA.get("checked_at") or "never"
    cur = FLIGHTS_DATA.get("currency", "GBP")

    lines = [
        f"**Route:** {r['origin_city']} ({'/'.join(r['origin_airports'])}) ⇄ "
        f"{r['dest_city']} ({'/'.join(r['dest_airports'])}) · {r['passengers']} pax · "
        f"target ≤ £{target} return.",
        f"**Prices last checked:** {checked}. _{FLIGHTS_CFG['data_source']}_",
        "",
        "| Combo | Out | Back | Nights | Cheapest | Airline | Airports | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    priced = []
    for c in FLIGHTS_CFG["combos"]:
        d = data.get(c["id"], {})
        price = d.get("cheapest_gbp")
        price_s = f"£{price}" if price is not None else "—"
        if price is not None:
            priced.append((price, c["id"]))
        ap = "→".join(x for x in [d.get("out_airport"), d.get("back_airport")] if x) or "—"
        lines.append(
            f"| {c['id']} | {c['out']} | {c['back']} | {c['nights']} | {price_s} | "
            f"{d.get('airline') or '—'} | {ap} | {d.get('notes') or ''} |"
        )
    lines.append("")
    if priced:
        priced.sort()
        best_price, best_id = priced[0]
        flag = " ✅ under target" if target and best_price <= target else ""
        lines.append(f"**Cheapest so far:** {best_id} at £{best_price} ({cur}){flag}.")
    else:
        lines.append("_No prices logged yet — ask Claude to check, or wire a flight API._")
    lines.append("")
    return "\n".join(lines)


# --- Assemble --------------------------------------------------------------
def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    blocks, summaries = [], {}
    for v in VENUES:
        block, summ = venue_block(v)
        blocks.append(block)
        summaries[v["name"]] = summ
    weather_md = "\n".join(blocks)
    rec = recommendation(summaries)
    flights_md = flights_block()

    report = (
        f"# {TRIP_NAME}\n\n"
        f"**Last update:** {now:%Y-%m-%d %H:%M UTC} · **Target window:** {TARGET_START}…{TARGET_END}\n\n"
        f"## 🧭 Recommendation\n\n{rec}\n\n"
        f"## ✈️ Flights\n\n{flights_md}\n"
        f"## 🌦️ Weather by venue\n\n{weather_md}\n"
    )
    DAILY.write_text(report)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(
        f"# Snapshot {today}\n\n## Recommendation\n\n{rec}\n\n"
        f"## Flights\n\n{flights_md}\n## Weather\n\n{weather_md}\n"
    )
    print(f"Wrote daily-report.md and history/{today}.md")
    print(rec)


if __name__ == "__main__":
    main()

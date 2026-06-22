#!/usr/bin/env python3
"""Fetch free Open-Meteo forecasts for the trip's candidate venues and write
both a permanent dated history file and the latest daily-report.md.

No dependencies, no API key — uses the standard library only so it runs on a
bare GitHub Actions runner. Flights are NOT fetched here (no reliable free
flight API); those are filled in manually and preserved across runs.
"""
import json
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

# --- Config: the candidate venues live in venues.json (single source of truth) ---
ROOT = Path(__file__).resolve().parent.parent          # trip-ni-july-2026/
HISTORY = ROOT / "history"
DAILY = ROOT / "daily-report.md"
VENUES_FILE = ROOT / "venues.json"

_cfg = json.loads(VENUES_FILE.read_text())
TRIP_NAME = _cfg["trip"]
TARGET_START = date.fromisoformat(_cfg["target_window"]["start"])
TARGET_END = date.fromisoformat(_cfg["target_window"]["end"])
VENUES = _cfg["venues"]

WMO = {  # Open-Meteo weather codes -> short label
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent showers", 95: "thunderstorm",
    96: "thunderstorm+hail", 99: "thunderstorm+hail",
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


def score_day(code, precip_mm, precip_prob):
    """Crude climbability flag for a single day."""
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
    except Exception as e:  # network/API hiccup — don't kill the whole run
        return f"### {v['name']}  _(priority {v['priority']})_\n\n_fetch failed: {e}_\n", None

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
        dry = sum(1 for v in in_window if v.startswith("✅"))
        lines.append("")
        lines.append(f"**Window summary:** {dry}/{len(in_window)} clearly-dry days in {TARGET_START}…{TARGET_END}.")
    else:
        last = days[-1] if days else "?"
        lines.append(f"_Target window {TARGET_START}…{TARGET_END} is beyond the 16-day forecast "
                     f"horizon (forecast currently reaches {last}). Check back closer to the date._")
    lines.append("")
    summary = in_window
    return "\n".join(lines), summary


def recommendation(summaries):
    """summaries: {venue_name: [verdict,...]}"""
    scored = []
    for name, verds in summaries.items():
        if not verds:
            continue
        dry = sum(1 for v in verds if v.startswith("✅"))
        scored.append((dry, len(verds), name))
    if not scored:
        return ("⏳ Target window not yet in forecast range — no go/no-go call possible. "
                "Forecasts reach 16 days out; meaningful from ~8 July.")
    scored.sort(reverse=True)
    best_dry, total, best = scored[0]
    if best_dry == 0:
        return f"⚠️ No venue shows clearly-dry days yet. Best so far: **{best}**. Keep watching."
    return (f"📍 Leaning **{best}** — {best_dry}/{total} dry days in the window. "
            "(Primary NI preferred when dry; switch to backup only if NI is washed out.)")


def carry_flight_section():
    """Preserve the manually-maintained flights block across automated runs."""
    if DAILY.exists():
        text = DAILY.read_text()
        marker = "## ✈️ Flights"
        if marker in text:
            block = text[text.index(marker):]
            # cut at next top-level section if any
            nxt = block.find("\n## ", len(marker))
            return block[:nxt].rstrip() if nxt != -1 else block.rstrip()
    return ("## ✈️ Flights\n\n_No flight prices logged yet. Claude updates this on a session "
            "(London ⇄ Belfast for Michel). No free flight API, so this is checked on demand._")


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    blocks, summaries = [], {}
    for v in VENUES:
        block, summ = venue_block(v)
        blocks.append(block)
        if summ is not None:
            summaries[v["name"]] = summ

    rec = recommendation(summaries)
    weather_md = "\n".join(blocks)

    header = (
        f"# {TRIP_NAME}\n\n"
        f"**Last weather update:** {now:%Y-%m-%d %H:%M UTC} · "
        f"**Target window:** {TARGET_START}…{TARGET_END}\n\n"
        f"## 🧭 Recommendation\n\n{rec}\n\n"
        f"## 🌦️ Weather by venue\n\n{weather_md}\n"
    )

    flights = carry_flight_section()
    report = header + "\n" + flights + "\n"

    DAILY.write_text(report)
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{today}.md").write_text(
        f"# Snapshot {today}\n\n## Recommendation\n\n{rec}\n\n## Weather\n\n{weather_md}\n"
    )
    print(f"Wrote daily-report.md and history/{today}.md")
    print(rec)


if __name__ == "__main__":
    sys.exit(main())

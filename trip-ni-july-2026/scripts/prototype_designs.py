#!/usr/bin/env python3
"""Throwaway: render alternative layouts (card / accordion) from the live data so
we can compare them before changing the real report. Reuses cached flight prices
(no SerpApi spend) and free weather. Writes prototypes/*.html."""
import importlib.util as iu
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = iu.spec_from_file_location("rep", ROOT / "scripts" / "update_report.py")
m = iu.module_from_spec(spec)
spec.loader.exec_module(m)

m.MP_CLIMBS = m.load_mp_climbs()
results = [m.evaluate(v) for v in m.VENUES]
ranked = m.rank(results)
cache = json.loads((ROOT / "flights-latest.json").read_text()).get("venues", {})
for r in ranked:
    if r.get("ok"):
        r["flights"] = cache.get(r["venue"]["name"])

OUT = ROOT.parent / "prototypes"
OUT.mkdir(exist_ok=True)

CSS = """
:root{--bg:#eef1f6;--card:#fff;--ink:#1f2733;--dim:#7b8694;--line:#e6eaf0;--accent:#2563eb;--shadow:0 1px 3px rgba(16,24,40,.08),0 2px 8px rgba(16,24,40,.05)}
@media(prefers-color-scheme:dark){:root{--bg:#0b0f17;--card:#141a24;--ink:#e7edf5;--dim:#8b97a7;--line:#222c3a;--accent:#5b9dff;--shadow:0 1px 3px rgba(0,0,0,.5)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:20px 14px}
.wrap{max-width:760px;margin:0 auto}h1{font-size:21px;margin:0 0 4px}.lead{color:var(--dim);font-size:13.5px;margin:0 0 16px}
.vcard{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);padding:16px;margin:0 0 14px}
.vcard.best{border:2px solid var(--accent)}
.vhead{display:flex;align-items:center;gap:10px}
.rank{font-size:20px;font-weight:800;min-width:30px}
.vname{font-weight:800;font-size:17px;flex:1}.vname a{color:inherit;text-decoration:none}
.vname small{display:block;font-weight:500;font-size:12px;color:var(--dim);margin-top:1px}
.score{margin-left:auto;color:#fff;font-weight:800;font-size:16px;padding:5px 11px;border-radius:10px}
.tag{display:inline-block;font-size:11px;font-weight:700;color:var(--accent);background:rgba(37,99,235,.1);padding:2px 8px;border-radius:20px;margin-bottom:8px}
.wxrow{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0}
.wxrow svg{flex:1;min-width:240px;max-width:340px}
.wxnum{font-size:14px;white-space:nowrap}
.flights{display:flex;gap:12px;flex-wrap:wrap;margin-top:6px}
.fcol{flex:1;min-width:210px;background:rgba(127,127,127,.05);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.fcol h4{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim)}
.fdates{font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px}
.opt{margin-bottom:3px;font-size:13px}.opt .t{font-variant-numeric:tabular-nums}
.vsub{color:var(--dim);font-size:12px}
.flink{color:var(--accent);text-decoration:none;font-weight:600;font-size:12.5px}
.srcs{margin-top:10px;font-size:11.5px;border-top:1px dashed var(--line);padding-top:8px}
.src{color:var(--accent);text-decoration:none;font-weight:600}.src.dim{color:var(--dim);font-weight:400}
summary{cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}
.srow{display:flex;align-items:center;gap:10px}
.spark{width:84px;height:30px;flex-shrink:0}
.cheap{font-size:12.5px;color:var(--dim);margin-left:auto;text-align:right;white-space:nowrap}
"""


def score_col(s):
    return m.score_color(s)


def cheapest(f):
    if not f or f.get("mode") != "fly":
        return f.get("mode", "?") if f else "—"
    o = (f.get("options") or [])
    return f"£{o[0]['price']}" if o else "see link"


def flights_block(r):
    fl = r.get("flights") or {}
    out = "<div class='flights'>"
    for who, lbl in (("michel", "✈️ Michel · London"), ("dan", "✈️ Dan · Belfast/Dublin")):
        out += f"<div class='fcol'><h4>{lbl}</h4>{m.flight_html(fl.get(who))}</div>"
    return out + "</div>"


def weather_block(r):
    c = r.get("climo") or {}
    num = (f"<span class='wxnum'>{c.get('tmax','?')}°C · <b>{c.get('rain_pct','?')}%</b> wet · 💨{c.get('wind','?')}</span>"
           if c else "<span class='vsub'>—</span>")
    g = m.weather_mini_svg(c.get("series")) if c else ""
    return (f"<div class='wxrow'>{g}<span>{num}<br>"
            f"<a class='flink' href='{m.weather_url(r['venue'])}' target='_blank'>full forecast ↗</a></span></div>")


# ---------- Design A: cards ----------
def design_a():
    cards = []
    for n, r in enumerate(ranked, 1):
        if not r.get("ok") or r["score"] < 0:
            continue
        v = r["venue"]
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, f"{n}")
        cards.append(
            f"<div class='vcard {'best' if n==1 else ''}'>"
            + (f"<span class='tag'>📍 best option right now</span>" if n == 1 else "")
            + f"<div class='vhead'><span class='rank'>{medal}</span>"
            f"<span class='vname'>{m.flag(v['country'])} <a href='{m.maps_url(v)}' target='_blank'>{v['name']} 🗺️</a>"
            f"<small>{v['country']} · {v.get('style','')}</small></span>"
            f"<span class='score' style='background:{score_col(r['score'])}'>{r['score']}</span></div>"
            + weather_block(r) + flights_block(r)
            + f"<div class='srcs'>{m.source_links(v)}</div></div>"
        )
    return page("Design A — venue cards", "".join(cards))


# ---------- Design B: accordion ----------
def design_b():
    rows = []
    for n, r in enumerate(ranked, 1):
        if not r.get("ok") or r["score"] < 0:
            continue
        v = r["venue"]
        c = r.get("climo") or {}
        fl = r.get("flights") or {}
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, f"{n}")
        spark = m.weather_mini_svg(c.get("series"), W=84, H=30) if c.get("series") else ""
        cheap = f"M {cheapest(fl.get('michel'))} · D {cheapest(fl.get('dan'))}"
        rows.append(
            f"<details class='vcard' {'open' if n==1 else ''}><summary><div class='srow'>"
            f"<span class='rank'>{medal}</span>"
            f"<span class='vname'>{m.flag(v['country'])} {v['name']}<small>{v['country']} · {c.get('tmax','?')}°C · {c.get('rain_pct','?')}% wet</small></span>"
            f"<span class='spark'>{spark}</span>"
            f"<span class='score' style='background:{score_col(r['score'])}'>{r['score']}</span>"
            f"</div><div class='cheap'>✈️ {cheap}</div></summary>"
            + weather_block(r) + flights_block(r)
            + f"<div class='srcs'>{m.source_links(v)}</div></details>"
        )
    return page("Design B — ranked accordion (tap to expand)", "".join(rows))


def page(title, body):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title><style>{CSS}</style></head><body><div class=wrap>"
            f"<h1>🧗 {title}</h1><p class=lead>Prototype · {len(ranked)} venues · trip Fri 24–Tue 28 Jul 2026</p>"
            f"{body}</div></body></html>")


(OUT / "design-a-cards.html").write_text(design_a())
(OUT / "design-b-accordion.html").write_text(design_b())
print("wrote prototypes/design-a-cards.html and design-b-accordion.html")

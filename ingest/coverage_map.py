"""Coverage map — one page showing every crag a run found and which source
supplied it.

    python -m ingest map <run-id> [--with <run-id>,<run-id>] [--out FILE]

The question it answers is the one that decides a trip: for this box, what is
documented, by whom, and where are the holes. Sources disagree about names and
positions, so records are clustered into places by an alias table plus name
normalisation, and each place shows a per-source route count. A source column of
dots is a source that has nothing there; a 0 is a source we crawled that yielded
no route list (Compass West, whose routes live inside topo images).

The page carries every route with its properties, searchable, and clicking one
opens its full record on the map. Leaflet over OSM tiles with circleMarker
points — the same idiom as the curation Studio (corpus/tools/curate_ui.html),
so this project has one map, not two. It therefore needs the network: to make
an artifact-publishable copy, the tiles have to be inlined as data URIs and
Leaflet loaded from cdnjs.
"""
from __future__ import annotations

import glob
import html
import json
import math
import re
import unicodedata
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent / "runs"

# Sources spell the same mountain several ways; these fold them onto one place.
# Anything not matched here clusters on its normalised name alone.
ALIAS = [
    (r"\bpuig ?campana\b", "puig campana"),
    (r"\bpenon (de )?ifach\b|\bpenon d ifach\b|\bpenyal d ifac\b", "penon de ifach"),
    (r"\b(sierra (de|del) )?toix\b", "toix"),
    (r"\bponoig\b|\bponotx\b", "ponoig"),
    (r"\bcabec?o d?.?or\b|\bcabezon de oro\b", "cabeco d or"),
    (r"\bpenon del divino\b|\bpenon divino\b", "penon del divino"),
    (r"\bmascarat\b", "mascarat"),
    (r"\bsella\b|\bvalle di sella\b|\bvalle de sella\b", "sella"),
    (r"\bbernia\b|\bserra de bernia\b", "bernia"),
    (r"\bbenicadell\b", "benicadell"),
    (r"\bmorro (del )?falqui\b", "morro falqui"),
    (r"\bpenya roc\b|\bdos hermanos\b", "penya roc"),
    (r"\bolta\b", "olta"),
    (r"\bcastellet\b", "el castellet"),
    (r"\bguadalest\b", "guadalest"),
    (r"\balcalali\b", "alcalali"),
    (r"\bracc?o del corb\b|\braco del corv\b", "raco del corb"),
    (r"\bsierra helada\b|\bserra gelada\b", "serra gelada"),
]

# name shown in the legend, and the licence position that governs publishing it
SOURCE_META = {
    "multilargo": ("multilargo", "CC BY-SA 4.0"),
    "enlavertical": ("enlavertical", "no licence stated — ask first"),
    "camptocamp": ("camptocamp", "CC BY-SA 3.0"),
    "panoramicas360": ("panorámicas360", "all rights reserved"),
    "compasswest": ("Compass West", "no notice — ask first"),
    "mountainproject": ("Mountain Project", "permission held"),
    "multipitch": ("multi-pitch.com", "ours, CC BY-SA 4.0"),
    "ukc": ("UKC", "permission held"),
    "thecrag": ("theCrag", "permission held"),
    "climbook": ("Climbook", "robots open"),
    "falesiait": ("falesia.it", "robots open"),
    "irishwiki": ("wiki.climbing.ie", "wiki"),
    "openbeta": ("OpenBeta", "CC0"),
}

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _key(name: str) -> str:
    n = _norm(name.split("—")[0])
    for pat, canon in ALIAS:
        if re.search(pat, n):
            return canon
    return n


def _load(run_ids: list[str]) -> tuple[list[dict], tuple, str]:
    """Merge runs, newest wins per source. Re-running one source after fixing
    its adapter is the normal way to work here, so a source appearing in two of
    the given runs takes its LAST occurrence rather than being counted twice."""
    by_source: dict[str, list[dict]] = {}
    bbox = None
    for run in run_ids:
        for path in sorted(glob.glob(str(RUNS_DIR / run / "parsed" / "*.json"))):
            d = json.loads(Path(path).read_text())
            bbox = bbox or tuple(d["bbox"])
            by_source[d["source"]] = [c for c in d["crags"]
                                      if c["lat"] is not None and c["lon"] is not None]
    crags = [c for group in by_source.values() for c in group]
    if not crags:
        raise SystemExit(f"no parsed crags with coordinates in run(s) {run_ids}")
    return crags, bbox, run_ids[0]


def _places(crags: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for c in crags:
        groups.setdefault(_key(c["name"]), []).append(c)
    places = []
    for key, members in groups.items():
        by: dict[str, dict] = {}
        for m in members:
            b = by.setdefault(m["source"], {"routes": 0})
            b["routes"] += len(m["routes"])
        grades, seen = [], set()
        for m in members:
            for r in m["routes"]:
                g = (r.get("grade") or {}).get("value")
                if g and g not in seen:
                    seen.add(g)
                    grades.append(g)
        # Every route, with the properties worth deciding a day on. The
        # verbatim `description` prose is deliberately left out: it is the bulk
        # of the payload and it is the third-party text that stays private.
        routes = []
        for m in members:
            for r in m["routes"]:
                g = r.get("grade") or {}
                routes.append({
                    "name": r["name"], "src": m["source"],
                    # enlavertical names sectors "Crag — Sector"; keep the
                    # sector so a route says which face it is actually on
                    "sector": m["name"].split("—", 1)[1].strip() if "—" in m["name"] else None,
                    "grade": g.get("value"), "sys": g.get("system"),
                    "len": r.get("length_m"), "p": r.get("pitches"),
                    "disc": r.get("disciplines") or [], "prot": r.get("protection"),
                    "fa": r.get("fa"), "stars": r.get("stars"), "url": r.get("url"),
                })
        routes.sort(key=lambda r: (r["name"] or "").lower())

        places.append({
            "key": key,
            "name": sorted({m["name"].split("—")[0].strip() for m in members}, key=len)[0],
            "lat": sum(m["lat"] for m in members) / len(members),
            "lon": sum(m["lon"] for m in members) / len(members),
            "routes": sum(len(m["routes"]) for m in members),
            "by": by, "grades": grades[:5], "list": routes,
        })
    places.sort(key=lambda p: -p["routes"])
    return places


def build(run_ids: list[str], out: Path) -> Path:
    crags, bbox, run = _load(run_ids)
    s, w, n, e = bbox
    places = _places(crags)
    sources = sorted({src for p in places for src in p["by"]},
                     key=lambda x: -sum(p["by"].get(x, {}).get("routes", 0) for p in places))
    totals = {x: {"crags": sum(1 for p in places if x in p["by"]),
                  "routes": sum(p["by"].get(x, {}).get("routes", 0) for p in places)}
              for x in sources}
    total_routes = sum(p["routes"] for p in places)

    # Marker data for Leaflet — the same circleMarker treatment the curation
    # Studio (corpus/tools/curate_ui.html) uses over OSM tiles, so there is one
    # map idiom in this project rather than two.
    markers = json.dumps([{"i": i, "name": p["name"], "lat": round(p["lat"], 5),
                           "lon": round(p["lon"], 5), "routes": p["routes"],
                           "by": {k: v["routes"] for k, v in sorted(p["by"].items())},
                           "list": p["list"]}
                          for i, p in enumerate(places)], ensure_ascii=False)

    rows = []
    for i, p in enumerate(places):
        cells = []
        for x in sources:
            if x in p["by"] and p["by"][x]["routes"]:
                cells.append(f'<td class="num">{p["by"][x]["routes"]}</td>')
            elif x in p["by"]:
                cells.append('<td class="num zero" title="crawled, no route list">0</td>')
            else:
                cells.append('<td class="num none">·</td>')
        rows.append(f'<tr data-i="{i}"><th scope="row">{html.escape(p["name"])}'
                    f'<span class="coord">{p["lat"]:.4f}, {p["lon"]:.4f}</span></th>'
                    f'<td class="num tot">{p["routes"]}</td>{"".join(cells)}'
                    f'<td class="grades">{" ".join(html.escape(g) for g in p["grades"])}</td></tr>')

    head = "".join(f'<th scope="col">{html.escape(SOURCE_META.get(x, (x, ""))[0])}</th>'
                   for x in sources)
    legend = "".join(
        f'<li><b>{html.escape(SOURCE_META.get(x, (x, ""))[0])}</b>'
        f'<span class="lic">{html.escape(SOURCE_META.get(x, (x, ""))[1])}</span>'
        f'<span class="cnt">{totals[x]["routes"]} routes · {totals[x]["crags"]} crags</span></li>'
        for x in sources)

    pc = next((p for p in places if p["key"] == "puig campana"), None)
    pc_mp = pc["by"].get("mountainproject", {}).get("routes", 0) if pc else 0

    # The note states only what this run's own data supports: the Mountain
    # Project contrast is the point of the page, but claiming "MP supplies 0"
    # when MP was never crawled would be a lie about a gap in our own run.
    note = ""
    if pc:
        top_src, top_n = max(pc["by"].items(), key=lambda kv: kv[1]["routes"])
        top_name = SOURCE_META.get(top_src, (top_src, ""))[0]
        if "mountainproject" in sources:
            note = (f'<p class="note"><b>The gap that matters.</b> Puig Campana carries '
                    f'<b>{pc["routes"]} routes</b> across these sources, and Mountain Project '
                    f'supplies <b>{pc_mp}</b> of them — {top_name} alone supplies '
                    f'{top_n["routes"]}. The English-language databases are deep on roadside '
                    f'sport and near-empty on the multi-pitch mountains; the Spanish sites '
                    f'carry those.</p>')
        else:
            note = (f'<p class="note"><b>Where the mountain routes actually live.</b> '
                    f'Puig Campana carries <b>{pc["routes"]} routes</b> here, '
                    f'{top_n["routes"]} of them from {top_name} alone. Mountain Project is '
                    f'not in this run — crawled separately at its 60-second delay, it holds '
                    f'exactly one route on this mountain.</p>')

    out.write_text(_TEMPLATE.format(
        w=w, e=e, s=s, n=n, places=len(places), routes=total_routes,
        records=len(crags), nsources=len(sources), run=run, markers=markers,
        legend=legend, head=head, rows="".join(rows), note=note))
    return out


_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Costa Blanca Route Coverage</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500&display=swap">
<style>
:root {{
  --sea:#CFE0E4; --land:#F7F6F2; --ink:#12222A; --muted:#5E7078;
  --line:#C3D2D6; --teal:#0E6068; --ochre:#C08324; --rust:#A2402C;
  --panel:#FFFFFF; --shadow:0 1px 2px rgba(18,34,42,.10);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --sea:#14262C; --land:#0E1619; --ink:#E4EBEC; --muted:#8FA3AA;
    --line:#26383E; --teal:#4FB3AE; --ochre:#D9A144; --rust:#D2705A;
    --panel:#131E22; --shadow:0 1px 2px rgba(0,0,0,.5);
  }}
}}
:root[data-theme="dark"] {{
  --sea:#14262C; --land:#0E1619; --ink:#E4EBEC; --muted:#8FA3AA;
  --line:#26383E; --teal:#4FB3AE; --ochre:#D9A144; --rust:#D2705A;
  --panel:#131E22; --shadow:0 1px 2px rgba(0,0,0,.5);
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--land); color:var(--ink);
  font:400 15px/1.55 "IBM Plex Sans", system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:1120px; margin:0 auto; padding:28px 22px 64px;
  display:flex; flex-direction:column; gap:26px; }}
h1, h2 {{ font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;
  font-weight:700; margin:0; text-wrap:balance; letter-spacing:-.01em; }}
h1 {{ font-size:clamp(26px,4vw,38px); line-height:1.1; }}
h2 {{ font-size:19px; }}
.eyebrow {{ font-family:"IBM Plex Mono",monospace; font-size:11px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--teal); margin:0 0 8px; }}
.lede {{ margin:10px 0 0; max-width:62ch; color:var(--muted); font-size:16px; }}
.lede b {{ color:var(--ink); font-weight:500; }}
.stamp {{ font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--muted);
  border-top:1px solid var(--line); padding-top:9px; margin-top:16px;
  display:flex; flex-wrap:wrap; gap:6px 18px; }}
figure {{ margin:0; }}
#map {{ height:min(68vh,620px); border:1px solid var(--line); border-radius:3px;
  box-shadow:var(--shadow); background:var(--sea); }}
.leaflet-container {{ font:inherit; background:var(--sea); }}
.leaflet-popup-content {{ font:14px/1.5 "IBM Plex Sans",sans-serif; margin:10px 12px; }}
.leaflet-popup-content b {{ font-family:"IBM Plex Sans Condensed",sans-serif; font-size:16px; }}
.leaflet-popup-content dl {{ display:grid; grid-template-columns:auto auto; gap:1px 10px;
  margin:7px 0 0; font-family:"IBM Plex Mono",monospace; font-size:12.5px; }}
.leaflet-popup-content dd {{ margin:0; text-align:right; }}
.leaflet-popup-content .rl {{ margin-top:8px;
  border-top:1px solid var(--line); padding-top:6px; }}
.leaflet-popup-content .rl button {{ display:flex; justify-content:space-between; gap:10px;
  width:100%; text-align:left; background:none; border:0; padding:3px 2px; cursor:pointer;
  font:inherit; font-size:13px; color:var(--ink); border-radius:2px; }}
.leaflet-popup-content .rl button:hover {{ background:color-mix(in srgb, var(--ochre) 22%, transparent); }}
.leaflet-popup-content .rl b {{ font-family:"IBM Plex Mono",monospace; font-weight:500;
  font-size:12px; color:var(--teal); white-space:nowrap; }}
.finder {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:10px; }}
#q {{ flex:1; min-width:240px; font:inherit; padding:9px 12px; color:var(--ink);
  background:var(--panel); border:1px solid var(--line); border-radius:3px; }}
#q::placeholder {{ color:var(--muted); }}
.count {{ margin:0; font-family:"IBM Plex Mono",monospace; font-size:12.5px; color:var(--muted); }}
table.routes tbody tr {{ cursor:pointer; }}
table.routes td {{ white-space:nowrap; }}
/* the route name stays put while the other twelve columns scroll under it */
table.routes td.rname, table.routes th:first-child {{
  position:sticky; left:0; z-index:1; font-weight:500; white-space:nowrap;
  background:var(--panel); box-shadow:1px 0 0 var(--line); }}
table.routes th:first-child {{ z-index:3; }}
table.routes tbody tr:hover td.rname {{ background:var(--panel); }}
th.sortable {{ cursor:pointer; user-select:none; }}
th.sortable:hover {{ color:var(--ink); }}
th.sortable .arrow {{ font-size:9px; margin-left:5px; color:var(--teal); }}
th[aria-sort]:not([aria-sort="none"]) {{ color:var(--ink); }}
table.routes a {{ color:var(--teal); text-decoration:none; }}
.tag {{ font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--muted); }}
.empty {{ padding:18px 12px; color:var(--muted); }}
figcaption {{ margin-top:9px; font-size:12.5px; color:var(--muted); }}
ul.legend {{ list-style:none; margin:0; padding:0; display:grid; gap:1px;
  grid-template-columns:repeat(auto-fit,minmax(228px,1fr)); background:var(--line);
  border:1px solid var(--line); border-radius:3px; overflow:hidden; }}
ul.legend li {{ background:var(--panel); padding:11px 13px; display:grid; gap:2px; }}
ul.legend b {{ font-weight:500; font-size:14.5px; }}
.lic {{ font-size:11.5px; color:var(--muted); }}
.cnt {{ font-family:"IBM Plex Mono",monospace; font-size:12.5px; color:var(--teal); }}
.tablewrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:3px; background:var(--panel); }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th, td {{ padding:7px 10px; text-align:left; border-bottom:1px solid var(--line); }}
thead th {{ font-family:"IBM Plex Sans Condensed",sans-serif; font-size:12.5px; font-weight:600;
  color:var(--muted); text-transform:uppercase; letter-spacing:.05em; white-space:nowrap;
  position:sticky; top:0; background:var(--panel); }}
tbody th {{ font-weight:500; white-space:nowrap; }}
.coord {{ display:block; font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--muted); }}
.num {{ font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums; text-align:right; }}
.tot {{ font-weight:500; }}
td.none {{ color:var(--line); }}
td.zero {{ color:var(--muted); }}
.grades {{ font-family:"IBM Plex Mono",monospace; font-size:12px; color:var(--muted); white-space:nowrap; }}
tbody tr.on {{ background:color-mix(in srgb, var(--ochre) 16%, transparent); }}
tbody tr:hover {{ background:color-mix(in srgb, var(--teal) 8%, transparent); }}
.note {{ border-left:2px solid var(--rust); padding:2px 0 2px 14px; margin:0; max-width:64ch; }}
.note b {{ color:var(--rust); }}
.foot {{ font-size:12.5px; color:var(--muted); max-width:70ch; }}
.foot code {{ font-family:"IBM Plex Mono",monospace; font-size:12px; }}
:focus-visible {{ outline:2px solid var(--teal); outline-offset:2px; }}
@media (prefers-reduced-motion:no-preference) {{ .dot {{ transition:fill-opacity .12s; }} }}
</style>

<div class="wrap">
<header>
  <p class="eyebrow">{s:.2f}–{n:.2f} N · {w:.2f}–{e:.2f} E</p>
  <h1>Every crag our sources know, and who knows it</h1>
  <p class="lede">Adapters crawled live on 7 September 2026. They found
  <b>{places} crags</b> and <b>{routes} routes</b> inside the box. The map sizes
  each crag by how many routes we hold for it; the table shows who supplied them.</p>
  <p class="stamp"><span>run {run}</span><span>{records} crag records → {places} places</span><span>{nsources} sources</span></p>
</header>

<figure>
  <div id="map"></div>
  <figcaption>Circle area tracks routes held. Click a crag for its per-source
  breakdown, or a table row below to find it on the map.</figcaption>
</figure>

<section>
  <h2>Find a route</h2>
  <div class="finder">
    <input id="q" type="search" autocomplete="off"
           placeholder="Search {routes} routes — name, crag, grade, source…"
           aria-label="Search routes by name, crag, grade or source">
    <p id="count" class="count"></p>
  </div>
  <div class="tablewrap"><table class="routes">
    <thead><tr id="rhead"></tr></thead>
    <tbody id="rlist"></tbody>
  </table></div>
  <p id="more" class="foot"></p>
</section>

<section>
  <h2>The sources</h2>
  <ul class="legend">{legend}</ul>
</section>

{note}

<section>
  <h2>Coverage by crag</h2>
  <div class="tablewrap">
  <table>
    <thead><tr><th scope="col">Crag</th><th scope="col">Routes</th>{head}<th scope="col">Grades seen</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</section>

<p class="foot">A dot sits at the mean of every record we hold for that crag, so
sources that place a mountain differently pull it slightly.
<span class="num">·</span> means the source has nothing there;
<span class="num">0</span> means we crawled it and it yielded no route list.
Grades are stored exactly as each source writes them (<code>IV+</code>,
<code>6a+/A0</code>, <code>V (un paso 6a+)</code>) and never converted.</p>
</div>

<script>
const PLACES = {markers};
const map = L.map('map', {{scrollWheelZoom: false}});
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap contributors', maxZoom: 17
}}).addTo(map);
map.fitBounds([[{s}, {w}], [{n}, {e}]]);

const rows = document.querySelectorAll('tbody tr');
const marks = {{}};
PLACES.forEach(p => {{
  const m = L.circleMarker([p.lat, p.lon], {{
    radius: 4 + Math.sqrt(p.routes) * 1.5,
    color: '#C08324', weight: 2, fillColor: '#C08324', fillOpacity: .45
  }}).addTo(map);
  m.on('click', () => {{ select(p.i, false); m.setPopupContent(cragPopup(p)); }});
  // maxHeight lets Leaflet scroll and auto-pan the popup itself — a crag with
  // 97 routes otherwise opens taller than the map and loses its own heading
  m.bindPopup(cragPopup(p), {{maxWidth: 330, minWidth: 260, maxHeight: 240,
                             autoPanPadding: [24, 24]}});
  marks[p.i] = m;
}});

// a declaration, not a const: the marker loop above calls it while building
// its popups, which a const in the temporal dead zone would not survive
function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({{'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}}[c]));
}}

// Crag popup: the per-source split, then every route on it. Clicking one
// swaps the popup for that route's full properties.
function cragPopup(p) {{
  const dl = Object.entries(p.by)
    .map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + v + '</dd>').join('');
  const list = p.list.map((r, j) =>
    '<button data-c="' + p.i + '" data-r="' + j + '"><span>' + esc(r.name) +
    '</span><b>' + esc(r.grade || '—') + '</b></button>').join('');
  return '<b>' + esc(p.name) + '</b><br>' + p.routes + ' routes<dl>' + dl + '</dl>' +
         (list ? '<div class="rl">' + list + '</div>' : '');
}}

// Route popup: the properties, with the source named so a claim can be chased.
function routePopup(p, r) {{
  const row = (k, v) => v ? '<dt>' + k + '</dt><dd>' + esc(v) + '</dd>' : '';
  const grade = r.grade ? esc(r.grade) + (r.sys ? ' <span class="tag">' + esc(r.sys) + '</span>' : '') : '';
  return '<b>' + esc(r.name) + '</b><br><span class="tag">' + esc(p.name) +
    (r.sector ? ' · ' + esc(r.sector) : '') + '</span><dl>' +
    (grade ? '<dt>grade</dt><dd>' + grade + '</dd>' : '') +
    row('length', r.len ? r.len + ' m' : '') +
    row('pitches', r.p) +
    row('style', (r.disc || []).join(', ')) +
    row('protection', r.prot) +
    row('stars', r.stars) +
    row('first ascent', r.fa) +
    row('source', r.src) +
    '</dl>' + (r.url ? '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">open on ' +
                       esc(r.src) + ' ↗</a>' : '');
}}

function showRoute(ci, ri) {{
  const p = PLACES[ci], r = p.list[ri];
  select(ci, false);
  marks[ci].setPopupContent(routePopup(p, r));
  map.setView([p.lat, p.lon], Math.max(map.getZoom(), 12));
  marks[ci].openPopup();
}}

document.addEventListener('click', e => {{
  const b = e.target.closest('.rl button');
  if (b) showRoute(+b.dataset.c, +b.dataset.r);
}});

function select(i, fly) {{
  rows.forEach(r => r.classList.toggle('on', r.dataset.i == i));
  Object.entries(marks).forEach(([k, m]) =>
    m.setStyle({{fillOpacity: k == i ? .9 : .45, color: k == i ? '#A2402C' : '#C08324'}}));
  if (fly) {{
    const p = PLACES[i];
    map.setView([p.lat, p.lon], 13);
    marks[i].setPopupContent(cragPopup(p));
    marks[i].openPopup();
  }}
}}
rows.forEach(r => r.addEventListener('click', () => select(r.dataset.i, true)));

// ---- route search -------------------------------------------------------
const ALL = [];
PLACES.forEach(p => p.list.forEach((r, j) => ALL.push({{
  c: p.i, r: j, crag: p.name, d: r,
  hay: (r.name + ' ' + p.name + ' ' + (r.grade || '') + ' ' + r.src + ' ' +
        (r.disc || []).join(' ') + ' ' + (r.sector || '')).toLowerCase()
}})));

// Every property the record holds, one column each. `t` is the sort type and
// `g` reads the value, so the header, the cells and the comparator all come
// from this one list.
const COLS = [
  {{k: 'name',   l: 'Route',        t: 's', g: x => x.d.name}},
  {{k: 'crag',   l: 'Crag',         t: 's', g: x => x.crag}},
  {{k: 'sector', l: 'Sector',       t: 's', g: x => x.d.sector}},
  {{k: 'grade',  l: 'Grade',        t: 's', g: x => x.d.grade, n: true,
    tip: 'Sorts within each grade system — systems are never converted'}},
  {{k: 'sys',    l: 'System',       t: 's', g: x => x.d.sys}},
  {{k: 'len',    l: 'Metres',       t: 'n', g: x => x.d.len, n: true}},
  {{k: 'p',      l: 'Pitches',      t: 'n', g: x => x.d.p, n: true}},
  {{k: 'disc',   l: 'Style',        t: 's', g: x => (x.d.disc || []).join(' ')}},
  {{k: 'prot',   l: 'Protection',   t: 's', g: x => x.d.prot}},
  {{k: 'stars',  l: 'Stars',        t: 'n', g: x => x.d.stars, n: true}},
  {{k: 'fa',     l: 'First ascent', t: 's', g: x => x.d.fa}},
  {{k: 'src',    l: 'Source',       t: 's', g: x => x.d.src}},
];

const LIMIT = 250;
const qEl = document.getElementById('q');
const headEl = document.getElementById('rhead');
const listEl = document.getElementById('rlist');
const countEl = document.getElementById('count');
const moreEl = document.getElementById('more');
let sortKey = null, sortDir = 1;

headEl.innerHTML = COLS.map(c =>
  '<th scope="col" data-k="' + c.k + '" tabindex="0" class="sortable' +
  (c.n ? ' num' : '') + '"' + (c.tip ? ' title="' + c.tip + '"' : '') + '>' +
  esc(c.l) + '<span class="arrow"></span></th>').join('') + '<th scope="col"></th>';

function sortBy(k) {{
  sortDir = sortKey === k ? -sortDir : 1;
  sortKey = k;
  headEl.querySelectorAll('th[data-k]').forEach(th => {{
    const on = th.dataset.k === k;
    th.setAttribute('aria-sort', on ? (sortDir > 0 ? 'ascending' : 'descending') : 'none');
    th.querySelector('.arrow').textContent = on ? (sortDir > 0 ? '▲' : '▼') : '';
  }});
  render();
}}
headEl.addEventListener('click', e => {{
  const th = e.target.closest('th[data-k]');
  if (th) sortBy(th.dataset.k);
}});
headEl.addEventListener('keydown', e => {{
  if (e.key === 'Enter' || e.key === ' ') {{
    const th = e.target.closest('th[data-k]');
    if (th) {{ e.preventDefault(); sortBy(th.dataset.k); }}
  }}
}});

function render() {{
  const terms = qEl.value.toLowerCase().split(/\\s+/).filter(Boolean);
  let hits = terms.length ? ALL.filter(x => terms.every(t => x.hay.includes(t))) : ALL.slice();

  if (sortKey) {{
    const col = COLS.find(c => c.k === sortKey);
    hits.sort((a, b) => {{
      const va = col.g(a), vb = col.g(b);
      // "?", "¿?", "¿ ?" are what the Spanish sources write for an unknown —
      // kept verbatim in the cell, but sorted with the blanks, at the end
      const blank = v => v == null || String(v).replace(/[¿?\\s]/g, '') === '';
      const ea = blank(va), eb = blank(vb);
      if (ea || eb) return ea && eb ? 0 : (ea ? 1 : -1);   // blanks always last
      return (col.t === 'n' ? va - vb
                            : String(va).localeCompare(String(vb), 'es')) * sortDir;
    }});
  }}

  countEl.textContent = hits.length + ' of ' + ALL.length + ' routes';
  listEl.innerHTML = hits.slice(0, LIMIT).map(x =>
    '<tr data-c="' + x.c + '" data-r="' + x.r + '">' +
    COLS.map(c => {{
      const v = c.g(x);
      return '<td class="' + (c.n ? 'num' : c.k === 'name' ? 'rname' : 'tag') + '">' +
             (v == null || v === '' ? '·' : esc(v)) + '</td>';
    }}).join('') +
    '<td>' + (x.d.url ? '<a href="' + esc(x.d.url) + '" target="_blank" rel="noopener" ' +
                        'title="open on ' + esc(x.d.src) + '">↗</a>' : '') + '</td></tr>'
  ).join('') || '<tr><td colspan="' + (COLS.length + 1) +
                '" class="empty">No route matches that.</td></tr>';
  moreEl.textContent = hits.length > LIMIT
    ? 'Showing the first ' + LIMIT + ' of ' + hits.length +
      ' — narrow the search, or sort to bring what you want to the top.' : '';
}}

listEl.addEventListener('click', e => {{
  if (e.target.closest('a')) return;   // the ↗ link opens the source, not the popup
  const tr = e.target.closest('tr[data-c]');
  if (tr) showRoute(+tr.dataset.c, +tr.dataset.r);
}});
qEl.addEventListener('input', render);
render();
</script>
"""

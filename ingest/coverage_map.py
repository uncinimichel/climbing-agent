"""Coverage map — one page showing every crag a run found and which source
supplied it.

    python -m ingest map <run-id> [--with <run-id>,<run-id>] [--out FILE]

The question it answers is the one that decides a trip: for this box, what is
documented, by whom, and where are the holes. Sources disagree about names and
positions, so records are clustered into places by an alias table plus name
normalisation, and each place shows a per-source route count. A source column of
dots is a source that has nothing there; a 0 is a source we crawled that yielded
no route list (Compass West, whose routes live inside topo images).

Self-contained HTML with an inline SVG map — no tile server, no map library, so
it opens from disk and survives being published as an artifact.
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

# Traced from the chart, north to south; land lies north-west, sea south-east.
COAST = [(38.85, 0.100), (38.84, 0.115), (38.80, 0.185), (38.77, 0.185),
         (38.74, 0.200), (38.70, 0.175), (38.68, 0.145), (38.66, 0.100),
         (38.64, 0.075), (38.62, 0.045), (38.60, -0.030), (38.57, -0.075),
         (38.54, -0.115), (38.51, -0.190), (38.50, -0.235), (38.47, -0.310),
         (38.45, -0.360)]


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
    crags, bbox = [], None
    for run in run_ids:
        for path in sorted(glob.glob(str(RUNS_DIR / run / "parsed" / "*.json"))):
            d = json.loads(Path(path).read_text())
            bbox = bbox or tuple(d["bbox"])
            for c in d["crags"]:
                if c["lat"] is not None and c["lon"] is not None:
                    crags.append(c)
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
        places.append({
            "key": key,
            "name": sorted({m["name"].split("—")[0].strip() for m in members}, key=len)[0],
            "lat": sum(m["lat"] for m in members) / len(members),
            "lon": sum(m["lon"] for m in members) / len(members),
            "routes": sum(len(m["routes"]) for m in members),
            "by": by, "grades": grades[:5],
        })
    places.sort(key=lambda p: -p["routes"])
    return places


def build(run_ids: list[str], out: Path) -> Path:
    crags, bbox, run = _load(run_ids)
    s, w, n, e = bbox
    lat0 = math.radians((s + n) / 2)
    k = 2000.0

    def proj(lat, lon):
        return ((lon - w) * math.cos(lat0) * k, (n - lat) * k)

    width, height = (e - w) * math.cos(lat0) * k, (n - s) * k
    places = _places(crags)
    sources = sorted({src for p in places for src in p["by"]},
                     key=lambda x: -sum(p["by"].get(x, {}).get("routes", 0) for p in places))
    totals = {x: {"crags": sum(1 for p in places if x in p["by"]),
                  "routes": sum(p["by"].get(x, {}).get("routes", 0) for p in places)}
              for x in sources}
    total_routes = sum(p["routes"] for p in places)

    sea = [proj(*pt) for pt in COAST if s <= pt[0] <= n] + [proj(s, e), proj(n, e)]
    sea_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in sea) + " Z"
    coast_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in
                                (proj(*pt) for pt in COAST if s <= pt[0] <= n))

    dots, labels, placed = [], [], []
    for i, p in enumerate(places):
        x, y = proj(p["lat"], p["lon"])
        r = 3.2 + math.sqrt(p["routes"]) * 1.55
        dots.append(f'<circle class="dot" data-i="{i}" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}">'
                    f'<title>{html.escape(p["name"])} — {p["routes"]} routes</title></circle>')
        if p["routes"] >= 12:
            anchor = "end" if x > width * 0.62 else "start"
            dx = -(r + 6) if anchor == "end" else (r + 6)
            ly = y + 4
            for px, py in placed:
                if abs(px - x) < 150 and abs(py - ly) < 17:
                    ly = py + 18
            placed.append((x, ly))
            labels.append(f'<text class="lbl" x="{x + dx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">'
                          f'{html.escape(p["name"])} <tspan class="lblnum">{p["routes"]}</tspan></text>')

    grat = []
    lon = math.ceil(w * 10) / 10
    while lon < e:
        gx, _ = proj(s, lon)
        grat.append(f'<line class="grat" x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{height:.1f}"/>')
        lon += 0.1
    lat = math.ceil(s * 10) / 10
    while lat < n:
        _, gy = proj(lat, w)
        grat.append(f'<line class="grat" x1="0" y1="{gy:.1f}" x2="{width:.1f}" y2="{gy:.1f}"/>')
        lat += 0.1

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
    scale_px = (10 / 111.32) * math.cos(lat0) * k

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
        width=width, height=height, w=w, e=e, s=s, n=n,
        vb_w=width + 32, vb_h=height + 56, scale_px=scale_px, scale_lbl=scale_px + 8,
        scale_y=height + 28, places=len(places), routes=total_routes,
        records=len(crags), nsources=len(sources), run=run,
        grat="".join(grat), sea=sea_d, coast=coast_d,
        dots="".join(dots), labels="".join(labels),
        legend=legend, head=head, rows="".join(rows), note=note))
    return out


_TEMPLATE = """<title>Costa Blanca Route Coverage</title>
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
.mapbox {{ background:var(--panel); border:1px solid var(--line); border-radius:3px;
  padding:10px; box-shadow:var(--shadow); overflow-x:auto; }}
svg {{ display:block; width:100%; height:auto; }}
.sea {{ fill:var(--sea); }}
.coast {{ fill:none; stroke:var(--teal); stroke-width:1.6; opacity:.55; }}
.grat {{ stroke:var(--line); stroke-width:.8; opacity:.55; }}
.dot {{ fill:var(--ochre); fill-opacity:.62; stroke:var(--ochre); stroke-width:1.4; cursor:pointer; }}
.dot:hover, .dot.on {{ fill-opacity:.95; stroke:var(--ink); stroke-width:2; }}
.lbl {{ font-family:"IBM Plex Sans Condensed",sans-serif; font-weight:600; font-size:15px;
  fill:var(--ink); paint-order:stroke; stroke:var(--panel); stroke-width:3.5px; pointer-events:none; }}
.lblnum {{ font-family:"IBM Plex Mono",monospace; font-weight:500; fill:var(--muted); font-size:13px; }}
.scalewrap text {{ font-family:"IBM Plex Mono",monospace; font-size:12px; fill:var(--muted); }}
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
  <div class="mapbox">
  <svg viewBox="-16 -16 {vb_w:.0f} {vb_h:.0f}" role="img"
       aria-label="Map of Costa Blanca crags, each sized by the number of routes held">
    <rect x="-16" y="-16" width="{vb_w:.0f}" height="{vb_h:.0f}" fill="var(--panel)"/>
    {grat}
    <path class="sea" d="{sea}"/>
    <path class="coast" d="{coast}"/>
    {dots}
    {labels}
    <g class="scalewrap" transform="translate(8,{scale_y:.0f})">
      <line x1="0" y1="0" x2="{scale_px:.1f}" y2="0" stroke="var(--muted)" stroke-width="1.5"/>
      <line x1="0" y1="-4" x2="0" y2="4" stroke="var(--muted)" stroke-width="1.5"/>
      <line x1="{scale_px:.1f}" y1="-4" x2="{scale_px:.1f}" y2="4" stroke="var(--muted)" stroke-width="1.5"/>
      <text x="{scale_lbl:.1f}" y="4">10 km</text>
    </g>
  </svg>
  </div>
  <figcaption>Circle area tracks routes held. The Mediterranean is the tinted
  wedge; the coastline is traced, not surveyed. Click a crag to find it below.</figcaption>
</figure>

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
const dots = document.querySelectorAll('.dot');
const rows = document.querySelectorAll('tbody tr');
function mark(i, scroll) {{
  dots.forEach(d => d.classList.toggle('on', d.dataset.i === i));
  rows.forEach(r => r.classList.toggle('on', r.dataset.i === i));
  if (scroll) {{
    const row = document.querySelector('tbody tr[data-i="' + i + '"]');
    if (row) row.scrollIntoView({{block: 'center', behavior: 'smooth'}});
  }}
}}
dots.forEach(d => d.addEventListener('click', () => mark(d.dataset.i, true)));
rows.forEach(r => r.addEventListener('click', () => mark(r.dataset.i, false)));
</script>
"""

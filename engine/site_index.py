"""Repo-root trip picker — the site homepage (decision #33 M4).

Renders trips/<slug>/ dashboards into a single chooser. The three winter
weekends are a real temporal sequence, so the layout is a timeline spine:
each weekend is a station showing the agent's best-conditions destination.
Palette is a cold winter night with a warm ember accent (the dry rock you
chase in December); condition readouts reuse the dashboards' dry/mixed/wet
colours for continuity. Pure string rendering — no API calls, no JS state.
"""
from datetime import date, datetime, timezone

PAGES_BASE = "https://uncinimichel.github.io/climbing-agent/"


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _band(rain):
    """Wet-day % -> css class, same thresholds as the dashboard copy."""
    if rain is None:
        return "unknown"
    if rain <= 30:
        return "dry"
    if rain <= 55:
        return "mixed"
    return "wet"


def _window(start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if (s.month, s.year) == (e.month, e.year):
        return f"{s:%a} {s.day}–{e.day} {e:%b} {e.year}"
    return f"{s:%a} {s.day} {s:%b} – {e:%a} {e.day} {e:%b} {e.year}"


def _winner(data):
    vs = data.get("venues") or []
    for v in vs:                       # first ranked venue with a real score
        sc = v.get("score", -1)
        if sc is not None and sc >= 0:
            return v, vs
    return (vs[0] if vs else None), vs


def _stop(trip, data, is_best):
    v, vs = _winner(data)
    slug = trip["slug"]
    ended = trip.get("status") == "ended"
    dates = _window(trip["start"], trip["end"])
    flex = trip.get("flex_days", 0)

    if v:
        rain = v.get("wx", {}).get("rain")
        tmax = v.get("wx", {}).get("tmax")
        band_cls = _band(rain)
        temp = f"{round(tmax)}°C" if tmax is not None else "—"
        wet = f"{round(rain)}% wet" if rain is not None else "no data"
        pick = (f'<span class="flag">{_esc(v.get("flag"))}</span>'
                f'<span class="dest">{_esc(v.get("shortName"))}</span>'
                f'<span class="score">{round(v.get("score", 0))}</span>')
        cond = (f'<span class="dot"></span>{temp} · {wet}'
                f'<span class="typ">{"as it happened" if ended else "typical"}</span>')
        runners = " · ".join(
            f'{_esc(r.get("flag"))} {_esc(r.get("shortName"))}' for r in vs[1:3])
        runners = (f'<div class="runners">then {runners}</div>' if runners else "")
    else:
        band_cls = "unknown"
        pick = '<span class="dest">No ranking yet</span>'
        cond = '<span class="dot"></span>render pending'
        runners = ""

    tag = ('<span class="pill ended">ended</span>' if ended
           else '<span class="pill best">best conditions</span>' if is_best
           else f'<span class="pill flex">flexible ±{flex}d</span>')

    cls = "stop" + (" is-ended" if ended else "") + (" is-best" if is_best else "")
    return f"""      <a class="{cls} band-{band_cls}" href="trips/{_esc(slug)}/index.html">
        <span class="node"></span>
        <div class="when">
          <span class="dates">{_esc(dates)}</span>
          {tag}
        </div>
        <div class="body">
          <div class="tname">{_esc(trip["name"])}</div>
          <div class="pick">{pick}</div>
          <div class="cond">{cond}</div>
          {runners}
        </div>
        <span class="go">Open<span class="arr">&#8594;</span></span>
      </a>"""


def build_index(summaries, now=None):
    now = now or datetime.now(timezone.utc)
    live = [(t, d) for t, d in summaries if t.get("status") == "live"]

    # the single live weekend whose winning pick scores highest gets the ember
    best_slug, best_score = None, -1
    for t, d in live:
        v, _ = _winner(d)
        sc = (v or {}).get("score", -1) if v else -1
        if sc is not None and sc > best_score:
            best_score, best_slug = sc, t["slug"]

    stops = "\n".join(
        _stop(t, d, is_best=(t["slug"] == best_slug and t.get("status") == "live"))
        for t, d in summaries)

    return (_PAGE.replace("__CANON__", PAGES_BASE)
                 .replace("__STOPS__", stops)
                 .replace("__NLIVE__", str(len(live)))
                 .replace("__UPDATED__", now.strftime("%-d %b %Y")))


def render_index(repo_root, summaries, now=None):
    html = build_index(summaries, now=now)
    (repo_root / "index.html").write_text(html)
    print(f"[picker] wrote index.html ({len(summaries)} trips)")
    return html


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Winter climbing — pick a weekend</title>
<meta name="description" content="Candidate winter climbing weekends, each ranked across the whole crag catalogue for the best-conditions destination.">
<link rel="canonical" href="__CANON__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --night:#0C1220; --night2:#111A2B; --panel:#141F33; --panelHi:#182742;
    --frost:#EAF1FA; --mist:#93A2B8; --faint:#57657E; --line:#22314C;
    --ember:#E8763B; --ember-soft:rgba(232,118,59,.14);
    --dry:#57A664; --mixed:#C89A45; --wet:#D06A57; --unknown:#57657E;
    --disp:'Fraunces',Georgia,serif; --body:'IBM Plex Sans',system-ui,sans-serif;
    --mono:'IBM Plex Mono',ui-monospace,monospace;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--night);color:var(--frost);font-family:var(--body);
       line-height:1.5;-webkit-font-smoothing:antialiased;
       background-image:radial-gradient(120% 80% at 88% -8%,rgba(232,118,59,.10),transparent 60%),
                        radial-gradient(90% 60% at 0% 0%,rgba(60,96,150,.12),transparent 55%);
       background-attachment:fixed}
  .wrap{max-width:820px;margin:0 auto;padding:clamp(40px,7vw,88px) 22px 96px}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.22em;
       text-transform:uppercase;color:var(--ember);margin-bottom:20px}
  h1{font-family:var(--disp);font-weight:500;font-size:clamp(34px,6.4vw,60px);
       line-height:1.02;letter-spacing:-.015em;margin:0 0 22px;max-width:15ch}
  h1 em{font-style:italic;font-weight:400;color:var(--ember)}
  .lede{color:var(--mist);font-size:clamp(15px,2vw,17px);max-width:56ch;margin:0}
  .lede b{color:var(--frost);font-weight:500}

  .line{margin:clamp(40px,6vw,64px) 0 0;position:relative}
  .line::before{content:"";position:absolute;left:11px;top:12px;bottom:14px;width:2px;
       background:linear-gradient(var(--line),var(--line) 60%,transparent);
       transform-origin:top;animation:draw .9s ease both}
  .stop{display:grid;grid-template-columns:24px 1fr auto;column-gap:20px;
       align-items:start;padding:22px 20px 22px 0;text-decoration:none;color:inherit;
       border-bottom:1px solid var(--line);position:relative;
       transition:transform .16s ease;animation:rise .6s ease both}
  .stop:first-of-type{padding-top:6px}
  .stop:nth-child(2){animation-delay:.06s}
  .stop:nth-child(3){animation-delay:.12s}
  .stop:nth-child(4){animation-delay:.18s}
  .stop:hover,.stop:focus-visible{transform:translateX(4px);outline:none}
  .stop:focus-visible .node{box-shadow:0 0 0 3px var(--night),0 0 0 5px var(--ember)}
  .node{grid-row:1/99;width:14px;height:14px;margin-top:6px;border-radius:50%;
       background:var(--night);border:2px solid var(--faint);z-index:1;
       transition:border-color .16s,box-shadow .16s}
  .stop:hover .node{border-color:var(--frost)}

  .when{display:flex;flex-direction:column;gap:8px}
  .dates{font-family:var(--mono);font-size:13.5px;color:var(--frost);letter-spacing:.01em}
  .pill{justify-self:start;font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;
       text-transform:uppercase;padding:3px 9px;border-radius:999px;width:max-content;
       border:1px solid var(--line);color:var(--mist)}
  .pill.best{color:var(--ember);border-color:rgba(232,118,59,.5);background:var(--ember-soft)}
  .pill.ended{color:var(--faint)}

  .body{grid-column:2;margin-top:16px}
  .tname{font-family:var(--mono);font-size:11px;letter-spacing:.14em;
       text-transform:uppercase;color:var(--faint);margin-bottom:7px}
  .pick{display:flex;align-items:baseline;gap:11px}
  .flag{font-size:19px;line-height:1}
  .dest{font-family:var(--disp);font-weight:600;font-size:clamp(21px,3.4vw,27px);
       letter-spacing:-.01em}
  .score{margin-left:2px;font-family:var(--mono);font-size:13px;color:var(--mist);
       border:1px solid var(--line);border-radius:7px;padding:1px 7px;align-self:center}
  .cond{display:flex;align-items:center;gap:8px;margin-top:9px;font-family:var(--mono);
       font-size:13px;color:var(--mist)}
  .cond .dot{width:8px;height:8px;border-radius:50%;background:var(--unknown)}
  .band-dry .cond .dot{background:var(--dry)} .band-dry .cond{color:var(--dry)}
  .band-mixed .cond .dot{background:var(--mixed)} .band-mixed .cond{color:var(--mixed)}
  .band-wet .cond .dot{background:var(--wet)} .band-wet .cond{color:var(--wet)}
  .cond .typ{color:var(--faint)}
  .cond .typ::before{content:"\\00b7";margin-right:8px}
  .runners{margin-top:11px;font-size:13px;color:var(--faint)}

  .go{grid-column:3;align-self:center;font-family:var(--mono);font-size:12.5px;
       color:var(--mist);white-space:nowrap;display:flex;align-items:center;gap:7px}
  .go .arr{transition:transform .16s ease}
  .stop:hover .go{color:var(--frost)} .stop:hover .go .arr{transform:translateX(4px)}

  /* the ember weekend: warm node, warm score, faint glow up the spine */
  .is-best .node{border-color:var(--ember);background:var(--ember);
       box-shadow:0 0 0 5px var(--ember-soft)}
  .is-best .dest{color:var(--frost)}
  .is-best .score{color:var(--ember);border-color:rgba(232,118,59,.45)}

  .is-ended{opacity:.62}
  .is-ended .node{border-style:dashed}
  .is-ended:hover{opacity:.85}

  footer{margin-top:40px;color:var(--faint);font-size:12.5px;font-family:var(--mono);
       line-height:1.7}
  footer a{color:var(--mist);text-underline-offset:3px}
  footer .u{color:var(--mist)}

  @media (max-width:560px){
    .stop{grid-template-columns:22px 1fr;column-gap:16px}
    .go{grid-column:2;grid-row:auto;margin-top:14px;justify-self:start}
    .body{grid-column:2}
  }
  @keyframes draw{from{transform:scaleY(0)}to{transform:scaleY(1)}}
  @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  @media (prefers-reduced-motion:reduce){
    .line::before,.stop{animation:none}
    .stop:hover,.stop:focus-visible{transform:none}
  }
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">Climbing agent · winter</div>
      <h1>Three weekends out. Pick your <em>line</em>.</h1>
      <p class="lede">For each candidate weekend, the agent ranks <b>every crag in
        the catalogue</b> and surfaces the one with the best conditions. This far
        out it reads typical winter weather; it sharpens to live forecast as each
        date nears. Open a weekend for the full ranking, weather and flights.</p>
    </header>
    <main class="line">
__STOPS__
    </main>
    <footer>
      <span class="u">__NLIVE__ live weekends</span> · updated __UPDATED__ ·
      ranked on typical-weather climatology &amp; the long-range outlook.<br>
      <a href="knowledge/index.html">How the ranking works</a> ·
      <a href="https://multi-pitch.com/">multi-pitch.com</a>
    </footer>
  </div>
</body>
</html>
"""

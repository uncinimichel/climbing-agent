#!/usr/bin/env python3
"""Render knowledge/**/*.md → matching .html on the GitHub Pages site.

The site ships a `.nojekyll` file, so GitHub Pages serves raw Markdown as plain
text (no rendering). This script converts every Markdown doc in `knowledge/` into
a styled HTML page that mirrors the folder structure (knowledge/data/taxonomy.md →
knowledge/data/taxonomy.html) and builds a knowledge index at knowledge/index.html.

Dependency-free (stdlib only), matching the project's no-pip ethos. It handles the
Markdown subset these docs use: headings, tables, fenced code, blockquotes, ordered/
unordered (nested) lists, hr, and inline bold/italic/code/links. Intra-doc `.md`
links are rewritten to `.html`.

Run: python3 trip-ni-july-2026/scripts/build_knowledge.py
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KDIR = ROOT / "knowledge"
TAG_SPEC_FILE = KDIR / "data" / "tag-spec.json"


def _tag_table(fam: str) -> str:
    """Render one family's rows from the tag-spec single source of truth."""
    spec = json.loads(TAG_SPEC_FILE.read_text(encoding="utf-8"))
    out = ["| Tag | Meaning | Values | Source |", "|---|---|---|---|"]
    for t in spec["tags"]:
        if t["family"] == fam:
            out.append(f"| `{t['k']}` | {t['meaning']} | {t.get('values', '')} | {t['source']} |")
    return "\n".join(out)


def _expand_tag_tables(md: str) -> str:
    """Fill {{TAGTABLE:family}} placeholders from knowledge/data/tag-spec.json."""
    return re.sub(r"\{\{TAGTABLE:([a-z]+)\}\}", lambda m: _tag_table(m.group(1)), md)

# ── inline formatting ───────────────────────────────────────────────────────
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITAL = re.compile(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _rewrite_href(url: str) -> str:
    """Local .md links → .html (keep #anchors and external URLs intact)."""
    if re.match(r"^[a-z]+://", url) or url.startswith("mailto:"):
        return url
    return re.sub(r"\.md(#.*)?$", lambda m: ".html" + (m.group(1) or ""), url)


def inline(text: str) -> str:
    """Escape HTML then apply inline markdown. Code spans are protected."""
    spans: list[str] = []

    def stash(m):
        spans.append("<code>" + html.escape(m.group(1)) + "</code>")
        return f"\x00{len(spans)-1}\x00"

    text = _CODE.sub(stash, text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITAL.sub(r"<em>\1</em>", text)
    text = _LINK.sub(
        lambda m: f'<a href="{html.escape(_rewrite_href(m.group(2)), quote=True)}">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    return text


# ── block parsing ───────────────────────────────────────────────────────────
def _table(rows: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<table><thead><tr>"]
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return '<div class="tw">' + "".join(out) + "</div>"


def _is_table_sep(line: str) -> bool:
    return bool(re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]+$", line)) and "-" in line


def _list(items: list[tuple[int, str, bool]]) -> str:
    """items = [(indent, text, ordered)]; build nested <ul>/<ol>."""
    html_out = []
    stack: list[tuple[int, str]] = []  # (indent, tag)

    for indent, text, ordered in items:
        tag = "ol" if ordered else "ul"
        while stack and indent < stack[-1][0]:
            html_out.append(f"</li></{stack.pop()[1]}>")
        if stack and indent == stack[-1][0]:
            html_out.append("</li>")
        if not stack or indent > stack[-1][0]:
            stack.append((indent, tag))
            html_out.append(f"<{tag}>")
        html_out.append(f"<li>{inline(text)}")
    while stack:
        html_out.append(f"</li></{stack.pop()[1]}>")
    return "".join(html_out)


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        # fenced code
        if line.lstrip().startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].lstrip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue

        # blank
        if not line.strip():
            i += 1
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            txt = inline(m.group(2).strip())
            anchor = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
            out.append(f'<h{lvl} id="{anchor}">{txt}</h{lvl}>')
            i += 1
            continue

        # hr
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line.strip()):
            out.append("<hr>")
            i += 1
            continue

        # table
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            tbl = [line]
            i += 1
            while i < n and "|" in lines[i] and lines[i].strip():
                tbl.append(lines[i])
                i += 1
            out.append(_table(tbl))
            continue

        # blockquote
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = md_to_html("\n".join(buf))
            out.append(f"<blockquote>{inner}</blockquote>")
            continue

        # list (unordered - * ; ordered N. )
        lm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if lm:
            items = []
            while i < n:
                lm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
                if not lm:
                    if lines[i].strip() == "":
                        # allow blank line inside list only if next line is a list item
                        if i + 1 < n and re.match(r"^(\s*)([-*]|\d+\.)\s+", lines[i + 1]):
                            i += 1
                            continue
                    break
                indent = len(lm.group(1))
                ordered = lm.group(2).endswith(".")
                items.append((indent, lm.group(3), ordered))
                i += 1
            out.append(_list(items))
            continue

        # paragraph
        buf = []
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|>|\s*([-*]|\d+\.)\s|```|(-{3,}|\*{3,})$)", lines[i]
        ):
            if "|" in lines[i] and i + 1 < n and _is_table_sep(lines[i + 1]):
                break
            buf.append(lines[i])
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")

    return "\n".join(out)


# ── page template ───────────────────────────────────────────────────────────
CSS = """
:root{--ink:#0C0D10;--ink2:#12141B;--ink3:#191C27;--ink4:#20243A;--seam:#252840;
--chalk:#EAE6DD;--chalk2:#9B9890;--chalk3:#5A5860;--go:#6CB268;--amb:#C8A44A;
--wet:#B94438;--spike:#C4FF5C;--r:6px;--r-lg:12px}
*{box-sizing:border-box}
html,body{margin:0;background:var(--ink);color:var(--chalk)}
body{font-family:'Inter',system-ui,sans-serif;font-size:15px;line-height:1.65;
-webkit-font-smoothing:antialiased}
.top{position:sticky;top:0;z-index:10;height:48px;background:var(--ink2);
border-bottom:1px solid var(--seam);display:flex;align-items:center;gap:12px;padding:0 18px}
.logo{font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:var(--chalk);
letter-spacing:-.2px;text-decoration:none}
.top a.btn{margin-left:auto;font-size:12px;color:var(--chalk2);text-decoration:none;
border:1px solid var(--seam);border-radius:var(--r);padding:5px 12px}
.top a.btn:hover{color:var(--chalk);border-color:var(--chalk3)}
.wrap{max-width:860px;margin:0 auto;padding:32px 22px 96px}
.crumb{font-size:12px;color:var(--chalk3);margin-bottom:22px;font-family:'DM Mono',monospace}
.crumb a{color:var(--chalk2);text-decoration:none}
.crumb a:hover{color:var(--spike)}
h1,h2,h3,h4{font-family:'Syne',sans-serif;letter-spacing:-.3px;line-height:1.25;
scroll-margin-top:64px}
h1{font-size:30px;font-weight:800;margin:.2em 0 .6em}
h2{font-size:21px;font-weight:700;margin:1.8em 0 .5em;padding-top:.4em;
border-top:1px solid var(--seam)}
h3{font-size:16.5px;font-weight:700;margin:1.4em 0 .4em;color:var(--chalk)}
h4{font-size:14px;font-weight:700;margin:1.2em 0 .3em;color:var(--chalk2)}
p{margin:.7em 0}
a{color:var(--amb);text-decoration:none;border-bottom:1px solid rgba(200,164,74,.28)}
a:hover{color:var(--spike);border-bottom-color:var(--spike)}
strong{color:#fff;font-weight:600}
code{font-family:'DM Mono',ui-monospace,monospace;font-size:.86em;background:var(--ink3);
border:1px solid var(--seam);border-radius:4px;padding:1px 5px;color:var(--amb)}
pre{background:var(--ink2);border:1px solid var(--seam);border-radius:var(--r-lg);
padding:16px 18px;overflow-x:auto;margin:1em 0}
pre code{background:none;border:none;padding:0;color:var(--chalk2);font-size:12.5px;
line-height:1.5;white-space:pre}
blockquote{margin:1.1em 0;padding:.4em 16px;border-left:3px solid var(--amb);
background:var(--amb-d,rgba(200,164,74,.07));border-radius:0 var(--r) var(--r) 0;
color:var(--chalk2)}
blockquote p{margin:.4em 0}
hr{border:none;border-top:1px solid var(--seam);margin:2em 0}
ul,ol{margin:.6em 0;padding-left:1.4em}
li{margin:.28em 0}
li>ul,li>ol{margin:.25em 0}
.tw{overflow-x:auto;margin:1.1em 0;border:1px solid var(--seam);border-radius:var(--r-lg)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--seam);
vertical-align:top}
th{background:var(--ink3);font-family:'Syne',sans-serif;font-weight:700;font-size:12px;
color:var(--chalk);white-space:nowrap}
tr:last-child td{border-bottom:none}
td code{white-space:nowrap}
.idx-group{margin:1.4em 0}
.idx-group h3{border-bottom:1px solid var(--seam);padding-bottom:.3em}
.idx-card{display:block;padding:12px 14px;margin:8px 0;background:var(--ink2);
border:1px solid var(--seam);border-radius:var(--r-lg);color:var(--chalk);
border-bottom:1px solid var(--seam)}
.idx-card:hover{border-color:var(--chalk3);color:var(--chalk)}
.idx-card b{font-family:'Syne',sans-serif}
.idx-card span{display:block;color:var(--chalk2);font-size:13px;margin-top:2px}
@media(max-width:600px){.wrap{padding:22px 15px 80px}h1{font-size:24px}body{font-size:14px}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800'
         '&family=Inter:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500'
         '&display=swap" rel="stylesheet">')


def page(title: str, body: str, depth: int, crumb: str) -> str:
    home = "../" * depth
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)} · multi-pitch Live</title>{FONTS}"
        f"<style>{CSS}</style></head><body>"
        f'<div class=top><a class=logo href="{home}index.html">🧗 multi-pitch <span style="color:var(--spike)">Live</span></a>'
        f'<a class=btn href="{home}knowledge/index.html">📚 Knowledge</a>'
        f'<a class=btn href="{home}knowledge/corpus-inspector.html">🧗 Inspector</a>'
        f'<a class=btn href="{home}knowledge/data-dependencies.html">🗺 Data map</a>'
        f'<a class=btn href="{home}index.html">▶ Dashboard</a></div>'
        f'<div class=wrap><div class=crumb>{crumb}</div>{body}</div></body></html>'
    )


# ── titles / descriptions for the index ─────────────────────────────────────
TITLES = {
    "README": ("Knowledge Base — Home", "Index & navigation for the whole project."),
    "CONVENTIONS": ("Conventions", "Doc + code conventions for contributors and agents."),
    "vision/mission": ("The Mission", "The North Star: the four-layer decision engine."),
    "vision/glossary": ("Glossary", "Climbing + system vocabulary."),
    "architecture/overview": ("Architecture Overview", "The four layers → concrete components."),
    "architecture/current-state": ("Current State", "Honest snapshot: what runs today vs planned."),
    "architecture/data-flow": ("Data Flow", "How a data point travels scraper → dashboard."),
    "architecture/retrieval-agent": ("Retrieval Agent", "Admin chat over the DB: SQL-first tool use; pgvector later."),
    "architecture/phases": ("The Four Layers", "Per-layer developer guide: interfaces + when building here."),
    "architecture/venue-env-cache": ("Venue Env Cache", "Trip-independent weather/tide, once per venue (decision #24)."),
    "data/taxonomy": ("Strict Data Dictionary", "Controlled vocabularies for tagging a climb."),
    "data/tags": ("Area Character Tags", "The venue-card tag key: two tiers, four families, every value."),
    "data/route-schema": ("Route Schema", "The tagging target: full route record (from multi-pitch.com)."),
    "data/grade-conversion": ("Grade Conversion", "Normalized dataGrade 1–7 across grade systems."),
    "data/schemas": ("Data Schemas", "JSON shapes: venues, flights, conditions."),
    "data/condition-algorithm": ("Condition Algorithm", "The predictive weather-scoring maths."),
    "data/weather-models": ("Weather Models", "Why Open-Meteo + the ECMWF ensemble, and the forecast-horizon strategy."),
    "data/references": ("References & Authorities", "People, books & encyclopedias behind the taxonomy."),
    "data/external-models": ("External Models", "How UKC/theCrag/MP/OpenBeta model data — and what to adopt."),
    "data/database": ("Database (Postgres)", "The relational schema for the taxonomy + route corpus (db/)."),
    "data/source-of-truth": ("Source of Truth", "Where climb/venue data lives — one authored corpus.json (decision #27)."),
    "data/governance": ("Data Governance", "Trust tiers (curated / seeded / AI-tagged) + the curated-only ranking rule (#32)."),
    "data-dependencies": ("Data Map", "Visual data-flow graph: where each source lives + where to add a new climb or venue (#27)."),
    "corpus-inspector": ("Corpus Inspector", "Read-only admin: browse every climb with its taxonomy + weather (reads corpus.json)."),
    "operations/deployment": ("Deployment", "GitHub Actions + Pages + secrets."),
    "operations/external-apis": ("External APIs", "Open-Meteo, SerpApi, multi-pitch data.json."),
    "operations/runbook": ("Runbook", "Run / verify / maintain, day to day."),
    "operations/notifications": ("Notifications & Push", "Options for a push/alert channel (Telegram, ntfy, web push) — the Action is the sender."),
    "operations/testing-plan": ("Testing Plan", "How to test the build: one network chokepoint, determinism."),
    "roadmap/roadmap": ("Roadmap", "Prototype → platform, staged."),
    "roadmap/ingestion-plan": ("Ingestion Plan", "The free, staged build of Phase 1→3 — sources, scraping, tagging, curation."),
    "roadmap/multi-pitch-site-plan": ("multi-pitch.com Site Plan", "The same vision as a multi-pitch.com product roadmap."),
    "roadmap/curation-studio-plan": ("Curation Studio Plan", "The fast localhost UI for reviewing drafts into curated rows (#32 follow-up)."),
    "roadmap/trip-editing-plan": ("Trip Editing Plan", "Multi-trip, file-backed: trips.json registry, shared fetch layer, local admin forms (#33)."),
    "roadmap/decisions": ("Decision Log", "Lightweight ADRs — why we chose X."),
}
GROUPS = [
    ("Start here", ["README", "CONVENTIONS"]),
    ("Vision", ["vision/mission", "vision/glossary"]),
    ("Architecture", ["architecture/current-state", "architecture/overview", "architecture/data-flow",
                       "architecture/phases", "architecture/retrieval-agent", "architecture/venue-env-cache"]),
    ("Data & Taxonomy", ["data/taxonomy", "data/tags", "data/route-schema", "data/grade-conversion",
                          "data/schemas", "data/database", "data/source-of-truth", "data/governance", "data-dependencies",
                          "corpus-inspector", "data/condition-algorithm", "data/weather-models",
                          "data/references", "data/external-models"]),
    ("Operations", ["operations/deployment", "operations/external-apis", "operations/runbook",
                     "operations/notifications", "operations/testing-plan"]),
    ("Roadmap", ["roadmap/roadmap", "roadmap/ingestion-plan", "roadmap/multi-pitch-site-plan",
                  "roadmap/curation-studio-plan", "roadmap/trip-editing-plan", "roadmap/decisions"]),
]


def build():
    md_files = sorted(KDIR.rglob("*.md"))
    count = 0
    for md_path in md_files:
        rel = md_path.relative_to(KDIR).with_suffix("")  # e.g. data/taxonomy
        key = rel.as_posix()
        depth = len(rel.parts)  # for ../ back to repo root from inside knowledge/
        title = TITLES.get(key, (md_path.stem.replace("-", " ").title(), ""))[0]
        raw = md_path.read_text(encoding="utf-8")
        if "{{TAGTABLE:" in raw:
            raw = _expand_tag_tables(raw)
        body = md_to_html(raw)
        parts = ['<a href="' + ("../" * (depth - 1)) + 'index.html">📚 knowledge</a>']
        for p in rel.parts[:-1]:
            parts.append(p)
        parts.append(f"<b style='color:var(--chalk2)'>{rel.parts[-1]}</b>")
        crumb = " / ".join(parts)
        out_path = md_path.with_suffix(".html")
        # depth from this html file back to repo root = number of dirs below repo root
        depth_to_root = len(out_path.relative_to(ROOT).parts) - 1
        out_path.write_text(page(title, body, depth_to_root, crumb), encoding="utf-8")
        count += 1

    # knowledge index
    cards = ['<h1>📚 Knowledge Base</h1>',
             '<p>Reference brain for <strong>multi-pitch.com "Live"</strong> — the dynamic, '
             'predictive climbing-trip decision engine. Vision, architecture, the tagging '
             'taxonomy, and the roadmap.</p>']
    for group, keys in GROUPS:
        cards.append(f'<div class=idx-group><h3>{group}</h3>')
        for k in keys:
            t, d = TITLES.get(k, (k, ""))
            href = (k if "/" in k else k) + ".html"
            cards.append(f'<a class=idx-card href="{href}"><b>{html.escape(t)}</b>'
                         f'<span>{html.escape(d)}</span></a>')
        cards.append("</div>")
    idx_body = "\n".join(cards)
    crumb = '<b style="color:var(--chalk2)">knowledge</b>'
    (KDIR / "index.html").write_text(
        page("Knowledge Base", idx_body, 1, crumb), encoding="utf-8")
    print(f"Built {count} knowledge pages + index → knowledge/index.html")


if __name__ == "__main__":
    build()

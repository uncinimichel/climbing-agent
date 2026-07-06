#!/usr/bin/env python3
"""One-time snapshot of the multi-pitch.com per-climb source → db/mp-climbs.json.

The public multi-pitch.com/data/data.json is shallow (grade/length/pitches/geo).
The *local* site source keeps the canonical rich record per climb at
`website/data/climbs/{id}.json` — with rock, incline, aspect (`face`), the hazard
booleans, 12-month weather, and prose (`intro`/`pitchInfo`). This script reads
those files ONCE and writes a self-contained, committed snapshot that build_corpus.py
consumes offline — so the enrichment is done once and lives in the repo, never
re-read from a machine-specific path (decision #27).

Re-run only when the multi-pitch source changes:
    python3 db/tools/enrich_from_multipitch.py [/path/to/multi-pitch]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "db" / "mp-climbs.json"
DEFAULT_SRC = Path("/Users/micheluncini/dev/multi-pitch/website/data/climbs")

# MP hazard booleans → taxonomy hazard codes (knowledge/data/taxonomy.md)
HAZARD_FLAGS = {"abseil": "abseil", "traverse": "traverse", "boat": "boat", "tidal": "tidal",
                "polished": "polished", "loose": "loose", "seepage": "seepage",
                "grassLegdes": "grassLedges"}
BASE = ["id", "routeName", "cliff", "country", "county", "geoLocation", "gradeSys",
        "originalGrade", "tradGrade", "techGrade", "length", "pitches", "approachTime",
        "approachDifficulty", "dataGrade", "status", "rock", "incline", "face"]


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def weather_to_climatology(w):
    """MP weatherData = parallel 12-month arrays → [{month,tempHigh,tempLow,rainyDays}]."""
    if not w:
        return []
    hi, lo, rd = w.get("tempH") or [], w.get("tempL") or [], w.get("rainyDays") or []
    out = []
    for m in range(12):
        if m < len(hi) or m < len(lo) or m < len(rd):
            out.append({"month": m + 1,
                        "tempHigh": hi[m] if m < len(hi) else None,
                        "tempLow": lo[m] if m < len(lo) else None,
                        "rainyDays": rd[m] if m < len(rd) else None})
    return out


def main():
    src = Path(sys.argv[1]) / "website" / "data" / "climbs" if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.exists():
        print(f"[error] multi-pitch source not found: {src}\n"
              f"Pass the repo path: python3 db/tools/enrich_from_multipitch.py /path/to/multi-pitch",
              file=sys.stderr)
        sys.exit(1)
    climbs = []
    for f in sorted(src.glob("*.json")):
        if f.stem == "template":
            continue
        try:
            c = json.loads(f.read_text()).get("climbData", {})
        except Exception as e:
            print(f"[warn] {f.name}: {e}", file=sys.stderr)
            continue
        if not c.get("id"):
            continue
        rec = {k: c.get(k) for k in BASE}
        rec["hazards"] = [code for flag, code in HAZARD_FLAGS.items() if c.get(flag)]
        rec["climatology"] = weather_to_climatology(c.get("weatherData"))
        rec["description"] = strip_html(c.get("intro"))
        rec["pitchInfo"] = strip_html(c.get("pitchInfo"))
        climbs.append(rec)
    OUT.write_text(json.dumps({"source": "multi-pitch.com local site source",
                               "note": "One-time rich snapshot (decision #27). Regenerate with "
                                       "enrich_from_multipitch.py when the MP source changes.",
                               "count": len(climbs), "climbs": climbs},
                              ensure_ascii=False, indent=2) + "\n")
    wx = sum(1 for c in climbs if c["climatology"])
    rock = sum(1 for c in climbs if c["rock"])
    print(f"wrote {OUT.relative_to(ROOT)} — {len(climbs)} climbs "
          f"({rock} with rock, {wx} with weather)")


if __name__ == "__main__":
    main()

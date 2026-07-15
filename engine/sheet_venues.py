"""Google-Sheet-driven venue list — moved verbatim from update_report.py.

Michel curates areas in a Google Sheet (downloaded as climbing-trips.csv each
CI run). Every sheet row becomes a ranked venue: curated venues.json entries
are enriched with their sheet columns; unmatched rows are generated from the
GAZETTEER below (coords + airports), falling back to free geocoding.

This is NI-trip-specific ingestion, not part of the generic per-trip engine —
an arbitrary user-defined trip supplies its own venues directly rather than
through this sheet, so nothing else in engine/ depends on this module.
"""
import csv
import difflib
import re
import sys
import unicodedata
import urllib.parse

from .http import get_json


def _fly(m_to, d_to=None):
    return {"michel": {"mode": "fly", "to": m_to}, "dan": {"mode": "fly", "to": d_to or m_to}}


# Coords + airports for sheet areas (keys = accent-stripped lowercase sheet names,
# in the sheet's own spellings). New sheet rows missing here are geocoded.
# Same physical-character vocabulary as venues.json (see its "notes"): aspect /
# coastal / wind_exposed / drying — the ranking reads them for felt temperature,
# gust exposure and how long the rock stays wet.
GAZETTEER = {
    "tenerife": dict(lat=28.27, lon=-16.64, rock="volcanic", style="Cañadas del Teide multi-pitch", travel=_fly("TFS")),
    "mallorca": dict(lat=39.72, lon=2.77, rock="limestone", style="Sa Gubia + sea cliffs", coastal=True, travel=_fly("PMI")),
    "riglos": dict(lat=42.35, lon=-0.73, rock="conglomerate", style="huge overhanging towers", aspect="S", wind_exposed=True, travel=_fly("BCN")),
    "vratsa": dict(lat=43.20, lon=23.55, rock="limestone", style="big limestone walls", travel=_fly("SOF")),
    "elbsandstein": dict(lat=50.91, lon=14.06, rock="sandstone", style="historic sandstone towers", travel=_fly("PRG")),
    "montserrat": dict(lat=41.60, lon=1.81, rock="conglomerate", style="pocketed conglomerate spires", travel=_fly("BCN")),
    "freyr": dict(lat=50.22, lon=4.89, rock="limestone", style="Meuse valley slab classics", travel=_fly("BRU")),
    "meteora": dict(lat=39.72, lon=21.63, rock="conglomerate", style="monastery towers, bold conglomerate", travel=_fly("SKG")),
    "anti atlas": dict(lat=29.72, lon=-8.98, rock="quartzite", style="vast desert trad (Tafraout)", travel=_fly("AGA")),
    "bruggler": dict(lat=47.12, lon=8.99, rock="limestone", style="plated limestone slabs", aspect="S", travel=_fly("ZRH")),
    "setesdal": dict(lat=58.9, lon=7.4, rock="granite", style="granite walls & slabs", travel=_fly("KRS")),
    "loften": dict(lat=68.12, lon=13.6, rock="granite", style="arctic granite (Presten, Svolvær)", coastal=True, travel=_fly("BOO")),
    "wadi rum": dict(lat=29.57, lon=35.42, rock="sandstone", style="desert big walls, Bedouin routes", travel=_fly("AQJ")),
    "triglav": dict(lat=46.38, lon=13.84, rock="limestone", style="north-face alpine limestone", aspect="N", travel=_fly("LJU")),
    "lundy": dict(lat=51.18, lon=-4.67, rock="granite", style="island sea-cliff granite", tidal=True, coastal=True, wind_exposed=True,
                  travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "BRS"}}),
    "costa blanca": dict(lat=38.63, lon=0.07, rock="limestone", style="Peñón d'Ifach + big ridges", aspect="S", coastal=True, travel=_fly("ALC")),
    "zadiel": dict(lat=48.62, lon=20.83, rock="limestone", style="karst gorge towers", travel=_fly("KSC")),
    "calanques": dict(lat=43.21, lon=5.45, rock="limestone", style="sea cliffs above turquoise coves", aspect="S", coastal=True, travel=_fly("MRS")),
    "gredos": dict(lat=40.27, lon=-5.17, rock="granite", style="Galayos granite spires", aspect="W", travel=_fly("MAD")),
    "sicilly": dict(lat=38.17, lon=12.74, rock="limestone", style="San Vito lo Capo sea cliffs", coastal=True, travel=_fly("PMO")),
    "campanile basso": dict(lat=46.16, lon=10.87, rock="dolomite", style="Brenta's free-standing tower", travel=_fly("VRN")),
    "mont blonc": dict(lat=45.88, lon=6.89, rock="granite", style="high alpine granite (Chamonix)", travel=_fly("GVA")),
    "spitzkoppe": dict(lat=-21.83, lon=15.19, rock="granite", style="desert granite dome", travel=_fly("WDH")),
    "hoy": dict(lat=58.88, lon=-3.43, rock="sandstone", style="Old Man of Hoy sea stack", aspect="W", coastal=True, wind_exposed=True, travel=_fly("KOI")),
    "isle of white": dict(lat=50.66, lon=-1.30, rock="chalk", style="south-coast sea cliffs", tidal=True, coastal=True, aspect="S",
                          travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "SOU"}}),
    "devon": dict(lat=50.92, lon=-4.56, rock="culm sandstone", style="Culm coast slabs (Wreckers Slab)", tidal=True, coastal=True, wind_exposed=True,
                  travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "EXT"}}),
    "carcassonne": dict(lat=43.21, lon=2.35, rock="limestone", style="southern France crags", travel=_fly("CCF")),
    "medina": dict(lat=24.47, lon=39.61, rock="granite", style="desert granite", travel=_fly("MED")),
    "aladaglar": dict(lat=37.80, lon=35.15, rock="limestone", style="Turkish alpine limestone", travel=_fly("ASR")),
}

# sheet spelling -> curated venues.json name
SHEET_ALIAS = {
    "east tyrol": "East Tyrol (Lienz)", "picos europa": "Picos de Europa",
    "dolomites": "Dolomites (Cortina)", "aaran": "Isle of Arran",
    "mournes": "Mournes, NI", "lake district": "Lake District (Borrowdale)",
    "llanberis": "Snowdonia (Llanberis Pass)", "cornwall": "West Cornwall (Bosigran)",
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)   # keep parenthetical tokens (e.g. "Llanberis")
    return [t for t in s.split() if t not in ("the", "de", "of", "ni", "la", "el")]


def _key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def load_sheet_rows(csv_path):
    """(sheet_row, area_name) parsed from the venue spreadsheet CSV — true row numbers."""
    rows = []
    try:
        for i, r in enumerate(csv.reader(csv_path.open()), start=1):
            if i >= 3 and r and r[0].strip():     # rows 1-2 are banner/header
                rows.append((i, r[0].strip()))
    except Exception as e:
        print(f"[warn] could not read {csv_path.name}: {e}", file=sys.stderr)
    return rows


def load_sheet_full(csv_path):
    """All venue rows with the judgment columns (volume/difficulty/travel/min-trip)."""
    rows = []
    try:
        rdr = list(csv.reader(csv_path.open()))
    except Exception as e:
        print(f"[warn] could not read {csv_path.name}: {e}", file=sys.stderr)
        return rows

    def g(r, j):
        return r[j].strip() if j < len(r) else ""
    for i, r in enumerate(rdr, 1):
        if i < 3 or not r or not r[0].strip():    # rows 1-2 are banner/header
            continue
        rows.append({"row": i, "area": g(r, 0), "country": g(r, 1), "volume": g(r, 2),
                     "max_height": g(r, 4), "difficulty": g(r, 5), "travel_time": g(r, 6),
                     "hub": g(r, 7), "min_trip": g(r, 8), "cost": g(r, 9), "link": g(r, 22)})
    return rows


def geocode(name):
    """Open-Meteo's free geocoder — fallback for sheet rows not in the GAZETTEER."""
    try:
        d = get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&name="
                      + urllib.parse.quote(name))
        res = (d.get("results") or [None])[0]
        if res:
            return dict(lat=res["latitude"], lon=res["longitude"],
                        country=res.get("country", ""), rock="", style="",
                        travel={"michel": {"mode": "fly", "to": ""}, "dan": {"mode": "fly", "to": ""}})
    except Exception as e:
        print(f"[warn] geocode failed for {name}: {e}", file=sys.stderr)
    return None


def build_venues(curated_venues, csv_path):
    """Sheet rows (deduped, in sheet order) merged with curated venues.json entries;
    curated venues without a sheet row (e.g. Paklenica) are appended after."""
    curated = {v["name"]: v for v in curated_venues}
    out, used, seen = [], set(), set()
    for sh in load_sheet_full(csv_path):
        k = _key(sh["area"])
        if not k or k in seen:
            continue
        seen.add(k)
        cname = SHEET_ALIAS.get(k)
        if cname and cname in curated:
            v = dict(curated[cname])
            used.add(cname)
        else:
            g = GAZETTEER.get(k) or geocode(sh["area"])
            if not g:
                print(f"[warn] sheet area '{sh['area']}' has no coords — skipped", file=sys.stderr)
                continue
            v = {"name": sh["area"], "country": sh["country"] or g.get("country", ""),
                 "priority": "7 (from sheet)", "lat": g["lat"], "lon": g["lon"],
                 "rock": g.get("rock", ""), "style": g.get("style", ""), "why": "",
                 "travel": g["travel"], "tidal": g.get("tidal", False), "auto": True}
            # physical character the ranking reads (felt temp / gusts / drying)
            for k in ("aspect", "coastal", "wind_exposed", "drying"):
                if g.get(k) is not None:
                    v[k] = g[k]
        v["sheet"] = sh
        out.append(v)
    for name, v in curated.items():
        if name not in used:
            v = dict(v)
            v["sheet"] = None
            out.append(v)
    return out


def match_sheet_row(name, sheet_rows):
    """Find the spreadsheet row a venue came from by fuzzy-matching its area name."""
    vt = _norm(name)
    for row, area in sheet_rows:
        at = _norm(area)
        if at and all(any(difflib.SequenceMatcher(None, a, x).ratio() >= 0.8 for x in vt) for a in at):
            return row
    return None

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

from core.http import get_json


def _fly(m_to, d_to=None):
    return {"michel": {"mode": "fly", "to": m_to}, "dan": {"mode": "fly", "to": d_to or m_to}}


# Coords + airports for sheet areas (keys = accent-stripped lowercase sheet names,
# in the sheet's own spellings). EVERY sheet row must have an entry here: a row
# without one is skipped, never guessed at (see build_venues).
# Same physical-character vocabulary as venues.json (see its "notes"): aspect /
# coastal / wind_exposed / drying — the ranking reads them for felt temperature,
# gust exposure and how long the rock stays wet.
#
# aspect provenance (2026-09-04, every entry now has one — it draws the compass
# rose on the venue header): corpus/multi-pitch.com route facings for tenerife
# (Cathedral Rock E), vratsa (S), freyr (W), lundy (W), devon (Cornakey S; Culm
# coast W), anti atlas (Amzkhssan S, Ksar SE, Lower Eagle NE, High Sierra S);
# "all" = towers/domes with a wall every way (elbsandstein, meteora, wadi rum,
# campanile basso, mont blonc, spitzkoppe, medina); the rest are curated from
# general knowledge and UNVERIFIED — mallorca (Sa Gubia S/SE), montserrat (S
# side + N side), setesdal (Hægefjell S/SW), loften (Presten W, Vågakallen N),
# zadiel (N–S gorge → E/W walls), sicilly (San Vito: Monte Monaco N, Salinella
# W), carcassonne (S), aladaglar (Demirkazık N face, Parmakkaya E). Correct
# in place when you have been there.
GAZETTEER = {
    # ── areas the spreadsheet names but spells its own way ───────────────────
    # These used to reach build_venues' geocode fallback whenever the trip did
    # not curate the SHEET_ALIAS target by name, and the geocoder placed several
    # of them on the wrong continent — "Aaran" (a typo for Arran) resolved to
    # ‘Arān in Syria and ranked 13th on Aleppo's weather. Coordinates below are
    # taken from the curated trip-ni-july-2026/venues.json entries, not guessed.
    "aaran": dict(lat=55.634, lon=-5.20, rock="granite", style="mountain multi-pitch (Cìr Mhòr)", aspect="S",
                  coastal=True, wind_exposed=True, travel=_fly("GLA")),
    "mournes": dict(lat=54.15, lon=-6.00, rock="granite", style="moderate multi-pitch trad", aspect="SE/NE/SW",
                    wind_exposed=True,
                    travel={"michel": {"mode": "fly", "to": "BFS"}, "dan": {"mode": "local"}}),
    "lake district": dict(lat=54.546, lon=-3.128, rock="volcanic rock", style="large, Full-Range multi-pitch", aspect="SW/N",
                          travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "MAN"}}),
    "cornwall": dict(lat=50.176, lon=-5.62, rock="granite",
                     style="immaculate sea-cliff trad (Bosigran, Chair Ladder)",
                     aspect="NW", coastal=True, tidal=True, wind_exposed=True, drying="fast",
                     travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "NQY"}}),
    "llanberis": dict(lat=53.103, lon=-4.043, rock="rhyolite/dolerite", style="vast, Full-Range multi-pitch", aspect="N/E/SW",
                      drying="slow",
                      travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "MAN"}}),
    "dolomites": dict(lat=46.54, lon=12.137, rock="limestone", style="vast Full-Range multi-pitch", aspect="S/SW/NW",
                      travel=_fly("VCE")),
    "east tyrol": dict(lat=46.829, lon=12.769, rock="limestone/dolomite",
                       style="large, medium-to-hard multi-pitch", aspect="N/S", travel=_fly("INN")),
    "picos europa": dict(lat=43.201, lon=-4.821, rock="limestone",
                         style="moderate-to-hard alpine multi-pitch (Naranjo de Bulnes)", aspect="S/W/E",
                         travel=_fly("BIO")),
    "tenerife": dict(lat=28.27, lon=-16.64, rock="volcanic", style="Cañadas del Teide multi-pitch", aspect="E", travel=_fly("TFS")),
    "mallorca": dict(lat=39.72, lon=2.77, rock="limestone", style="Sa Gubia + sea cliffs", aspect="S/SE", coastal=True, travel=_fly("PMI")),
    "riglos": dict(lat=42.35, lon=-0.73, rock="conglomerate", style="huge overhanging towers", aspect="S", wind_exposed=True, travel=_fly("BCN")),
    "vratsa": dict(lat=43.20, lon=23.55, rock="limestone", style="big limestone walls", aspect="S", travel=_fly("SOF")),
    "elbsandstein": dict(lat=50.91, lon=14.06, rock="sandstone", style="historic sandstone towers", aspect="all", travel=_fly("PRG")),
    "montserrat": dict(lat=41.60, lon=1.81, rock="conglomerate", style="pocketed conglomerate spires", aspect="S/N", travel=_fly("BCN")),
    "freyr": dict(lat=50.22, lon=4.89, rock="limestone", style="Meuse valley slab classics", aspect="W", travel=_fly("BRU")),
    "meteora": dict(lat=39.72, lon=21.63, rock="conglomerate", style="monastery towers, bold conglomerate", aspect="all", travel=_fly("SKG")),
    "anti atlas": dict(lat=29.72, lon=-8.98, rock="quartzite", style="vast desert trad (Tafraout)", aspect="S/SE/NE", travel=_fly("AGA")),
    "bruggler": dict(lat=47.12, lon=8.99, rock="limestone", style="plated limestone slabs", aspect="S", travel=_fly("ZRH")),
    "setesdal": dict(lat=58.9, lon=7.4, rock="granite", style="granite walls & slabs", aspect="S/SW", travel=_fly("KRS")),
    "loften": dict(lat=68.12, lon=13.6, rock="granite", style="arctic granite (Presten, Svolvær)", aspect="W/N", coastal=True, travel=_fly("BOO")),
    "wadi rum": dict(lat=29.57, lon=35.42, rock="sandstone", style="desert big walls, Bedouin routes", aspect="all", travel=_fly("AQJ")),
    "triglav": dict(lat=46.38, lon=13.84, rock="limestone", style="north-face alpine limestone", aspect="N", travel=_fly("LJU")),
    "lundy": dict(lat=51.18, lon=-4.67, rock="granite", style="island sea-cliff granite", aspect="W", tidal=True, coastal=True, wind_exposed=True,
                  travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "BRS"}}),
    "costa blanca": dict(lat=38.63, lon=0.07, rock="limestone", style="Peñón d'Ifach + big ridges", aspect="S", coastal=True, travel=_fly("ALC")),
    "zadiel": dict(lat=48.62, lon=20.83, rock="limestone", style="karst gorge towers", aspect="E/W", travel=_fly("KSC")),
    "calanques": dict(lat=43.21, lon=5.45, rock="limestone", style="sea cliffs above turquoise coves", aspect="S", coastal=True, travel=_fly("MRS")),
    "gredos": dict(lat=40.27, lon=-5.17, rock="granite", style="Galayos granite spires", aspect="W", travel=_fly("MAD")),
    "sicilly": dict(lat=38.17, lon=12.74, rock="limestone", style="San Vito lo Capo sea cliffs", aspect="N/W", coastal=True, travel=_fly("PMO")),
    "campanile basso": dict(lat=46.16, lon=10.87, rock="dolomite", style="Brenta's free-standing tower", aspect="all", travel=_fly("VRN")),
    "mont blonc": dict(lat=45.88, lon=6.89, rock="granite", style="high alpine granite (Chamonix)", aspect="all", travel=_fly("GVA")),
    "spitzkoppe": dict(lat=-21.83, lon=15.19, rock="granite", style="desert granite dome", aspect="all", travel=_fly("WDH")),
    "hoy": dict(lat=58.88, lon=-3.43, rock="sandstone", style="Old Man of Hoy sea stack", aspect="W", coastal=True, wind_exposed=True, travel=_fly("KOI")),
    "isle of white": dict(lat=50.66, lon=-1.30, rock="chalk", style="south-coast sea cliffs", tidal=True, coastal=True, aspect="S",
                          travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "SOU"}}),
    "devon": dict(lat=50.92, lon=-4.56, rock="culm sandstone", style="Culm coast slabs (Wreckers Slab)", aspect="S/W", tidal=True, coastal=True, wind_exposed=True,
                  travel={"michel": {"mode": "drive"}, "dan": {"mode": "fly", "to": "EXT"}}),
    "carcassonne": dict(lat=43.21, lon=2.35, rock="limestone", style="southern France crags", aspect="S", travel=_fly("CCF")),
    "medina": dict(lat=24.47, lon=39.61, rock="granite", style="desert granite", aspect="all", travel=_fly("MED")),
    "aladaglar": dict(lat=37.80, lon=35.15, rock="limestone", style="Turkish alpine limestone", aspect="N/E", travel=_fly("ASR")),
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


def geocode_suggestions(name, count=3):
    """Open-Meteo's free geocoder — a CURATION AID, never a source of truth.

    It used to be build_venues' silent fallback, which is how "Aaran" (the
    spreadsheet's spelling of Arran) came to be ranked as a village near Aleppo,
    and "Lake District" as San Francisco. A place name alone is not enough to
    identify a crag, and being wrong here is invisible: the venue still renders,
    still scores, and simply reports another continent's weather.

    So it now only suggests. When a sheet row has no GAZETTEER entry, the row is
    skipped and these candidates go in the warning, for a human to verify and
    paste into the GAZETTEER."""
    try:
        d = get_json(f"https://geocoding-api.open-meteo.com/v1/search?count={count}&name="
                      + urllib.parse.quote(name))
        return [f"{r['name']}, {r.get('admin1') or ''} {r.get('country') or ''}".strip()
                + f" ({r['latitude']:.3f}, {r['longitude']:.3f})"
                for r in (d.get("results") or [])]
    except Exception as e:
        print(f"[warn] geocode lookup failed for {name}: {e}", file=sys.stderr)
        return []


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
            # Curated coordinates only. An alias that this trip does not curate
            # by name falls through to the GAZETTEER (keyed by the sheet's own
            # spelling) — and if that is missing too, the row is SKIPPED rather
            # than geocoded. Guessing put "Aaran, Scotland" in Syria and "Lake
            # District, England" in San Francisco, silently, for days.
            g = GAZETTEER.get(k)
            if not g:
                hints = geocode_suggestions(sh["area"])
                print(f"[warn] sheet area '{sh['area']}' ({sh['country'] or 'no country'}) "
                      f"has no GAZETTEER entry — SKIPPED, not guessed. "
                      f"Add one to domains/climbing/venues.py keyed '{k}'."
                      + (f" Geocoder suggests: {'; '.join(hints)}" if hints else ""),
                      file=sys.stderr)
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

"""multi-pitch.com route-database lookups — moved verbatim from
update_report.py, with MP_CLIMBS threaded as an explicit parameter instead of
a module-level global mutated by main()."""
import json
import re
import unicodedata

from core.geo import haversine_km
from core.http import get_json
from core.paths import REPO_ROOT

MP_DATA_URL = "https://multi-pitch.com/data/data.json"   # live climb DB (S3-backed)
SITE_URL = "https://multi-pitch.com/"

_GRADE_NORM = {"VDiff": "VD", "V Diff": "VD", "Diff": "D", "Mod": "M", "Moderate": "M",
               "Severe": "S", "Hard Severe": "HS", "Very Severe": "VS", "Hard Very Severe": "HVS"}
GRADE_ORDER = ["M", "D", "VD", "S", "HS", "VS", "HVS", "E1", "E2", "E3", "E4", "E5", "E6", "E7"]


def load_mp_climbs():
    try:
        return get_json(MP_DATA_URL).get("climbs", [])
    except Exception:
        return []


def nearby_climbs(v, mp_climbs, km=50):
    """multi-pitch.com climbs within `km` of the venue, nearest first (from data.json)."""
    out = []
    for c in mp_climbs:
        try:
            la, lo = map(float, c.get("geoLocation", "").split(","))
        except Exception:
            continue
        d = haversine_km(v["lat"], v["lon"], la, lo)
        if d <= km:
            out.append((round(d), c.get("cliff", "?")))
    return sorted(out)


def _climb_flags(c):
    labels = [("seepage", "Seepage after rain"), ("loose", "Loose rock"), ("abseil", "Abseil descent"),
              ("tidal", "Tidal"), ("boat", "Boat approach"), ("polished", "Polished rock")]
    return [txt for key, txt in labels if c.get(key)]


def climb_url(c):
    """Route page on multi-pitch.com. Must match multi-pitch.com's own
    slugifier EXACTLY (website/js/modules/convertNameToURL.js): lowercase,
    drop apostrophes and slashes, spaces -> hyphens — nothing else. An
    earlier version also stripped accents to plain ASCII, which is wrong:
    the real site keeps diacritics literally in the URL (Peñón de Ifach,
    Brüggler, Freÿr do NOT become Penon/Bruggler/Freyr), so that version
    404'd on every accented cliff or route name. Draft routes (not yet
    published on multi-pitch.com) have no live page at all."""
    route, cliff = c.get("routeName") or "", c.get("cliff") or ""
    if not route or not cliff or (c.get("status") or "publish") != "publish":
        return None
    slug = (f"{route.strip()}-on-{cliff.strip()}".lower()
            .replace("'", "").replace("/", "").replace(" ", "-"))
    return SITE_URL + "climbs/" + slug + "/"


# ── which way a climb faces ──────────────────────────────────────────────────
# The live data.json feed doesn't carry `face`; the curated corpus record does
# (corpus/record/**/*.json, the source-stated multi-pitch.com facing), keyed by
# (cliff, route) with the crag's own areas.json aspect as the fallback. Loaded
# once per process.
_CORPUS_FACES = None


def _key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def corpus_faces():
    global _CORPUS_FACES
    if _CORPUS_FACES is None:
        faces, rec = {}, REPO_ROOT / "corpus" / "record"
        try:
            areas = {a["id"]: a for a in json.loads((rec / "areas.json").read_text())["areas"]}
        except Exception:
            areas = {}
        for a in areas.values():
            if a.get("aspect"):
                faces[(_key(a["name"]), None)] = a["aspect"]
        for f in rec.rglob("*.json"):
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            if isinstance(d, dict) and d.get("area_id") and d.get("aspect"):
                cliff = (areas.get(d["area_id"]) or {}).get("name", "")
                faces[(_key(cliff), _key(d.get("name")))] = d["aspect"]
        _CORPUS_FACES = faces
    return _CORPUS_FACES


def climb_face(c):
    """Source-stated facing for a data.json climb: its own `face` if the feed
    ever carries one, else the corpus record for (cliff, route), else the
    crag's aspect. None when nothing states it — never guessed."""
    if c.get("face"):
        return c["face"]
    faces, cliff = corpus_faces(), _key(c.get("cliff"))
    return faces.get((cliff, _key(c.get("routeName")))) or faces.get((cliff, None))


def nearby_climb_cards(v, mp_climbs, km=60, limit=6):
    """Full climb dicts (image + grade + flags) for multi-pitch.com routes near the venue."""
    out = []
    for c in mp_climbs:
        try:
            la, lo = map(float, c.get("geoLocation", "").split(","))
        except Exception:
            continue
        d = haversine_km(v["lat"], v["lon"], la, lo)
        if d <= km:
            img = (c.get("tileImage") or {}).get("url")
            out.append((round(d), {
                "cliff": c.get("cliff", "?"),
                "route": c.get("routeName", ""),
                "grade": c.get("originalGrade") or c.get("tradGrade") or "",
                "tradGrade": c.get("tradGrade", ""),
                "pitches": c.get("pitches"),
                "length": c.get("length"),
                "approach": c.get("approachTime"),
                "appDiff": c.get("approachDifficulty"),
                "face": climb_face(c),   # source-stated facing (compass point) or None
                "dist": round(d),
                "img": (SITE_URL.rstrip("/") + "/" + img) if img else None,
                "url": climb_url(c),
                "flags": _climb_flags(c),
            }))
    out.sort(key=lambda x: x[0])
    return [c for _, c in out[:limit]]


def venue_is_tidal(v, mp_climbs):
    """Crag-level tidal flag: explicit `tidal` on the venue/gazetteer entry, else
    derived from multi-pitch.com route evidence close by. The taxonomy marks
    `tidal` safety-critical (explicit evidence only), so the derivation radius
    stays tight — a tidal route 50 km away says nothing about this crag."""
    if v.get("tidal"):
        return True
    return any("Tidal" in (c.get("flags") or [])
               for c in nearby_climb_cards(v, mp_climbs, km=10))


def _grade_norm(g):
    g = (g or "").strip()
    return _GRADE_NORM.get(g, g)


def grade_range(cards):
    idx = sorted({GRADE_ORDER.index(_grade_norm(c["tradGrade"]))
                  for c in cards if _grade_norm(c.get("tradGrade")) in GRADE_ORDER})
    if not idx:
        return ""
    lo, hi = GRADE_ORDER[idx[0]], GRADE_ORDER[idx[-1]]
    return lo if lo == hi else f"{lo}–{hi}"

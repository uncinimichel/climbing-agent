"""Site & data integrity — the manual inspections, mechanized (testing-plan.md §
"Site & data integrity"; decision #27).

Stdlib `unittest`, fully offline and deterministic — no network, no DB. Each test
class is one of the by-hand checks I kept repeating while building the corpus /
Corpus Inspector / Data Map:

  A  CorpusIntegrity      valid JSON · counts · referential · enums · domains · no-drift
  B  LinkIntegrity        every relative href/src in knowledge/** + the nav resolves
  C  HtmlStructure        standalone pages parse · one <script> · doctype · data-map ids
  D  KnowledgeIndex       every doc is registered; every registered key has a page
  E  GeneratorsWired      nav links in render.py · corpus deploy-copy wired · build_knowledge imports

Run:  python3 engine/tests/test_site_integrity.py
"""
import importlib.util
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KDIR = ROOT / "knowledge"
CORPUS = ROOT / "corpus" / "corpus.json"
CORPUS_DEPLOYED = KDIR / "data" / "corpus.json"
ASPECTS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def taxonomy_enums():
    """Allowed code sets per lookup table, parsed from the taxonomy seed (the
    queryable mirror of taxonomy.md). Each row starts `('code', …)`."""
    sql = _read(ROOT / "corpus" / "sql" / "100_seed_taxonomy.sql")
    ext = ROOT / "corpus" / "sql" / "105_taxonomy_extensions.sql"
    if ext.exists():   # studio-managed values (decision #35) extend the base seed
        sql += "\n" + _read(ext)
    out = {}
    for chunk in re.split(r"INSERT INTO ", sql)[1:]:
        name = re.match(r"(\w+)", chunk).group(1)
        out.setdefault(name, set()).update(re.findall(r"\(\s*'([^']*)'", chunk))
    return out


def load_build_knowledge():
    spec = importlib.util.spec_from_file_location(
        "build_knowledge", ROOT / "trip-ni-july-2026" / "scripts" / "build_knowledge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.links.append(v)


# ── A · corpus data integrity ───────────────────────────────────────────────
class CorpusIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = json.loads(_read(CORPUS))
        cls.areas = {a["id"]: a for a in cls.c["areas"]}
        cls.routes = cls.c["routes"]
        cls.enums = taxonomy_enums()

    def test_shape(self):
        for k in ("schemaVersion", "areas", "routes", "counts"):
            self.assertIn(k, self.c)

    def test_counts_match_reality(self):
        n = self.c["counts"]
        self.assertEqual(n["routes"], len(self.routes))
        self.assertEqual(n["areas"], len(self.c["areas"]))
        self.assertEqual(n["routesCurated"], sum(r["status"] == "publish" for r in self.routes))
        self.assertEqual(n["routesSeeded"], sum(r["status"] == "draft" for r in self.routes))
        self.assertEqual(n.get("routesQuarantined", 0),
                         sum(r["status"] == "quarantined" for r in self.routes))
        self.assertEqual(n["areasCurated"], sum(a["status"] == "publish" for a in self.c["areas"]))

    def test_area_refs_resolve(self):
        for r in self.routes:
            if r.get("area") is not None:
                self.assertIn(r["area"], self.areas, f"route {r['id']} → missing area {r['area']}")

    def test_status_and_grade_domains(self):
        ok = {"publish", "draft", "quarantined"}
        for r in self.routes:
            self.assertIn(r["status"], ok, f"route {r['id']} bad status")
            dg = r.get("dataGrade")
            self.assertTrue(dg is None or (isinstance(dg, int) and 1 <= dg <= 7),
                            f"route {r['id']} dataGrade {dg} out of 1–7")
        for a in self.c["areas"]:
            self.assertIn(a["status"], ok, f"area {a['id']} bad status")

    def test_geolocation_in_range(self):
        for r in self.routes:
            g = r.get("geoLocation")
            if g and g[0] is not None:
                self.assertTrue(-90 <= g[0] <= 90 and -180 <= g[1] <= 180,
                                f"route {r['id']} geo {g} out of range")

    def test_curated_taxonomy_is_in_dictionary(self):
        """Publish (curated) routes must use closed-enum values only — the JSON
        mirror of the DB's FK guard (#18). Draft/seeded rows are unverified by
        design and exempt. Area rock is freeform across sources → not checked here."""
        field_enum = {"gradeSys": "grade_system", "protection": "protection_grade",
                      "incline": "incline", "sunWindow": "sun_window"}
        list_enum = {"disciplines": "discipline", "features": "feature",
                     "character": "character", "hazards": "hazard"}
        bad = []
        for r in self.routes:
            if r["status"] != "publish":
                continue
            for f, tbl in field_enum.items():
                v = r.get(f)
                if v not in (None, "") and v not in self.enums.get(tbl, set()):
                    bad.append(f"{r['id']}.{f}={v!r}")
            for f, tbl in list_enum.items():
                for v in r.get(f) or []:
                    if v not in self.enums.get(tbl, set()):
                        bad.append(f"{r['id']}.{f}={v!r}")
            a = self.areas.get(r.get("area"), {})
            if a.get("aspect") and a["aspect"] not in ASPECTS:
                bad.append(f"{r['id']}.aspect={a['aspect']!r}")
        self.assertEqual(bad, [], f"off-dictionary values on curated routes: {bad}")

    def test_deployed_copy_has_no_drift(self):
        self.assertTrue(CORPUS_DEPLOYED.exists(), "served copy missing — run build_corpus.py")
        self.assertEqual(_read(CORPUS), _read(CORPUS_DEPLOYED),
                         "corpus/corpus.json != knowledge/data/corpus.json — re-run build_corpus.py")


# ── B · link integrity ──────────────────────────────────────────────────────
class LinkIntegrity(unittest.TestCase):
    def _check(self, html_path):
        p = _Links()
        p.feed(_read(html_path))
        missing = []
        for link in p.links:
            if re.match(r"^(https?:|mailto:|data:|#|javascript:)", link):
                continue
            target = link.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            if not (html_path.parent / target).resolve().exists():
                missing.append(link)
        self.assertEqual(missing, [], f"{html_path.relative_to(ROOT)} → broken links: {missing}")

    def test_knowledge_html_links_resolve(self):
        for html_path in sorted(KDIR.rglob("*.html")):
            with self.subTest(page=str(html_path.relative_to(ROOT))):
                self._check(html_path)

    def test_render_nav_targets_exist(self):
        nav = re.findall(r'href="(knowledge/[^"]+\.html)"', _read(ROOT / "engine" / "render.py"))
        self.assertTrue(nav, "no knowledge/* nav links found in render.py")
        for href in nav:
            self.assertTrue((ROOT / href).exists(), f"nav link target missing: {href}")


# ── C · html structure ──────────────────────────────────────────────────────
class HtmlStructure(unittest.TestCase):
    STANDALONE = ["corpus-inspector.html", "data-dependencies.html"]

    def test_standalone_pages_well_formed(self):
        for name in self.STANDALONE:
            src = _read(KDIR / name)
            with self.subTest(page=name):
                HTMLParser().feed(src)  # raises on malformed
                self.assertTrue(src.lstrip().lower().startswith("<!doctype"), "missing doctype")
                self.assertEqual(src.count("<script"), 1, "expected exactly one <script>")
                self.assertIn("<title>", src)
                self.assertIn('name="viewport"', src)

    def test_data_map_edges_reference_real_nodes(self):
        src = _read(KDIR / "data-dependencies.html")
        ids = set(re.findall(r'id="([a-zA-Z]\w*)"', src))
        edges = re.findall(r"\['(\w+)','(\w+)','\w+'\]", src)
        self.assertTrue(edges, "no EDGES found in data-dependencies.html")
        missing = {n for a, b in edges for n in (a, b) if n not in ids}
        self.assertEqual(missing, set(), f"edges point at undefined node ids: {missing}")


# ── D · knowledge-index completeness ────────────────────────────────────────
class KnowledgeIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bk = load_build_knowledge()
        cls.grouped = {k for _, keys in cls.bk.GROUPS for k in keys}

    def test_every_doc_is_registered(self):
        for md in sorted(KDIR.rglob("*.md")):
            key = md.relative_to(KDIR).with_suffix("").as_posix()
            with self.subTest(doc=key):
                self.assertIn(key, self.bk.TITLES, f"{key} missing from TITLES")
                self.assertIn(key, self.grouped, f"{key} not in any GROUPS group")

    def test_every_registered_key_has_a_page(self):
        for key in self.grouped:
            with self.subTest(key=key):
                self.assertTrue((KDIR / f"{key}.html").exists(),
                                f"index links {key}.html but the page is missing")


# ── F · venue character fields ──────────────────────────────────────────────
class VenueCharacter(unittest.TestCase):
    """The ranking reads physical-character fields off every venue entry
    (aspect / coastal / wind_exposed / drying / tidal — see venues.json
    "notes"). Guard both curated sources so a typo can't silently become a
    no-op in scoring (an unknown aspect falls back to the mild sun bump)."""
    DRYING = {"fast", "slow"}
    BOOLS = ("coastal", "wind_exposed", "tidal")

    def _check(self, entries, label):
        bad = []
        for name, v in entries:
            if v.get("aspect") and v["aspect"].upper() not in ASPECTS:
                bad.append(f"{label}:{name}.aspect={v['aspect']!r}")
            if v.get("drying") and v["drying"].lower() not in self.DRYING:
                bad.append(f"{label}:{name}.drying={v['drying']!r}")
            for f in self.BOOLS:
                if f in v and not isinstance(v[f], bool):
                    bad.append(f"{label}:{name}.{f}={v[f]!r} (not bool)")
        self.assertEqual(bad, [], f"bad venue character fields: {bad}")

    def test_venues_json_fields(self):
        cfg = json.loads(_read(ROOT / "trip-ni-july-2026" / "venues.json"))
        self._check([(v["name"], v) for v in cfg["venues"]], "venues.json")

    def test_gazetteer_fields(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from engine.sheet_venues import GAZETTEER
        self._check(list(GAZETTEER.items()), "GAZETTEER")

    def test_new_tag_kinds_in_spec(self):
        spec = json.loads(_read(KDIR / "data" / "tag-spec.json"))
        kinds = {t["k"] for t in spec["tags"]}
        for k in ("aspect", "coastal", "windex", "drying"):
            self.assertIn(k, kinds, f"tag kind {k!r} missing from tag-spec.json")


# ── E · generators wired ────────────────────────────────────────────────────
class GeneratorsWired(unittest.TestCase):
    def test_nav_links_in_render(self):
        src = _read(ROOT / "engine" / "render.py")
        for href in ("knowledge/corpus-inspector.html", "knowledge/data-dependencies.html"):
            self.assertIn(href, src, f"{href} not wired into the homepage nav")

    def test_corpus_deploy_copy_is_wired(self):
        src = _read(ROOT / "corpus" / "tools" / "build_corpus.py")
        self.assertIn("DEPLOY_OUT", src)
        self.assertIn("knowledge", src, "build_corpus.py must also emit the served copy")

    def test_build_knowledge_imports(self):
        bk = load_build_knowledge()
        self.assertTrue(bk.TITLES and bk.GROUPS)


if __name__ == "__main__":
    unittest.main(verbosity=2)

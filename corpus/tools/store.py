"""The JSON record store — what replaced Postgres (decision #39).

The record under corpus/record/ IS the database: one self-contained JSON document
per route, plus taxonomies/grades/areas/topos. This module loads it into
memory, answers queries, validates writes against schemas generated FROM the
taxonomy files (an off-vocabulary tag fails like an FK violation used to),
and persists atomically (tmp+rename, stable key order for honest git diffs).

Integrity model, mirroring what the Postgres schema enforced:
  - enum membership for every tag family      → JSON Schema enums (generated)
  - publish ⇒ tagged_by == human              → if/then conditional schema
  - safety-critical hazards need evidence     → checked in validate()
  - referential integrity (area ids, topo→route) → lint()
Single-writer by design (one Studio process); the record syncs to S3+git.
"""
from __future__ import annotations

import json
import os
import re
import struct
import threading
import unicodedata
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
# S3 mode (browser Studio, decision #40 phase B): RECORD_BUCKET set ⇒ the
# record loads from and writes to S3; the local dir is a warm cache (/tmp in
# Lambda). No bucket ⇒ pure local files, exactly as before.
RECORD_BUCKET = os.environ.get("RECORD_BUCKET")
REC_DIR = Path(os.environ.get("RECORD_DIR",
               "/tmp/record" if RECORD_BUCKET else ROOT / "corpus" / "record"))

_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3

_LOCK = threading.RLock()


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    body = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    tmp.write_text(body)
    tmp.replace(path)
    if RECORD_BUCKET:      # the bucket is the truth; local is the warm cache
        s3().put_object(Bucket=RECORD_BUCKET,
                        Key=f"record/{path.relative_to(REC_DIR)}",
                        Body=body.encode(), ContentType="application/json")


def _delete(path: Path) -> None:
    path.unlink(missing_ok=True)
    if RECORD_BUCKET:
        s3().delete_object(Bucket=RECORD_BUCKET, Key=f"record/{path.relative_to(REC_DIR)}")


def hydrate_from_s3() -> None:
    """Cold start: pull every record JSON (not media) from S3 into the cache."""
    from concurrent.futures import ThreadPoolExecutor
    keys = []
    token = None
    while True:
        kw = {"Bucket": RECORD_BUCKET, "Prefix": "record/"}
        if token:
            kw["ContinuationToken"] = token
        resp = s3().list_objects_v2(**kw)
        keys += [o["Key"] for o in resp.get("Contents", [])
                 if o["Key"].endswith(".json") and "/media/" not in o["Key"]]
        token = resp.get("NextContinuationToken")
        if not token:
            break

    def fetch(k):
        dest = REC_DIR / Path(k).relative_to("record")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(s3().get_object(Bucket=RECORD_BUCKET, Key=k)["Body"].read())
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(fetch, keys))


def media_url(uri: str, expires: int = 3600) -> str:
    """Where the browser loads a photo from: presigned S3 GET in cloud mode
    (private bucket, no Lambda bandwidth, no 6MB cap), the local mount
    otherwise."""
    if RECORD_BUCKET:
        # only ever presign media objects — a stray uri must not become a
        # 1-hour public link to record JSONs or backups
        if not (uri.startswith("record/") and "/media/" in uri and ".." not in uri):
            return ""
        return s3().generate_presigned_url(
            "get_object", Params={"Bucket": RECORD_BUCKET, "Key": uri},
            ExpiresIn=expires)
    return "/" + uri


def wkb_latlon(hexstr: str) -> tuple[float, float]:
    """(lat, lon) from a PostGIS EWKB hex point — parkings exported from Postgres
    kept their geom column; decode it here rather than re-export the record."""
    b = bytes.fromhex(hexstr)
    fmt = "<" if b[0] == 1 else ">"
    lon, lat = struct.unpack_from(fmt + "2d", b, 9)   # byte order + type + SRID = 9 bytes
    return lat, lon


def slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "route")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "route"


class Store:
    def __init__(self, rec_dir: Path = REC_DIR):
        self.dir = Path(rec_dir)
        self.reload()

    # ── loading ────────────────────────────────────────────────────────────
    def reload(self):
        with _LOCK:
            if RECORD_BUCKET and not (self.dir / "taxonomies.json").exists():
                hydrate_from_s3()
            self.tax = json.loads((self.dir / "taxonomies.json").read_text())["taxonomies"]
            self.grades = json.loads((self.dir / "grades.json").read_text())
            adoc = json.loads((self.dir / "areas.json").read_text())
            self.areas = {a["id"]: a for a in adoc["areas"]}
            self.area_refs = adoc.get("references", [])
            self.routes = {}
            self._route_files = {}
            # route documents live at hierarchical keys (decision #40:
            # country/region/crag/route.json); the legacy flat routes/ dir is
            # still read so the migration itself can load the old layout
            ROOT_DOCS = {"taxonomies.json", "grades.json", "areas.json", "topos.json",
                         "crawl-frontier.json", "external-refs-nonroute.json", "manifest.json"}
            for f in sorted(self.dir.rglob("*.json")):
                rel = f.relative_to(self.dir)
                if (len(rel.parts) == 1 and rel.name in ROOT_DOCS) or "media" in rel.parts:
                    continue
                if not (rel.parts[0] == "routes" or len(rel.parts) >= 4):
                    continue
                r = json.loads(f.read_text())
                for pk in r.get("parkings", []):       # legacy PostGIS geom → plain lat/lon
                    if pk.get("lat") is None and pk.get("geom"):
                        pk["lat"], pk["lon"] = wkb_latlon(pk["geom"])
                self.routes[r["id"]] = r
                self._route_files[r["id"]] = f
            tdoc = json.loads((self.dir / "topos.json").read_text())
            self.topos = tdoc["topos"]
            self._schema = self._build_schema()
            self._resolve_areas()
            self._number_topos()

    # topos were exported on natural keys (uri, area name); the UI addresses
    # /api/topo/{id}, so ids are assigned once here and persisted — stable
    # from then on because new uploads take max+1.
    def _number_topos(self):
        by_name = {a["name"]: a["id"] for a in self.areas.values()}
        dirty = False
        next_id = max((t.get("id", 0) for t in self.topos), default=0) + 1
        for t in self.topos:
            if "id" not in t:
                t["id"], next_id, dirty = next_id, next_id + 1, True
            if "area_id" not in t:
                t["area_id"], dirty = by_name.get(t.get("area_name")), True
        if dirty:
            self.save_topos()

    # inheritance the old area_resolved/route_resolved views computed ---------
    def _resolve_areas(self):
        def chain(aid):
            seen, out = set(), []
            while aid and aid not in seen and aid in self.areas:
                seen.add(aid)
                out.append(self.areas[aid])
                aid = self.areas[aid].get("parent_id")
            return out
        self._area_chain = {aid: chain(aid) for aid in self.areas}
        for aid, ch in self._area_chain.items():
            a = self.areas[aid]
            a["path_tokens"] = [x["name"] for x in reversed(ch)]
            for field in ("rock_code", "aspect", "grade_context", "timezone"):
                a["eff_" + field] = next((x.get(field) for x in ch if x.get(field)), None)

    def area_chain(self, aid):
        """Area dicts from aid up to the root (self first)."""
        return self._area_chain.get(aid) or []

    def route_effective(self, r):
        """eff_* fields a route inherits from its area chain (own value wins)."""
        ch = self._area_chain.get(r.get("area_id")) or []
        eff = {}
        for field in ("rock_code", "aspect", "grade_context"):
            eff["eff_" + field] = r.get(field) or next(
                (x.get(field) for x in ch if x.get(field)), None)
        eff["path_tokens"] = ([x["name"] for x in reversed(ch)] + [r["name"]])[:-1]
        return eff

    # ── schema generation: the taxonomy IS the constraint ─────────────────
    def _codes(self, fam):
        key = "code" if self.tax[fam] and "code" in self.tax[fam][0] else "id"
        return [t[key] for t in self.tax[fam]]

    def _build_schema(self):
        enum = {
            "discipline": self._codes("discipline"),
            "feature": self._codes("feature"),
            "character": self._codes("character"),
            "hazard": self._codes("hazard"),
            "rock": self._codes("rock_type"),
            "sun_window": self._codes("sun_window"),
            "protection": self._codes("protection_grade"),
            "incline": self._codes("incline"),
            "commitment": self._codes("commitment_grade"),
            "grade_system": [g["code"] for g in self.grades["systems"]],
            "source": self._codes("source"),
        }
        opt = lambda vals: {"anyOf": [{"type": "null"}, {"enum": vals}]}  # noqa: E731
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["id", "name", "area_id", "status", "tagged_by"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string", "minLength": 1},
                "area_id": {"type": "integer"},
                "status": {"enum": ["draft", "publish", "quarantined"]},
                "tagged_by": {"enum": ["human", "llm", "source"]},
                "rock_code": opt(enum["rock"]),
                "incline_code": opt(enum["incline"]),
                "sun_window_code": opt(enum["sun_window"]),
                "protection_code": opt(enum["protection"] + ["UNSPECIFIED"]),
                "commitment_code": opt(enum["commitment"]),
                "grade_system_code": opt(enum["grade_system"]),
                "tags": {
                    "type": "object",
                    "properties": {
                        "disciplines": {"type": "array", "items": {"enum": enum["discipline"]}},
                        "features": {"type": "array", "items": {"enum": enum["feature"]}},
                        "character": {"type": "array", "items": {"enum": enum["character"]}},
                    },
                },
                "hazards": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"hazard_code": {"enum": enum["hazard"]}},
                    "required": ["hazard_code"],
                }},
                "external_refs": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"source_id": {"enum": enum["source"]}},
                }},
            },
            # governance #32: a publish row must be human-tagged — the CHECK
            # constraint, relocated
            "if": {"properties": {"status": {"const": "publish"}}},
            "then": {"properties": {"tagged_by": {"const": "human"}}},
        }

    def validate(self, route: dict):
        """Raises ValueError with a curator-readable message on violation."""
        try:
            jsonschema.validate(route, self._schema)
        except jsonschema.ValidationError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "route"
            raise ValueError(f"{path}: {e.message}") from None
        crit = {h["code"] for h in self.tax["hazard"] if h.get("safety_critical")}
        for h in route.get("hazards", []):
            if h["hazard_code"] in crit and not (h.get("evidence_span") or "").strip():
                raise ValueError(
                    f"hazard '{h['hazard_code']}' is safety-critical — evidence is required")
        if route.get("area_id") not in self.areas:
            raise ValueError(f"area {route.get('area_id')} does not exist")

    # ── writes (atomic, validated) ─────────────────────────────────────────
    # ── hierarchical keys (decision #40) ───────────────────────────────────
    def crag_prefix(self, area_id):
        """(country/region/crag slug prefix, sector name) for an area — the
        crag is the TOPMOST sector/crag node below the region (kind labels
        are unreliable); no such node ⇒ the region doubles as crag (Lundy)."""
        ch = self.area_chain(area_id)
        below = [a for a in ch if a["kind"] in ("sector", "crag")]
        crag = below[-1] if below else next((a for a in ch if a["kind"] == "region"), None)
        country = next((a for a in ch if a["kind"] == "country"), None)
        region = next((a for a in ch if a["kind"] == "region"), None)
        sector = below[0]["name"] if len(below) > 1 else None
        return ("/".join([slug(country["name"]) if country else "unknown",
                          slug(region["name"]) if region else "unsorted",
                          slug(crag["name"]) if crag else "unknown"]), sector)

    def route_rel(self, route) -> Path:
        """The route's canonical file path. Filename collisions (duplicate
        route names in one crag = the MP-vs-crawl dedup backlog) get the
        UKC-style -<id> suffix; identity is the id INSIDE the document."""
        prefix, _ = self.crag_prefix(route["area_id"])
        base = self.dir / prefix / f"{slug(route['name'])}.json"
        clash = next((rid for rid, f in self._route_files.items()
                      if f == base and rid != route["id"]), None)
        if clash is not None:
            base = self.dir / prefix / f"{slug(route['name'])}-{route['id']}.json"
        return base

    def save_route(self, route: dict):
        with _LOCK:
            self.validate(route)
            rid = route["id"]
            old = self.routes.get(rid)
            target = self.route_rel(route)
            current = self._route_files.get(rid)
            _dump(target, route)
            if current and current != target:      # renamed/moved: relocate the file
                _delete(current)
            if old and old.get("name") != route["name"]:
                # topo lines key on route name — keep them pointing at this route
                changed = False
                for t in self.topos:
                    for ln in t.get("lines", []):
                        if ln.get("route_name") == old["name"]:
                            ln["route_name"] = route["name"]
                            changed = True
                if changed:
                    self.save_topos()
            self.routes[rid] = route
            self._route_files[rid] = target

    def new_route_id(self) -> int:
        return (max(self.routes) + 1) if self.routes else 1

    # ── topo lookups (lines are keyed by route NAME — the export's natural key) ─
    def topo(self, tid: int) -> dict | None:
        return next((t for t in self.topos if t.get("id") == tid), None)

    def new_topo_id(self) -> int:
        return max((t.get("id", 0) for t in self.topos), default=0) + 1

    def find_route(self, name: str, area_name: str | None = None) -> dict | None:
        """Resolve a topo line's (route_name, route_area) to a route — names
        repeat across crags (four 'Hurricane's), so the area disambiguates."""
        hits = [r for r in self.routes.values() if r["name"] == name]
        if area_name and len(hits) > 1:
            scoped = [r for r in hits
                      if self.areas.get(r["area_id"], {}).get("name") == area_name]
            hits = scoped or hits
        return hits[0] if hits else None

    def save_topos(self):
        with _LOCK:
            _dump(self.dir / "topos.json", {"schema": 1, "topos": self.topos})

    def save_taxonomies(self):
        with _LOCK:
            _dump(self.dir / "taxonomies.json", {"schema": 1, "taxonomies": self.tax})
            self._schema = self._build_schema()

    def save_areas(self):
        with _LOCK:
            _dump(self.dir / "areas.json",
                  {"schema": 1, "areas": [self.areas[k] for k in sorted(self.areas)],
                   "references": self.area_refs})
            self._resolve_areas()

    # ── the referential lint (what JSON Schema cannot say) ─────────────────
    def lint(self) -> list[str]:
        problems = []
        for r in self.routes.values():
            if r.get("area_id") not in self.areas:
                problems.append(f"route {r['id']} '{r['name']}': missing area {r.get('area_id')}")
            try:
                self.validate(r)
            except ValueError as e:
                problems.append(f"route {r['id']} '{r['name']}': {e}")
        for a in self.areas.values():
            p = a.get("parent_id")
            if p is not None and p not in self.areas:
                problems.append(f"area {a['id']} '{a['name']}': missing parent {p}")
        names = {}
        for t in self.topos:
            for ln in t.get("lines", []):
                key = ln["route_name"]
                names.setdefault(key, 0)
                if not any(r["name"] == key for r in self.routes.values()):
                    problems.append(f"topo '{t.get('title')}': line for unknown route '{key}'")
        return problems


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store

#!/usr/bin/env python3
"""One-off (decision #40): restructure the record onto hierarchical keys.

  routes/NNNN-slug.json  →  country/region/crag/route-slug[-id].json
  corpus/uploads/topos/**    →  country/region/crag/media/<file>   (co-location)

Path rules live in store.crag_prefix()/route_rel() (topmost sector/crag node
below the region = the crag; collisions -<id>-suffixed = the MP-vs-crawl
dedup backlog; region doubles as crag when nothing sits below it). Also
rewrites topos.json uris to the new media locations and stamps the sector
attribute onto routes that sat inside sector nodes.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REC = ROOT / "corpus" / "record"
UPLOADS = ROOT / "corpus" / "uploads" / "topos"


def main():
    s = Store()
    moved = 0
    for r in sorted(s.routes.values(), key=lambda x: x["id"]):
        _, sector = s.crag_prefix(r["area_id"])
        if sector and not r.get("sector"):
            r["sector"] = sector
        s.save_route(r)                      # relocates to the canonical path
        moved += 1
    legacy = REC / "routes"
    if legacy.exists() and not any(legacy.iterdir()):
        legacy.rmdir()

    media = 0
    for t in s.topos:
        prefix, _ = s.crag_prefix(t.get("area_id"))
        uri = t.get("uri") or ""
        name = Path(uri).name
        dest_dir = REC / prefix / "media"
        if uri.startswith("uploads/topos/"):
            src_dir = ROOT / "corpus" / Path(uri).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            for f in src_dir.glob(f"{Path(name).stem}*"):   # original + variants
                shutil.copy2(f, dest_dir / f.name)
                media += 1
            t["uri"] = f"record/{prefix}/media/{name}"
        elif uri.startswith("record/"):
            pass                              # already migrated
    s.save_topos()
    print(f"relocated {moved} routes, co-located {media} media files")
    print("corpus/uploads/topos/ kept as a safety copy — delete after verifying")


if __name__ == "__main__":
    main()

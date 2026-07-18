#!/usr/bin/env bash
# PUBLISH (decisions #39/#40): compile the published subset of the record
# into the serving artifacts, and put them everywhere consumers look.
#
#   1. lint the whole record (blocking)
#   2. build corpus.json (+ the knowledge/data copy) from published routes
#   3. build manifest.json — the published index (id, path, name, grade,
#      crag chain) that a browser Studio/website fetches in ONE GET
#   4. push record+manifest to S3, and remind to commit the artifacts to git
#      (decision Q4: the artifact lives in BOTH git and S3; the working
#      record lives only in S3)
set -euo pipefail
cd "$(dirname "$0")"
PY=../agent/.venv/bin/python

"$PY" tools/lint_record.py

"$PY" tools/build_corpus.py

"$PY" - <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, "tools")
from store import Store
s = Store()
entries = []
for r in s.routes.values():
    if r.get("status") != "publish":
        continue
    rel = s.route_rel(r).relative_to(s.dir)
    entries.append({"id": r["id"], "path": str(rel), "name": r["name"],
                    "grade": r.get("original_grade"), "stars": r.get("stars"),
                    "crag": "/".join(str(rel).split("/")[:3])})
entries.sort(key=lambda e: e["path"])
out = {"schema": 1, "published": len(entries), "routes": entries}
Path("record/manifest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print(f"manifest.json: {len(entries)} published routes")
EOF

./sync.sh push
echo "== now commit the artifacts:  git add db/corpus.json knowledge/data/corpus.json && git commit"

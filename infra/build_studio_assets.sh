#!/usr/bin/env bash
# Build the two deployable artifacts for the StudioStack:
#   lambda-build/  the API bundle (the SAME app the local Studio runs) with
#                  manylinux wheels so Pillow etc. work on Lambda x86_64
#   ui-build/      the static Studio UI: index.html (curate_ui.html verbatim,
#                  plus a config.js include) — config.js itself is written at
#                  deploy time with the real API URL + Cognito ids
set -euo pipefail
cd "$(dirname "$0")"

rm -rf lambda-build ui-build
mkdir -p lambda-build ui-build

python3 -m pip install -q \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 \
  --only-binary=:all: --target lambda-build \
  "fastapi==0.139.0" "mangum==0.19.0" "jsonschema==4.25.1" \
  "pillow==12.2.0" "python-multipart==0.0.32" "pydantic==2.13.4"

cp ../corpus/tools/{curate.py,topo_api.py,store.py,images.py,curate_ui.html} lambda-build/
cat > lambda-build/handler.py <<'PY'
from mangum import Mangum
from curate import app
handler = Mangum(app)
PY

# UI: same file, plus the deploy-time config include injected before its script
sed 's|<title>Curation Studio</title>|<title>Curation Studio</title>\n<script src="config.js"></script>|' \
  ../corpus/tools/curate_ui.html > ui-build/index.html

echo "lambda-build: $(du -sh lambda-build | cut -f1) · ui-build ready"

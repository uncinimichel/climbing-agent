#!/usr/bin/env bash
# The Curation Studio — runs directly on the JSON record (decision #39).
# No database, no Docker: db/record/ is the source of truth, synced to S3 +
# git by ./sync.sh. First run: python3 -m venv ../agent/.venv &&
# ../agent/.venv/bin/pip install -r tools/requirements.txt
set -euo pipefail
cd "$(dirname "$0")/tools"
echo "→ Curation Studio on http://localhost:8890 — record: db/record/ (JSON is the database)"
exec ../../agent/.venv/bin/uvicorn curate:app --port 8890

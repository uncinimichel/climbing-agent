#!/usr/bin/env bash
# Sync the JSON record (the source of truth, decision #39) with S3.
#
#   ./sync.sh push    validate, then record/ + photos → S3 (and remind to git commit)
#   ./sync.sh pull    S3 → record/ + photos (a fresh machine catches up)
#
# S3 layout (versioned, encrypted bucket):
#   s3://climbing-agent-db-backups-166832185275/record/   the JSON record
#   s3://climbing-agent-db-backups-166832185275/media/    topo photos (not in git — 90MB+)
set -euo pipefail
cd "$(dirname "$0")"

BUCKET=s3://climbing-agent-db-backups-166832185275
PY=../agent/.venv/bin/python

case "${1:-}" in
  push)
    echo "== validating the record before it becomes the truth"
    "$PY" tools/lint_record.py
    aws s3 sync record/ "$BUCKET/record/" --delete
    aws s3 sync uploads/topos/ "$BUCKET/media/topos/" --exclude "*.tmp"
    echo "== pushed. Now: git add db/record && git commit — git is the readable history"
    ;;
  pull)
    aws s3 sync "$BUCKET/record/" record/
    aws s3 sync "$BUCKET/media/topos/" uploads/topos/
    "$PY" tools/lint_record.py
    echo "== pulled and validated"
    ;;
  *)
    echo "usage: ./sync.sh push|pull"; exit 1;;
esac

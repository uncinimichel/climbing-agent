#!/usr/bin/env bash
# Sync the JSON record (the source of truth, decisions #39/#40) with S3.
# The record is NOT in git — S3 versioning is its history. Photos co-locate
# under each crag's media/ prefix, so one sync moves everything.
#
#   ./sync.sh push    validate, then record/ (JSON + media) → S3
#   ./sync.sh pull    S3 → record/ (a fresh machine catches up)
set -euo pipefail
cd "$(dirname "$0")"

BUCKET=s3://climbing-agent-db-backups-166832185275
PY=../agent/.venv/bin/python

case "${1:-}" in
  push)
    echo "== validating the record before it becomes the truth"
    "$PY" tools/lint_record.py
    aws s3 sync record/ "$BUCKET/record/" --delete
    echo "== pushed (S3 versioning keeps every prior state)"
    ;;
  pull)
    aws s3 sync "$BUCKET/record/" record/
    "$PY" tools/lint_record.py
    echo "== pulled and validated"
    ;;
  *)
    echo "usage: ./sync.sh push|pull"; exit 1;;
esac

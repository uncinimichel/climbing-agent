#!/usr/bin/env bash
# Re-apply the full schema + seeds to the running climbing-db container.
# 001_extensions.sql drops and recreates the `climbing` schema, so this is a
# rebuild-from-scratch every time (data in the climbing schema is discarded).
set -euo pipefail
cd "$(dirname "$0")"

C=${CONTAINER:-climbing-db}

for f in sql/*.sql; do
    echo "== applying $f"
    docker exec -i "$C" psql -q -v ON_ERROR_STOP=1 -U climbing -d climbing < "$f"
done
echo "== schema applied"

#!/usr/bin/env bash
# Run the smoke test against the running climbing-db container.
# Inserts the taxonomy.md example route, checks enum/evidence/inheritance/geo/grade
# behaviour, then rolls back — leaves no data behind.
set -euo pipefail
cd "$(dirname "$0")"

C=${CONTAINER:-climbing-db}
docker exec -i "$C" psql -v ON_ERROR_STOP=1 -U climbing -d climbing < smoke/smoke_test.sql

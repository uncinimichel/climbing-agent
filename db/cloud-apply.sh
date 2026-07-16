#!/usr/bin/env bash
# Apply the full schema + seeds to the CLOUD corpus DB (Aurora Serverless v2,
# decision #36), then restore data from corpus.json — the cloud twin of
# `./apply.sh && ingest_corpus.py`. Reads credentials from Secrets Manager
# (climbing-agent/corpus-db) and runs psql through the local climbing-db
# container, so no local psql install is needed.
#
# ⚠ Same caveat as apply.sh: 001_extensions.sql drops and recreates the
# climbing schema — this is a rebuild-from-scratch of the CLOUD copy.
# The cluster scales to zero when idle; the first statement may take ~15s
# while it resumes.
set -euo pipefail
cd "$(dirname "$0")"

SECRET_ID=${SECRET_ID:-climbing-agent/corpus-db}
REGION=${AWS_REGION:-eu-west-2}
C=${CONTAINER:-climbing-db}

eval "$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" \
  --query SecretString --output text | python3 -c '
import json, sys
s = json.load(sys.stdin)
print("HOST=%s\nPORT=%s\nPGUSER=%s\nPGPASS=%s"
      % (s["host"], s["port"], s["username"], s["password"]))')"

DSN="postgresql://$PGUSER:$PGPASS@$HOST:$PORT/climbing?sslmode=require"

for f in sql/*.sql; do
    echo "== applying $f"
    docker exec -i "$C" psql -q -v ON_ERROR_STOP=1 "$DSN" < "$f"
done
echo "== schema + seeds applied to $HOST"

# corpus.json currently carries a few refs from the local-dev fixture source
# (dev/sample_routes.sql); seed just its source row so the restore's FKs hold.
docker exec -i "$C" psql -q -v ON_ERROR_STOP=1 "$DSN" <<'SQL'
INSERT INTO source (id, name, type, method, license, tos, regions, cadence, teaches)
VALUES ('dev-fixtures', 'Dev fixtures', 'route-db', 'manual', 'n/a', 'owned', '{*}', 'manual', 'local development only')
ON CONFLICT (id) DO NOTHING;
SQL

DATABASE_URL="$DSN" ../agent/.venv/bin/python tools/ingest_corpus.py
echo "== corpus restored to the cloud DB"

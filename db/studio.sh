#!/usr/bin/env bash
# Launch the Curation Studio against the DATABASE OF RECORD (decision #38:
# the cloud DB is the source of truth; your laptop is a disposable copy).
#
#   ./studio.sh            → Studio on :8890 against the CLOUD (the default)
#   ./studio.sh local      → Studio on :8890 against the local Docker DB
#                            (offline/dev copy — refresh it from a cloud dump)
set -euo pipefail
cd "$(dirname "$0")/tools"

PY=../../agent/.venv/bin/uvicorn
if [ "${1:-cloud}" = "local" ]; then
    echo "→ Studio against the LOCAL copy (postgres://…@localhost) — remember: cloud is the record"
    exec "$PY" curate:app --port 8890
fi

eval "$(aws secretsmanager get-secret-value --secret-id climbing-agent/corpus-db \
  --region eu-west-2 --query SecretString --output text | python3 -c '
import json, sys
s = json.load(sys.stdin)
print("H=%s\nP=%s\nU=%s\nPW=%s" % (s["host"], s["port"], s["username"], s["password"]))')"
CA=/tmp/rds-eu-west-2-ca.pem
[ -s "$CA" ] || curl -sf "https://truststore.pki.rds.amazonaws.com/eu-west-2/eu-west-2-bundle.pem" -o "$CA"
echo "→ Studio on http://localhost:8890 against the CLOUD (database of record)"
echo "  first request after idle may take ~15s while the cluster resumes"
exec env DATABASE_URL="postgresql://$U:$PW@$H:$P/climbing?sslmode=verify-full&sslrootcert=$CA" \
    "$PY" curate:app --port 8890

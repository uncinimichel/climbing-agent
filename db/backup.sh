#!/usr/bin/env bash
# Full-fidelity dump of the corpus DB into db/backups/ — commit the result.
#
# Why this exists alongside corpus.json: the corpus export carries routes/
# areas/pitches/taxonomies, but NOT the topo layer (media/topo/topo_line —
# the drawn lines). A pg_dump carries literally everything, compresses to a
# few hundred KB, and git history becomes the complete archive.
#
#   ./backup.sh            dump the LOCAL DB (default)
#   ./backup.sh cloud      dump the CLOUD DB (reads the Secrets Manager DSN)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups

STAMP=$(date +%Y%m%d-%H%M)
if [ "${1:-local}" = "cloud" ]; then
    eval "$(aws secretsmanager get-secret-value --secret-id climbing-agent/corpus-db \
      --region eu-west-2 --query SecretString --output text | python3 -c '
import json, sys
s = json.load(sys.stdin)
print("H=%s\nP=%s\nU=%s\nPW=%s" % (s["host"], s["port"], s["username"], s["password"]))')"
    CA=/tmp/rds-eu-west-2-ca.pem
    [ -s "$CA" ] || curl -sf "https://truststore.pki.rds.amazonaws.com/eu-west-2/eu-west-2-bundle.pem" -o "$CA"
    docker cp "$CA" climbing-db:/tmp/rds-ca.pem >/dev/null
    OUT="backups/cloud-$STAMP.sql.gz"
    docker exec climbing-db pg_dump \
      "postgresql://$U:$PW@$H:$P/climbing?sslmode=verify-full&sslrootcert=/tmp/rds-ca.pem" \
      --clean --if-exists | gzip > "$OUT"
else
    OUT="backups/local-$STAMP.sql.gz"
    docker exec climbing-db pg_dump -U climbing -d climbing --clean --if-exists | gzip > "$OUT"
fi
echo "wrote $OUT ($(du -h "$OUT" | cut -f1)) — commit it. Restore with:"
echo "  gunzip -c $OUT | docker exec -i climbing-db psql -q [-v ON_ERROR_STOP=0] <local dsn or cloud DSN>"

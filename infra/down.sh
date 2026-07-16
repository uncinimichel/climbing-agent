#!/usr/bin/env bash
# Tear down the AWS infrastructure.
#
#   ./down.sh          destroy the corpus DB stack + its leftover final
#                      snapshot(s). Keeps the CDKToolkit bootstrap stack
#                      (an S3 bucket + IAM roles, ~£0) so future deploys work.
#   ./down.sh --all    also delete CDKToolkit (empties its versioned bucket
#                      first). After this the AWS account holds NOTHING from
#                      this project; the next up.sh re-bootstraps.
#
# Safe to re-run: every step skips what's already gone. The cloud data needs
# no backup — corpus.json in git is the source of truth and up.sh restores it.
set -euo pipefail
cd "$(dirname "$0")"

ACCOUNT=166832185275
REGION=${AWS_REGION:-eu-west-2}

echo "This deletes the ClimbingAgentCorpusDb stack + snapshots in $REGION${1:+ AND the CDK bootstrap}."
read -r -p "Type 'destroy' to continue: " ANSWER
[ "$ANSWER" = "destroy" ] || { echo "aborted"; exit 1; }

if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
export PATH="$PWD/.venv/bin:$PATH"

if aws cloudformation describe-stacks --stack-name ClimbingAgentCorpusDb --region "$REGION" >/dev/null 2>&1; then
    echo "== destroying ClimbingAgentCorpusDb (takes a few minutes)"
    npx --yes aws-cdk@2 destroy ClimbingAgentCorpusDb --force
else
    echo "== ClimbingAgentCorpusDb: already gone"
fi

echo "== deleting leftover corpus-db snapshots"
SNAPS=$(aws rds describe-db-cluster-snapshots --region "$REGION" \
    --query "DBClusterSnapshots[?contains(DBClusterSnapshotIdentifier,'corpusdb')].DBClusterSnapshotIdentifier" \
    --output text)
for s in $SNAPS; do
    echo "   deleting snapshot $s"
    aws rds delete-db-cluster-snapshot --region "$REGION" \
        --db-cluster-snapshot-identifier "$s" --query "DBClusterSnapshot.Status" --output text
done
[ -z "$SNAPS" ] && echo "   none found"

if [ "${1:-}" = "--all" ]; then
    B="cdk-hnb659fds-assets-$ACCOUNT-$REGION"
    if aws s3api head-bucket --bucket "$B" 2>/dev/null; then
        echo "== emptying versioned bootstrap bucket $B"
        while : ; do
            BATCH=$(aws s3api list-object-versions --bucket "$B" --max-keys 500 --output json \
                | python3 -c '
import json, sys
d = json.load(sys.stdin)
objs = [{"Key": v["Key"], "VersionId": v["VersionId"]}
        for k in ("Versions", "DeleteMarkers") for v in (d.get(k) or [])]
print(json.dumps({"Objects": objs, "Quiet": True}) if objs else "")')
            [ -z "$BATCH" ] && break
            aws s3api delete-objects --bucket "$B" --delete "$BATCH" >/dev/null
        done
    fi
    echo "== deleting CDKToolkit bootstrap stack"
    aws cloudformation delete-stack --stack-name CDKToolkit --region "$REGION"
    aws cloudformation wait stack-delete-complete --stack-name CDKToolkit --region "$REGION"
    echo "== CDKToolkit deleted — the account holds nothing from this project now"
fi

echo "== done"

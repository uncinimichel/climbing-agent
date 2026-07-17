#!/usr/bin/env bash
# Recreate the AWS infrastructure from scratch and reload its data.
#
# Deploys ONLY the corpus DB (ClimbingAgentCorpusDb). The app stacks
# (auth/data/api/test) are plan-stage skeletons and are deliberately NOT
# deployed by this script — "do not deploy anything to prod" (16 Jul 2026).
#
# What it does, in order:
#   1. creates the local CDK venv if missing
#   2. cdk bootstrap        (no-op when the CDKToolkit stack already exists)
#   3. cdk deploy the Aurora corpus DB, locked to this machine's public IP
#      (~15-30 min: Aurora clusters are slow to create)
#   4. db/cloud-apply.sh    (schema + seeds + corpus.json restore, ~2 min)
#
# Prerequisites: aws CLI logged in (account 166832185275), node/npx, python3,
# and the local climbing-db container running (colima start; cd db && docker-compose up -d)
# — cloud-apply.sh borrows its psql client.
#
# Cost while up: ~£0 idle (scale-to-zero; storage pennies), ~$0.12/ACU-hour
# only while querying. Tear down again with ./down.sh.
set -euo pipefail
cd "$(dirname "$0")"

ACCOUNT=166832185275
REGION=${AWS_REGION:-eu-west-2}

if [ ! -d .venv ]; then
    echo "== creating CDK venv"
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
export PATH="$PWD/.venv/bin:$PATH"

IP=$(curl -s https://checkip.amazonaws.com)
echo "== allowing Postgres access from $IP only"

# bootstrap with the SCOPED CloudFormation execution policy — never the
# default AdministratorAccess (fixed 17 Jul 2026; omitting the flag on a
# re-bootstrap would silently revert the executor to admin)
EXEC_POLICY="arn:aws:iam::$ACCOUNT:policy/ClimbingAgentCdkExec"
aws iam get-policy --policy-arn "$EXEC_POLICY" >/dev/null 2>&1 || \
  aws iam create-policy --policy-name ClimbingAgentCdkExec \
    --policy-document "file://$(dirname "$0")/cdk-exec-policy.json" \
    --description "Scoped CloudFormation execution for climbing-agent CDK stacks" >/dev/null
npx --yes aws-cdk@2 bootstrap "aws://$ACCOUNT/$REGION" \
  --cloudformation-execution-policies "$EXEC_POLICY"

# confused-deputy guard (sec review #4): only CloudFormation runs FROM THIS
# ACCOUNT may assume the exec role. Re-applied after every bootstrap because
# a re-bootstrap rewrites the trust policy without the condition.
aws iam update-assume-role-policy \
  --role-name "cdk-hnb659fds-cfn-exec-role-$ACCOUNT-$REGION" \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"cloudformation.amazonaws.com\"},\"Action\":\"sts:AssumeRole\",\"Condition\":{\"StringEquals\":{\"aws:SourceAccount\":\"$ACCOUNT\"}}}]}"
npx --yes aws-cdk@2 deploy ClimbingAgentCorpusDb \
    -c "corpusDbAllowedCidr=$IP/32" \
    --require-approval never --outputs-file corpus-db-outputs.json

echo "== cluster up — loading schema + corpus"
../db/cloud-apply.sh

echo "== done. Credentials: Secrets Manager 'climbing-agent/corpus-db' ($REGION)."
echo "   Point any db/ tool at it by setting DATABASE_URL (see db/cloud-apply.sh)."

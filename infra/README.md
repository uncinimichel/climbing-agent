# infra/ — AWS CDK (Python) for the multi-user trip planner

Infrastructure-as-code for the multi-user platform (plan:
`~/.claude/plans/shimmering-wandering-cupcake.md`, decision #36): Cognito auth,
DynamoDB + S3 data layer, HTTP API + Lambdas, and an isolated test stage.

## Layout

- `app.py` — CDK app entry; instantiates the four stacks in `eu-west-2`.
- `stacks/auth_stack.py` — Cognito user pool, Google IdP, groups, Hosted UI (M1).
- `stacks/data_stack.py` — DynamoDB tables (Trips / FlightCache / Quota / Jobs) + S3 (M2/M3).
- `stacks/api_stack.py` — HTTP API, JWT authorizer, Lambdas importing `engine/` via a layer (M2+).
- `stacks/test_stack.py` — fully separate test pool/stage/tables (M5).

M0 ships the stacks empty (they synth, deploy nothing meaningful) so every later
milestone lands as a reviewable diff against a working `cdk synth`.

## Working locally

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npx aws-cdk@2 synth        # from this directory; no AWS credentials needed
```

The CDK CLI is an npm package (`npx aws-cdk@2`); the application code stays pure
Python. CI synths on every change to `infra/**` (`.github/workflows/infra.yml`).

Nothing is deployed automatically: `cdk deploy` is a manual, deliberate step.

## Corpus Postgres (`ClimbingAgentCorpusDb` — currently NOT deployed)

Proven end to end on 16 Jul 2026 (deployed, took a full schema + corpus
restore: 220 routes / 181 areas), then torn down the same morning — Michel's
call: keep the corpus local on Docker/Colima for now. To bring it back
(~35 min total):

```
cd infra && PATH=.venv/bin:$PATH npx aws-cdk@2 deploy ClimbingAgentCorpusDb \
  -c corpusDbAllowedCidr=$(curl -s https://checkip.amazonaws.com)/32 --require-approval never
../db/cloud-apply.sh
```

Aurora PostgreSQL Serverless v2 with **scale-to-zero**: ~£0 idle (storage
pennies), ~$0.12/ACU-hour only while queried, ~15s resume on first statement.
Cloud home for the taxonomies + climbs corpus (decisions #34/#35/#36); the
local Colima DB stays the day-to-day default.

- Credentials: Secrets Manager `climbing-agent/corpus-db` (host/port/user/password).
- Load / rebuild the cloud copy: `db/cloud-apply.sh` (schema + seeds + corpus.json restore).
- Point any db/ tool at it: set `DATABASE_URL` (see cloud-apply.sh for the DSN shape).
- Access is locked to one IP. When the home IP changes:

```
NEW_IP=$(curl -s https://checkip.amazonaws.com)
SG=$(aws cloudformation describe-stacks --stack-name ClimbingAgentCorpusDb \
  --query "Stacks[0].Outputs[?OutputKey=='SecurityGroupId'].OutputValue" --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 5432 --cidr "$NEW_IP/32"
```

(then optionally revoke the old rule with `revoke-security-group-ingress`).

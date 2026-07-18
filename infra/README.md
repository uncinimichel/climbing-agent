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

## Bring it all up / tear it all down

Two scripts own the whole lifecycle — both idempotent, both safe to re-run:

```
./up.sh            # bootstrap (if needed) + deploy the corpus DB + load schema & corpus  (~35 min)
./down.sh          # destroy the corpus DB stack + delete its final snapshots            (~10 min)
./down.sh --all    # ALSO remove the CDKToolkit bootstrap — account left completely empty
```

What they cover, and don't:

- **`up.sh` deploys only `ClimbingAgentCorpusDb`** (Aurora PostgreSQL 16.13
  Serverless v2, scale-to-zero, TLS forced, port 5432 open to this machine's
  public IP only, credentials in Secrets Manager `climbing-agent/corpus-db`).
  The app stacks (auth/data/api/test) are plan-stage skeletons and are never
  deployed by script — each needs an explicit, deliberate `cdk deploy`.
- **No backups needed before `down.sh`** — `db/corpus.json` in git is the
  source of truth; `up.sh` rebuilds the cloud copy from it (proven 16 Jul
  2026: 220 routes, 181 areas). `down.sh` asks you to type `destroy` first.
- **Prerequisites**: aws CLI logged in, node/npx, python3, and the local
  `climbing-db` container running (`colima start`, then `cd db &&
  docker-compose up -d`) — the data load borrows its psql client.
- **Cost while up**: ~£0 idle; ~$0.12/ACU-hour only while querying.
  Cost while down: £0 (plus ~£0 for CDKToolkit's empty bucket unless you
  used `--all`).
- **Status right now: everything is DOWN** (torn down 16 Jul 2026,
  Michel: "keep all local with docker for the moment").

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


## AWS identities (18 Jul 2026)

Day-to-day CLI runs as the least-privilege user **`climbing-agent`**
(`[default]` profile) — it can read/write the corpus S3 bucket and nothing
else. Deploys and account administration use the **`admin`** profile
(`asyncloop`): `AWS_PROFILE=admin ./up.sh` etc. The 2020 admin key is
deactivated (kept ~a week for rollback, then delete); root MFA is enabled.

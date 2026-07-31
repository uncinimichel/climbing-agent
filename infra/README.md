# infra/ — AWS CDK (Python) for the multi-user trip planner

Infrastructure-as-code for the multi-user platform (plan:
`~/.claude/plans/shimmering-wandering-cupcake.md`, decision #36): Cognito auth,
DynamoDB + S3 data layer, HTTP API + Lambdas, and an isolated test stage.

## Layout

- `app.py` — CDK app entry; instantiates the five stacks in `eu-west-2`.
- `stacks/auth_stack.py` — Cognito user pool, Google IdP, groups, Hosted UI (M1).
- `stacks/data_stack.py` — DynamoDB tables (Trips / FlightCache / Quota / Jobs) + S3 (M2/M3).
- `stacks/api_stack.py` — HTTP API, JWT authorizer, Lambdas importing `engine/` via a layer (M2+).
- `stacks/studio_stack.py` — the browser Curation Studio: CloudFront + Lambda(Mangum) over the S3 record (#40, live).
- `stacks/test_stack.py` — fully separate test pool/stage/tables (M5).

The auth/data/api/test stacks ship as skeletons (they synth, deploy nothing
meaningful) so every later milestone lands as a reviewable diff against a working
`cdk synth`. **There is no database stack** — the corpus is the JSON record on S3
(decisions #39/#41); `ClimbingAgentCorpusDb` (Aurora) was removed.

## Working locally

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npx aws-cdk@2 synth        # from this directory; no AWS credentials needed
```

The CDK CLI is an npm package (`npx aws-cdk@2`); the application code stays pure
Python. CI synths on every change to `infra/**` (`.github/workflows/infra.yml`).

Nothing is deployed automatically: `cdk deploy` is a manual, deliberate step.

## Deploying

`cdk deploy` is always a manual, deliberate step (nothing deploys from CI). The
live stack today is the browser Studio:

```
./build_studio_assets.sh && npx aws-cdk@2 deploy ClimbingAgentStudio
```

There is **no corpus-DB lifecycle any more** — the old `up.sh`/`down.sh` +
`ClimbingAgentCorpusDb` (Aurora) were removed with Postgres (#41). The corpus is
the JSON record on S3; `corpus/sync.sh` pulls/pushes it. If a stray
`ClimbingAgentCorpusDb` stack ever lingers in the account, destroy it directly:
`aws cloudformation delete-stack --stack-name ClimbingAgentCorpusDb --region eu-west-2`.

## AWS identities (18 Jul 2026)

Day-to-day CLI runs as the least-privilege user **`climbing-agent`**
(`[default]` profile) — it can read/write the corpus S3 bucket and nothing
else. Deploys and account administration use the **`admin`** profile
(`asyncloop`): `AWS_PROFILE=admin ./up.sh` etc. The 2020 admin key is
deactivated (kept ~a week for rollback, then delete); root MFA is enabled.

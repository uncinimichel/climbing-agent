# The corpus API — one app, two homes

The FastAPI app in `../tools/curate.py` IS the API (24 endpoints,
contract captured in [`openapi.json`](openapi.json) — regenerate with
`curl localhost:8890/openapi.json` after endpoint changes). It runs:

- **Locally** (today): `../studio.sh` → uvicorn on `localhost:8890`,
  serving both the Studio UI and the API same-origin. `API_BASE` in the
  UI is empty ⇒ same-origin calls.
- **In Lambda** (phase B, decision #40 — ✅ **live**): `lambda_handler.py`
  wraps the same app with Mangum behind an HTTP API with a Cognito JWT
  authorizer. The S3-hosted Studio sets `window.API_BASE` to the Lambda
  URL; media URLs route through the same base via `asset()`. Deployed
  outputs in `infra/studio-outputs.json`
  (`https://driuinui6do86.cloudfront.net` UI,
  `https://1lm4oxrzc2.execute-api.eu-west-2.amazonaws.com` API).

Phase B, as shipped (the contract did not change):
- Cognito JWT (Michel + Dan, email+password) validated on mutating routes;
  the Host/Origin middleware widens to the CloudFront domain. OPTIONS
  preflight is served with explicit methods (an ANY route swallowed it
  into the authorizer → 401).
- The store reads/writes the record straight from the S3 bucket
  (locally it reads `corpus/record/`, synced by `../sync.sh`).
- CORS for the CloudFront origin only.

Auth: **locally** none — bound to localhost with Host/Origin guards,
single curator; never expose the localhost app publicly. **In the cloud**
the Cognito JWT authorizer is the guard on every mutating route.

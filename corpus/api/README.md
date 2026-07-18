# The corpus API — one app, two homes

The FastAPI app in `../tools/curate.py` IS the API (24 endpoints,
contract captured in [`openapi.json`](openapi.json) — regenerate with
`curl localhost:8890/openapi.json` after endpoint changes). It runs:

- **Locally** (today): `../studio.sh` → uvicorn on `localhost:8890`,
  serving both the Studio UI and the API same-origin. `API_BASE` in the
  UI is empty ⇒ same-origin calls.
- **In Lambda** (phase B, decision #40): `lambda_handler.py` wraps the
  same app with Mangum behind a Function URL/API Gateway. The S3-hosted
  Studio sets `window.API_BASE` to the Lambda URL; media URLs route
  through the same base via `asset()`.

Phase B additions when it lands (nothing about the contract changes):
- Cognito JWT (Michel + Dan, email+password) validated on mutating routes;
  the Host/Origin middleware widens to the CloudFront domain.
- The store reads/writes the record straight from the S3 bucket
  (locally it reads `corpus/record/`, synced by `../sync.sh`).
- CORS for the CloudFront origin only.

Auth today: none — bound to localhost with Host/Origin guards, single
curator. Never expose this app publicly without phase B's auth.

"""Lambda entry point for the corpus API (decision #40 phase B).

The SAME FastAPI app that serves the local Studio (corpus/tools/curate.py)
runs in Lambda behind a Function URL / API Gateway via Mangum. Locally you
never import this file — uvicorn serves the app directly. Deploy-time
environment: RECORD_DIR points at a warm copy of the record synced from S3
(or the store is S3-backed); Cognito JWT validation fronts the mutating
routes.

Requires (deploy bundle only): mangum
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from mangum import Mangum  # noqa: E402

from curate import app  # noqa: E402

handler = Mangum(app)

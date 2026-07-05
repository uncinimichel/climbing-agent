"""Admin chat server — the retrieval agent behind a local web page (Stage 5½ step 3).

A small FastAPI app holding the Anthropic key + DB connection server-side; the
browser talks to /api/chat and renders the same event stream the console does
(ndjson lines). Binds to localhost — this is an admin tool, not a public site.

Run:  .venv/bin/uvicorn server:app --port 8763      (from agent/)
Then open http://127.0.0.1:8763
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import anthropic
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from core import describe_params, stream_turn
from search import connect, load_dotenv, load_enums, tool_schema

app = FastAPI(title="climbing retrieval agent — admin")

STATIC = Path(__file__).resolve().parent / "static"

_state: dict = {}
_lock = threading.Lock()  # one conversation, one turn at a time (single admin user)


def _ensure_state() -> dict:
    """Lazy init so the server starts (and the page loads) even without a key."""
    if not _state:
        load_dotenv()
        _state["client"] = anthropic.Anthropic()
        _state["conn"] = connect()
        _state["tools"] = [tool_schema(load_enums(_state["conn"]))]
        _state["messages"] = []
    return _state


class ChatIn(BaseModel):
    message: str


def _event(kind: str, **payload) -> str:
    return json.dumps({"type": kind, **payload}, default=str, ensure_ascii=False) + "\n"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "admin.html")


@app.post("/api/reset")
def reset() -> dict:
    with _lock:
        if _state:
            _state["messages"] = []
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatIn) -> StreamingResponse:
    def generate():
        with _lock:
            try:
                st = _ensure_state()
            except Exception as e:  # missing key, DB down — report, don't 500
                yield _event("error", message=str(e))
                return
            st["messages"].append({"role": "user", "content": body.message})
            try:
                for kind, payload in stream_turn(st["client"], st["conn"], st["tools"], st["messages"]):
                    if kind == "text":
                        yield _event("text", text=payload)
                    elif kind == "tool":
                        yield _event("tool", label=describe_params(payload), input=payload)
                    elif kind == "rows":
                        yield _event("rows", rows=payload)
                    elif kind == "tool_error":
                        yield _event("tool_error", message=payload)
                    elif kind == "refusal":
                        yield _event("refusal")
                    elif kind == "done":
                        yield _event("done")
            except TypeError as e:
                if "authentication" in str(e).lower():
                    yield _event("error", message="No Anthropic credentials: set ANTHROPIC_API_KEY (env or repo .env) and restart.")
                else:
                    raise
            except anthropic.APIStatusError as e:
                yield _event("error", message=f"API error {e.status_code}: {e.message}")
            except anthropic.APIConnectionError:
                yield _event("error", message="Network error talking to the Anthropic API — retry.")

    return StreamingResponse(generate(), media_type="application/x-ndjson")

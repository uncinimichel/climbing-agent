"""Drive the Claude Code CLI (`claude`) as chat mode's LLM backend, instead of
the raw Anthropic Messages API in core.py.

Why this file exists: a script calling `client.messages.create()` directly
(core.py) always bills against the account's pay-per-token API credit balance,
regardless of auth method (API key or `ant auth login` OAuth) — confirmed live
on 2026-07-05, see knowledge/architecture/retrieval-agent.md. `claude -p` uses
Claude Code's own subscription-billed path instead (verified: succeeds even
when the raw API returns "credit balance too low"). Trade-off: needs the
`claude` binary installed and logged in locally — this can't be deployed
server-side the way core.py's approach can.

The model gets exactly one capability: running search_cli.py via its own Bash
tool. We never hand it a `search_climbs` tool schema over the wire — it's a
shell command, described in the system prompt and scoped via --allowedTools.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = HERE / ".venv" / "bin" / "python"
SEARCH_CLI = HERE / "search_cli.py"

DEFAULT_MODEL = "sonnet"

RULES = """You are the retrieval agent for a curated multi-pitch climbing database.
You have exactly one capability for finding routes: run this Bash command —
  {venv_py} {search_cli} '<json>'
— where <json> is a single-quoted JSON object with these OPTIONAL keys (all combine with AND):
  rock (one of: {rock})
  disciplines (array, subset of: {disciplines})
  features (array, subset of: {features})
  character (array, subset of: {character})
  near: {{"lat": .., "lon": .., "radius_km": ..}}
  month (1-12), max_data_grade (1-7), aspect (one of: {aspect}), limit
The command prints a JSON array of route rows, or {{"error": "..."}} if a value is
off-dictionary — fix the value and retry once; never guess an unlisted value.

Rules:
1. Always show grades as the original grade with its system (e.g. "VS 5a (British)").
   The numeric data_grade is only for ranking — never present it as the grade.
2. Every recommendation carries a short "why" grounded ONLY in the returned rows:
   rock/drying behaviour, aspect and sun window, season fit, hazards. Always mention
   safety-critical hazards (tidal, seepage, loose, alpine hazards) when present.
3. Never invent routes, grades, or conditions. If the command returns no rows, say so
   and suggest relaxing a filter (wider radius, different month, higher grade cap).
4. "Near me" needs coordinates — ask for a town or lat/lon rather than guessing one.
5. Run the search command before answering any route question; don't answer from
   general climbing knowledge.
6. This corpus is small dev-fixture data for now — say so if the user seems to expect
   full real-world coverage.
7. Use no tool other than the one Bash command above."""


def build_system_prompt(enums: dict) -> str:
    return RULES.format(
        venv_py=VENV_PY, search_cli=SEARCH_CLI,
        rock=", ".join(enums["rock"]), disciplines=", ".join(enums["disciplines"]),
        features=", ".join(enums["features"]), character=", ".join(enums["character"]),
        aspect=", ".join(enums["aspect"]),
    )


_CMD_JSON_RE = re.compile(r"'(\{.*\})'\s*$")


def _extract_params(command: str) -> dict | None:
    """None = not our search command; {} = ours but couldn't parse the args."""
    if str(SEARCH_CLI) not in command:
        return None
    m = _CMD_JSON_RE.search(command)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def stream_turn_cli(prompt: str, system_prompt: str, session_id: str | None = None,
                     model: str = DEFAULT_MODEL):
    """Generator of (kind, payload) events mirroring core.stream_turn's contract
    (text/tool/rows/tool_error/refusal/done), plus a ("session", id) event so the
    caller can thread session_id into the next call for conversation continuity."""
    cmd = [
        "claude", "-p", prompt,
        "--append-system-prompt", system_prompt,
        "--allowedTools", "Bash",
        "--disallowedTools", "Edit", "Write", "NotebookEdit",
        "--model", model,
        "--output-format", "stream-json", "--include-partial-messages", "--verbose",
    ]
    if session_id:
        cmd += ["--resume", session_id]

    try:
        proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        yield ("tool_error", "`claude` CLI not found on PATH — install Claude Code "
                              "(https://claude.com/claude-code) to use chat mode this way.")
        return

    pending_tool_id: str | None = None

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        et = event.get("type")
        if et == "stream_event":
            se = event["event"]
            if se.get("type") == "content_block_delta" and se.get("delta", {}).get("type") == "text_delta":
                yield ("text", se["delta"]["text"])

        elif et == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    params = _extract_params(block.get("input", {}).get("command", ""))
                    if params is not None:
                        pending_tool_id = block["id"]
                        yield ("tool", params)

        elif et == "user":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_result" and block.get("tool_use_id") == pending_tool_id:
                    content = block.get("content")
                    if isinstance(content, list):
                        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
                    try:
                        parsed = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        parsed = None
                    if isinstance(parsed, dict) and "error" in parsed:
                        yield ("tool_error", parsed["error"])
                    elif isinstance(parsed, list):
                        yield ("rows", parsed)
                    pending_tool_id = None

        elif et == "result":
            sid = event.get("session_id")
            if sid:
                yield ("session", sid)
            if event.get("subtype") != "success" or event.get("is_error"):
                yield ("refusal", event.get("result"))
            yield ("done", None)

    stderr = proc.stderr.read()
    proc.wait()
    if proc.returncode != 0 and stderr.strip():
        yield ("tool_error", f"claude CLI exited {proc.returncode}: {stderr.strip()[:300]}")

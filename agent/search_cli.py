#!/usr/bin/env python3
"""One-shot CLI wrapper around search_climbs — the entrypoint the Claude Code
CLI proxy (cli_agent.py) tells Claude to run via its own Bash tool, instead of
the raw Anthropic Messages API. Never touches the Anthropic API itself
(search_climbs is pure SQL); only the model call that decides *when* to run it
goes through the `claude` CLI's own billing path.

Usage: python search_cli.py '{"rock":"sandstone","month":8}'
       (or pipe the JSON on stdin)
Prints one JSON object to stdout: either the result rows array, or
{"error": "..."} on a validation failure — never raises, so the calling model
always gets something parseable back.
"""

from __future__ import annotations

import json
import sys

from search import connect, load_dotenv, search_climbs


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON: {e}"}))
        return

    load_dotenv()
    conn = connect()
    try:
        rows = search_climbs(conn, params)
        print(json.dumps(rows, default=str, ensure_ascii=False))
    except (ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()

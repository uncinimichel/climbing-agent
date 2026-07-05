"""The retrieval agent's turn loop, shared by the CLI console and the admin server.

stream_turn() is a generator of UI-agnostic events; each surface renders them its
own way. It mutates `messages` in place (appends assistant turns + tool results).

Events yielded:
    ("text", str)        — a streamed text delta from the model
    ("tool", dict)       — the model called search_climbs with these params
    ("rows", list[dict]) — the rows that call returned (render as table/cards)
    ("tool_error", str)  — the call was rejected (off-dictionary value etc.)
    ("refusal", None)    — the model declined the request
    ("done", None)       — turn complete
"""

from __future__ import annotations

import json

from search import search_climbs

MODEL = "claude-opus-4-8"

SYSTEM = """You are the retrieval agent for a curated multi-pitch climbing database.
You answer questions like "find me sandstone near me in August" by calling the
search_climbs tool and composing a ranked, honest answer.

Rules:
1. Always show grades as the original grade with its system (e.g. "VS 5a (British)").
   The numeric data_grade is only for ranking — never present it as the grade.
2. Every recommendation carries a short "why" grounded ONLY in the returned rows:
   rock/drying behaviour (rock_notes), aspect and sun window, season fit, hazards.
   Mention safety-critical hazards (tidal, seepage, loose, alpine hazards) whenever
   present, with their evidence if given.
3. Never invent routes, grades, or conditions. If the tool returns nothing, say so
   and offer the nearest relaxation (wider radius, different month, higher grade cap).
4. "Near me" needs coordinates: if the user hasn't given a location, ask for a town
   or lat/lon — do not guess one.
5. The UI already renders the returned rows as a table/cards next to your reply, so
   don't repeat every field — rank, recommend, and explain.
6. This corpus is small dev-fixture data for now; if the user seems to expect
   full coverage, note that ingestion hasn't run yet.
"""


def stream_turn(client, conn, tools, messages):
    while True:
        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            tools=tools,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield ("text", event.delta.text)
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            yield ("refusal", None)
            return

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            yield ("done", None)
            return

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            yield ("tool", block.input)
            try:
                rows = search_climbs(conn, block.input)
                yield ("rows", rows)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(rows, default=str, ensure_ascii=False),
                })
            except (ValueError, KeyError) as e:
                yield ("tool_error", str(e))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })
        messages.append({"role": "user", "content": results})


def describe_params(params: dict) -> str:
    """Human-readable one-liner for a search_climbs call."""
    bits = []
    if params.get("rock"):
        bits.append(params["rock"])
    if params.get("disciplines"):
        bits.append("+".join(params["disciplines"]))
    if params.get("near"):
        n = params["near"]
        bits.append(f"≤{n.get('radius_km', 150):g} km of ({n['lat']:.2f}, {n['lon']:.2f})")
    if params.get("month"):
        bits.append(f"month {params['month']}")
    if params.get("max_data_grade"):
        bits.append(f"≤grade {params['max_data_grade']}/7")
    if params.get("aspect"):
        bits.append(f"{params['aspect']}-facing")
    return " · ".join(bits) or "no filters"

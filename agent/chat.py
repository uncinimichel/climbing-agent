"""Retrieval agent console — chat over the climbing DB (roadmap Stage 5½).

A rich terminal UI over the shared turn loop in core.py: streamed replies,
search-call status lines, and result tables with grades/hazard chips.

Usage:  ANTHROPIC_API_KEY=... python chat.py     (or put the key in repo .env)
"""

from __future__ import annotations

import sys

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core import describe_params, stream_turn
from search import connect, load_dotenv, load_enums, tool_schema

console = Console()


def rows_table(rows: list[dict]) -> Table:
    table = Table(show_lines=False, header_style="bold cyan", border_style="dim")
    for col in ("Route", "Grade", "★", "Rock", "Aspect", "Dist", "Location", "⚠ hazards"):
        table.add_column(col)
    for r in rows:
        hazards = ", ".join(h["hazard"] for h in (r.get("hazards") or []))
        table.add_row(
            f"[bold]{r['name']}[/bold]",
            r["grade"] or "?",
            "★" * (r.get("stars") or 0),
            r.get("rock") or "?",
            r.get("aspect") or "",
            f"{r['distance_km']:g} km" if r.get("distance_km") is not None else "",
            r.get("location") or "",
            f"[yellow]{hazards}[/yellow]" if hazards else "",
        )
    return table


def render_turn(client, conn, tools, messages) -> None:
    streamed_text = False
    for kind, payload in stream_turn(client, conn, tools, messages):
        if kind == "text":
            console.print(payload, end="", highlight=False)
            streamed_text = True
        elif kind == "tool":
            if streamed_text:
                console.print()
                streamed_text = False
            console.print(f"  [cyan]⛏  searching:[/cyan] [dim]{describe_params(payload)}[/dim]")
        elif kind == "rows":
            if payload:
                console.print(rows_table(payload))
            else:
                console.print("  [dim]no matches[/dim]")
        elif kind == "tool_error":
            console.print(f"  [red]search rejected: {payload}[/red]")
        elif kind == "refusal":
            console.print("[red]\\[the model declined this request][/red]")
        elif kind == "done":
            console.print()


def main() -> None:
    load_dotenv()
    client = anthropic.Anthropic()
    conn = connect()
    tools = [tool_schema(load_enums(conn))]

    console.print(Panel.fit(
        "[bold]climbing retrieval agent[/bold] · corpus: local Postgres (dev fixtures)\n"
        "[dim]try: \"sandstone multi-pitch in August, easy grades\" · Ctrl-D to quit[/dim]",
        border_style="cyan",
    ))

    messages: list[dict] = []
    while True:
        try:
            user = console.input("\n[bold green]you>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        try:
            render_turn(client, conn, tools, messages)
        except anthropic.APIStatusError as e:
            console.print(f"[red]API error {e.status_code}: {e.message}[/red]")
        except anthropic.APIConnectionError:
            console.print("[red]network error talking to the Anthropic API — retry[/red]")
        except TypeError as e:
            if "authentication" in str(e).lower():
                sys.exit("No Anthropic credentials found. Set ANTHROPIC_API_KEY in the "
                         "environment or in the repo .env, then rerun.")
            raise


if __name__ == "__main__":
    main()

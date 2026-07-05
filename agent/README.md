# agent/ — the retrieval agent (Stage 5½, step 1: CLI harness)

Chat over the climbing DB: a Claude tool-use loop calling the enum-validated
`search_climbs` tool. Design: [`knowledge/architecture/retrieval-agent.md`](../knowledge/architecture/retrieval-agent.md)
(decision #19). The model never writes SQL — `search.py` builds one parameterized
query, with enum lists loaded from the DB lookup tables at startup.

## Setup

```bash
cd db && docker-compose up -d                                   # the corpus DB
docker exec -i climbing-db psql -U climbing -d climbing < dev/sample_routes.sql   # dev fixtures (until real ingestion)
cd ../agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python search.py           # no-LLM test pass: canned queries + enum-rejection check
.venv/bin/python chat.py             # rich terminal console (streaming, result tables)
.venv/bin/uvicorn server:app --port 8763   # admin web chat → http://127.0.0.1:8763
```

The chat surfaces need `ANTHROPIC_API_KEY` (env or repo `.env`). Model:
`claude-opus-4-8`, adaptive thinking. `DATABASE_URL` overrides the default local DSN
(`postgresql://climbing:climbing@localhost:5432/climbing`).

## Layout

| File | What |
|---|---|
| `search.py` | `search_climbs` handler: enums from DB lookup tables → strict tool schema → one parameterized query |
| `core.py` | the shared turn loop — a generator of UI-agnostic events (`text`/`tool`/`rows`/`done`) |
| `chat.py` | rich terminal console: streamed replies, ⛏ search status lines, result tables with hazard chips |
| `server.py` + `static/admin.html` | FastAPI admin page (localhost-only): ndjson event stream → chat bubbles + route cards, light/dark |

## What's here / not yet

| Step (build order) | Status |
|---|---|
| 1. `search_climbs` tool + handler + CLI harness | ✅ |
| 3. Admin chat page (server-side endpoint) | ✅ local (`server.py`; not deployed — Pages is static, this needs a host for key + DB) |
| 2. `get_conditions` (weather-engine join) | ⏳ next |
| 4. pgvector semantic tier | ⏳ budget-gated |

The fixtures in `db/dev/sample_routes.sql` are illustrative dev data (8 routes) so
the loop is testable before ingestion M2 fills the corpus — answers reflect that.

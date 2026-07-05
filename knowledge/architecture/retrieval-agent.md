# Retrieval Agent — chat over the climbing DB

The design for the **admin-page chat agent** that answers natural-language questions from
the Postgres corpus — *"I want to find some sandstone rock near me in August"* → the right
climbs, ranked, with a plain-language why. Roadmap **Stage 5½**; decision
[#19](../roadmap/decisions.md). Storage it queries: [`../data/database.md`](../data/database.md).

> **Status: ⚠️ Steps 1 + 3 built locally (4 Jul 2026).** [`agent/`](../../agent/README.md)
> holds the `search_climbs` handler, a shared turn loop (`core.py` — one event-generator
> consumed by both surfaces), a **rich terminal console** (`chat.py`: streaming, result
> tables, hazard chips) and the **admin web chat** (`server.py` + `static/admin.html`:
> FastAPI on localhost, ndjson event stream, route cards, light/dark). Tested against
> dev fixtures (`db/dev/sample_routes.sql`); the no-LLM pass (`python agent/search.py`)
> verifies enum/geo/season filtering and off-dictionary rejection. **Live LLM loop
> needs `ANTHROPIC_API_KEY`** (not yet configured on this machine). Real coverage still
> requires ingestion (M2+); `get_conditions` and pgvector remain planned.

## The core call: SQL-first, vectors later

The obvious question — *"should this use a vector database?"* — has the same answer as
the ontology question before it (see [`database.md`](../data/database.md)): **not for
these queries.** Decompose the example:

| Fragment | Resolves to | Mechanism |
|---|---|---|
| "sandstone rocks" | `rock = 'sandstone'` | closed enum (taxonomy) |
| "near me" | `ST_DWithin(geom, <user point>, <radius>)` | PostGIS |
| "in August" | `8 = ANY(best_season)` + `route_climatology` month 8 | climate columns |
| *(implied)* "and dry/climbable" | condition score from the weather engine | Stage-1/2 logic |

Every fragment is a **structured filter over a closed vocabulary** — deterministic SQL,
exactly what the schema was built for. Embedding similarity would only *approximate*
what an indexed `WHERE` clause answers exactly. Where semantic search does earn its
place is **prose and vagueness**: "something adventurous with an easy escape", route
descriptions, the social buzz summaries. That tier is **pgvector inside the same
Postgres** — never a separate vector DB — so one query can filter by enum/geo *and*
rank by similarity. It stays budget-gated as before: Anthropic ships no embedding API
(their docs point to external providers like Voyage AI), so it's a new dependency, not
a flip of a switch.

## Architecture

```
admin page (chat UI on the dashboard)
    │
    ▼
Claude (tool-use loop; claude-opus-4-8, adaptive thinking)
    │  1. search_climbs(...)      — strict, enum-validated parameters → SQL
    │  2. get_conditions(...)     — venue/day scores from the weather engine
    │  3. [later] semantic_search — pgvector over prose/buzz
    ▼
Postgres (db/ schema) → validated rows → LLM composes the answer with a why
```

The model **never writes raw SQL**. It calls a `search_climbs` tool whose JSON-Schema
parameters are the taxonomy's closed enums (`strict: true`, so inputs validate exactly):

```json
{
  "name": "search_climbs",
  "description": "Search the route corpus. Call when the user asks to find climbs/crags/routes by any attribute.",
  "strict": true,
  "input_schema": {
    "type": "object",
    "properties": {
      "rock": { "type": "string", "enum": ["granite", "limestone", "dolerite", "rhyolite", "sandstone", "gabbro", "quartzite", "volcanic", "dolomite"] },
      "disciplines": { "type": "array", "items": { "type": "string", "enum": ["trad", "sport", "multi-pitch", "..."] } },
      "near": { "type": "object", "properties": { "lat": {"type": "number"}, "lon": {"type": "number"}, "radius_km": {"type": "number"} }, "additionalProperties": false },
      "month": { "type": "integer", "enum": [1,2,3,4,5,6,7,8,9,10,11,12] },
      "max_data_grade": { "type": "integer", "enum": [1,2,3,4,5,6,7] },
      "aspect": { "type": "string", "enum": ["N","NE","E","SE","S","SW","W","NW"] }
    },
    "additionalProperties": false
  }
}
```

The tool handler builds one parameterized query (enum FKs make bad values impossible;
`status = 'publish'` enforced server-side — Zero-Garbage UGC applies to retrieval too).
Generate the enum lists **from the DB lookup tables** at startup so tool schema and
taxonomy never drift.

Why parameterized-tool over text-to-SQL: no injection surface, no invalid-column
hallucinations, the closed taxonomy means ~a dozen parameters cover the real query
space, and results are auditable (log the tool call = log the query). An admin-only
**read-only raw-SQL escape hatch** (separate tool, read-only role, `statement_timeout`)
can come later for power queries — it's a curation tool, not the user path.

## Answer composition rules

1. **Grades display as `originalGrade`**, ranked by `dataGrade` — never show the bare
   number (grade-conversion rule).
2. **Every recommendation carries a why** grounded in returned rows (rock/drying
   behaviour from `rock_type.notes`, aspect/sun, hazards with their evidence spans) —
   same plain-language-why principle as the Stage-2 contingency engine.
3. **Weather claims come from the condition engine**, not the LLM's prior. "Good in
   August" must trace to `route_climatology` / `best_season` / a live score.
4. **No results ≠ invent results.** An empty result set is reported as such, with the
   nearest relaxation offered ("nothing within 50 km — 3 matches within 120 km").

## Admin page

- Lives with the dashboard (same static-hosting model); the chat backend is the one
  server-side piece — a small endpoint holding the Anthropic key and the DB connection.
  It never runs in the browser (key + DB are server-side only).
- Admin-only at first: it doubles as the Phase-3 curation console's front door
  (promote/demote/verify actions can become tools on the same loop later).
- "Near me" uses browser geolocation or a typed place — **no personal locations in the
  public repo** (decision #7 discipline).
- This is the internal precursor of Stage 6's *"single question-and-answer flow"* front
  door: prove the loop on the admin, then productise.

## Cost & model notes

- `claude-opus-4-8`, adaptive thinking, tool-use loop (per the `/claude-api` reference —
  structured outputs and strict tools are GA). A cheaper tier (Haiku) can serve the
  parse-only path later if cost demands; don't start there.
- Token cost is bounded: the tools return compact rows, not documents. Cache the system
  prompt + tool schemas (stable prefix) per prompt-caching guidance.
- Embedding costs (pgvector tier) stay deferred with the rest of the semantic budget
  ([ingestion plan → free-tier constraints](../roadmap/ingestion-plan.md)).

## Build order (when its turn comes)

1. `search_climbs` tool + handler over the `db/` schema; CLI harness first, no UI.
2. Wire the condition engine as `get_conditions` (reuse existing scoring).
3. Minimal admin chat page calling the loop server-side.
4. pgvector + embeddings for prose/buzz — only once real prose is ingested and budget
   opens.

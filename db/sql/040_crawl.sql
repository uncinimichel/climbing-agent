-- 040 — crawl frontier: the durable index of ingestion work (roadmap Stage 5,
-- ingestion-plan.md). One row per area/route discovered from a source; the
-- crawler's entire state lives here, never in a script's memory, so it can be
-- started, stopped, or crashed at any point and just resume from the table.
-- Dedup key is (source_id, external_id), the same pairing external_ref uses.
SET search_path = climbing, public;

CREATE TABLE crawl_frontier (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id           text NOT NULL REFERENCES source (id),
    external_id         text NOT NULL,          -- the source's native id for this node
    kind                text NOT NULL CHECK (kind IN ('area', 'route')),
    parent_frontier_id  bigint REFERENCES crawl_frontier (id),
    path                text,                   -- "GB > Wales > Llanberis Pass", for logs/debugging
    corpus_area_id      text,                   -- db/corpus.json area id this subtree seeds from/maps to

    area_id             bigint REFERENCES area (id),   -- filled once mechanically inserted
    route_id            bigint REFERENCES route (id),  -- filled once mechanically inserted

    -- Fetch: the mechanical pull + structural insert (deterministic, no LLM).
    fetch_status        text NOT NULL DEFAULT 'pending'
                        CHECK (fetch_status IN ('pending', 'in_progress', 'done', 'failed', 'skipped')),
    -- Multi-pitch trad/alpine gate (routes only): pitches_count >= 2 AND
    -- discipline overlaps {trad, alpine, big-wall}. NULL = not yet evaluated.
    -- 'skipped' fetch_status is for subtrees rejected on crag-level metadata
    -- alone, before ever fetching route detail.
    passes_filter       boolean,

    -- Tag: the LLM-inferred fields (protection, hazards, character, prose).
    -- Only applies to routes that passed the filter — stays not_applicable
    -- for areas and for filtered-out routes.
    tag_status          text NOT NULL DEFAULT 'not_applicable'
                        CHECK (tag_status IN ('not_applicable', 'pending', 'in_progress', 'done', 'needs_review', 'failed')),
    flagged_fields       text[],                -- fields the LLM couldn't confidently resolve

    attempts            smallint NOT NULL DEFAULT 0,
    last_error          text,
    claimed_at          timestamptz,            -- lease timestamp; stale claims are reclaimed
    last_attempted_at   timestamptz,
    fetched_at          timestamptz,
    tagged_at           timestamptz,

    raw_capture_path    text,                   -- pointer into the local raw store (never committed)
    created_at          timestamptz NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

-- Partial indexes on the two claim queries (worker only ever selects the
-- "still has work" subset, which stays small relative to 'done').
CREATE INDEX crawl_frontier_fetch_pending_ix ON crawl_frontier (source_id, id)
    WHERE fetch_status = 'pending';
CREATE INDEX crawl_frontier_tag_pending_ix ON crawl_frontier (source_id, id)
    WHERE fetch_status = 'done' AND tag_status = 'pending';
CREATE INDEX crawl_frontier_needs_review_ix ON crawl_frontier (source_id)
    WHERE tag_status = 'needs_review';
CREATE INDEX crawl_frontier_parent_ix ON crawl_frontier (parent_frontier_id);

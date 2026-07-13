-- 025 — curation & tag provenance (decision #32/#34: Postgres-first curation).
-- Adds who-tagged-it provenance and the Curation Studio's working fields to route.
-- Runs after 020 (route exists) and before 030 (views pick the columns up via r.*).
SET search_path = climbing, public;

ALTER TABLE route
    ADD COLUMN tagged_by         text NOT NULL DEFAULT 'source'
                                 CHECK (tagged_by IN ('human', 'llm', 'source')),
    ADD COLUMN tag_prov          jsonb,          -- {model, date} when tagged_by = 'llm'
    ADD COLUMN curation_notes    text,           -- travels with the row ("photograph pitch 2")
    ADD COLUMN needs_field_check boolean NOT NULL DEFAULT false,
    ADD COLUMN curated_at        timestamptz;    -- set when a human publishes

-- Governance (#32): a publish row must be human-tagged — llm tags never pass as curated.
ALTER TABLE route
    ADD CONSTRAINT route_publish_needs_human_tags
    CHECK (status <> 'publish' OR tagged_by = 'human');

CREATE INDEX route_needs_field_check_ix ON route (needs_field_check) WHERE needs_field_check;

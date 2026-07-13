-- 026 — taxonomy metadata for studio-managed vocabularies (decision #35).
-- Every enum value the Curation Studio can add must carry a meaning (it feeds the
-- AI tagger's prompt and the taxonomy page); feature/sun_window predate that rule.
SET search_path = climbing, public;

ALTER TABLE feature    ADD COLUMN meaning text;
ALTER TABLE sun_window ADD COLUMN meaning text;

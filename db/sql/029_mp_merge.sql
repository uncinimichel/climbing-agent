-- 029 — multi-pitch merge prerequisites (knowledge/data/mp-field-mapping.md §3).
-- Two gaps found mapping every MP field into the schema:
--   1. guideBooks[].type ('guidebook' | 'PDF') had no home → guidebook.kind
--   2. route_reference.prefix CHECK was narrower than MP's real reference data
--      (mostly unprefixed free text, plus 'Access' and 'Accommodation').
SET search_path = climbing, public;

ALTER TABLE guidebook
    ADD COLUMN kind text NOT NULL DEFAULT 'guidebook'
        CHECK (kind IN ('guidebook', 'pdf'));

ALTER TABLE route_reference
    DROP CONSTRAINT route_reference_prefix_check;
ALTER TABLE route_reference
    ADD CONSTRAINT route_reference_prefix_check
        CHECK (prefix IN ('Video', 'Travel', 'Article', 'Info', 'Tides',
                          'Access', 'Accommodation'));

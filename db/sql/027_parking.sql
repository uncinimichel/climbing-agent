-- 027 — structured parking for the approach (Michel 2026-07-13: "add the park").
-- The curated multi-pitch.com pages carry parking lat/lon in approach prose; making it
-- a column lets the studio verify it on the map and the trip pipeline route to it.
SET search_path = climbing, public;

ALTER TABLE route ADD COLUMN parking geography (Point, 4326);

-- Smoke test — exercises the schema end-to-end with the taxonomy.md example route
-- (Original Route, Old Man of Stoer). Re-runnable: cleans up after itself.
\set ON_ERROR_STOP on
SET search_path = climbing, public;

BEGIN;

-- 1. Area hierarchy with an inherited grade context.
INSERT INTO area (name, kind, grade_context, timezone)
    VALUES ('SMOKE Scotland', 'country', 'GB', 'Europe/London');
INSERT INTO area (parent_id, name, kind)
    SELECT id, 'SMOKE Assynt', 'region' FROM area WHERE name = 'SMOKE Scotland';
INSERT INTO area (parent_id, name, kind, rock_code, geom)
    SELECT id, 'SMOKE Old Man of Stoer', 'sector', 'sandstone',
           ST_SetSRID(ST_MakePoint(-5.361, 58.258), 4326)::geography
    FROM area WHERE name = 'SMOKE Assynt';

-- 2. The example route from taxonomy.md § Record shape.
INSERT INTO route (area_id, name, status, tagged_by, geom,
                   length_m, pitches_count, rock_code, incline_code, aspect,
                   grade_system_code, original_grade, trad_grade, tech_grade, data_grade,
                   protection_code, approach_time_min, approach_difficulty)
    SELECT id, 'SMOKE Original Route', 'publish', 'human',
           ST_SetSRID(ST_MakePoint(-5.361, 58.258), 4326)::geography,
           67, 5, 'sandstone', 'Vertical', 'SE',
           'BAS', 'VS 5a', 'VS', '5a', 5,
           'PG', 50, 3
    FROM area WHERE name = 'SMOKE Old Man of Stoer';

INSERT INTO route_discipline
    SELECT id, d FROM route, unnest(ARRAY['trad', 'multi-pitch']) AS d
    WHERE name = 'SMOKE Original Route';

-- Safety-critical hazard WITH evidence (must succeed) + non-critical without.
INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url)
    SELECT id, 'tidal', 'sea stack, Tyrolean traverse', 'https://example.org/stoer'
    FROM route WHERE name = 'SMOKE Original Route';
INSERT INTO route_hazard (route_id, hazard_code)
    SELECT id, h FROM route, unnest(ARRAY['abseil', 'traverse']) AS h
    WHERE name = 'SMOKE Original Route';

INSERT INTO provenance (route_id, field, source_id, source_url, span, confidence)
    SELECT id, 'protection', 'multipitch', 'https://example.org/stoer',
           'sea stack, Tyrolean traverse', 0.82
    FROM route WHERE name = 'SMOKE Original Route';

-- 3. Closed-enum enforcement: off-dictionary rock must be rejected (parser rule #1).
DO $$
BEGIN
    BEGIN
        INSERT INTO route (area_id, name, rock_code)
            SELECT area_id, 'Bogus Route', 'kryptonite' FROM route WHERE name = 'SMOKE Original Route';
        RAISE EXCEPTION 'FAIL: off-dictionary rock type was accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        RAISE NOTICE 'OK: off-dictionary rock type rejected';
    END;
END $$;

-- 4. Safety-critical hazard WITHOUT evidence must be rejected (parser rule #4).
DO $$
BEGIN
    BEGIN
        INSERT INTO route_hazard (route_id, hazard_code)
            SELECT id, 'loose' FROM route WHERE name = 'SMOKE Original Route';
        RAISE EXCEPTION 'FAIL: safety-critical hazard accepted without evidence';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'OK: safety-critical hazard without evidence rejected';
    END;
END $$;

-- 5. Inheritance: the route must resolve grade_context GB from Scotland.
DO $$
DECLARE ctx text;
BEGIN
    SELECT eff_grade_context INTO ctx FROM route_resolved WHERE name = 'SMOKE Original Route';
    IF ctx IS DISTINCT FROM 'GB' THEN
        RAISE EXCEPTION 'FAIL: expected inherited grade_context GB, got %', ctx;
    END IF;
    RAISE NOTICE 'OK: grade_context GB inherited from country level';
END $$;

-- 6. Geo query: routes within 50 km of Lochinver (PostGIS replaces SQLite R-tree).
DO $$
DECLARE n int;
BEGIN
    SELECT count(*) INTO n FROM route
    WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(-5.245, 58.148), 4326)::geography, 50000);
    IF n < 1 THEN RAISE EXCEPTION 'FAIL: geo query found no nearby routes'; END IF;
    RAISE NOTICE 'OK: geo radius query found % route(s)', n;
END $$;

-- 7. Grade ladder join: VS 5a must map to dataGrade 5.
DO $$
DECLARE g smallint;
BEGIN
    SELECT gc.data_grade INTO g
    FROM route r JOIN grade_conversion gc
      ON gc.grade_system_code = r.grade_system_code AND gc.original_grade = r.original_grade
    WHERE r.name = 'SMOKE Original Route';
    IF g IS DISTINCT FROM 5 THEN RAISE EXCEPTION 'FAIL: VS 5a mapped to %', g; END IF;
    RAISE NOTICE 'OK: VS 5a → dataGrade 5 via grade_conversion';
END $$;

-- Show the resolved record, then roll back — the smoke test leaves no data behind.
SELECT name, path_tokens, eff_grade_context, original_grade, data_grade,
       protection_code, eff_rock_code
FROM route_resolved WHERE name = 'SMOKE Original Route';

ROLLBACK;
\echo 'SMOKE TEST PASSED (all inserts rolled back)'

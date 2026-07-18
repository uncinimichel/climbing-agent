-- DEV FIXTURES — illustrative sample routes so the retrieval agent has something to
-- query before real ingestion (M2) lands. NOT applied by initdb; load explicitly:
--   docker exec -i climbing-db psql -U climbing -d climbing < db/dev/sample_routes.sql
-- Route facts are approximate/illustrative dev data, not curated truth.
-- Re-runnable: wipes previous dev fixtures first (identified by the 'dev-fixtures' source).
\set ON_ERROR_STOP on
SET search_path = climbing, public;

BEGIN;

INSERT INTO source (id, name, type, method, license, tos, regions, cadence, teaches)
VALUES ('dev-fixtures', 'Dev fixtures', 'route-db', 'manual', 'n/a', 'owned', '{*}', 'manual', 'local development only')
ON CONFLICT (id) DO NOTHING;

-- wipe previous fixture load (cascades to junctions/climatology)
DELETE FROM route WHERE id IN (SELECT entity_id FROM external_ref WHERE source_id = 'dev-fixtures' AND entity_type = 'route');
DELETE FROM area  WHERE id IN (SELECT entity_id FROM external_ref WHERE source_id = 'dev-fixtures' AND entity_type = 'area')
                    AND NOT EXISTS (SELECT 1 FROM route r WHERE r.area_id = area.id);
DELETE FROM external_ref WHERE source_id = 'dev-fixtures';

-- ---------------------------------------------------------------------------
-- Area tree: country (grade context) → region → sector
-- ---------------------------------------------------------------------------
WITH countries AS (
    INSERT INTO area (name, kind, grade_context, timezone) VALUES
        ('Scotland',         'country', 'GB', 'Europe/London'),
        ('Wales',            'country', 'GB', 'Europe/London'),
        ('England',          'country', 'GB', 'Europe/London'),
        ('Northern Ireland', 'country', 'GB', 'Europe/London'),
        ('Spain',            'country', 'ES', 'Europe/Madrid'),
        ('France',           'country', 'FR', 'Europe/Paris'),
        ('Croatia',          'country', 'HR', 'Europe/Zagreb')
    RETURNING id, name
),
regions AS (
    INSERT INTO area (parent_id, name, kind)
    SELECT c.id, r.rname, 'region'
    FROM countries c
    JOIN (VALUES
        ('Scotland',         'Assynt'),
        ('Wales',            'Snowdonia'),
        ('Wales',            'Gower'),
        ('England',          'Lake District'),
        ('Northern Ireland', 'Antrim'),
        ('Spain',            'Sierra de Gredos'),
        ('France',           'Écrins'),
        ('Croatia',          'Paklenica')
    ) AS r(cname, rname) ON r.cname = c.name
    RETURNING id, name
)
INSERT INTO area (parent_id, name, kind, rock_code, aspect, geom)
SELECT r.id, s.sname, 'sector', s.rock, s.aspect::aspect_dir,
       ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography
FROM regions r
JOIN (VALUES
    ('Assynt',           'Old Man of Stoer',  'sandstone', 'SE', -5.3610, 58.2580),
    ('Snowdonia',        'Idwal Slabs',       'rhyolite',  'NE', -4.0290, 53.1140),
    ('Gower',            'Three Cliffs Bay',  'limestone', 'S',  -4.1110, 51.5700),
    ('Lake District',    'Gimmer Crag',       'volcanic',  'SW', -3.1120, 54.4470),
    ('Antrim',           'Fair Head',         'dolerite',  'N',  -6.1560, 55.2220),
    ('Sierra de Gredos', 'Los Galayos',       'granite',   'W',  -5.1740, 40.2600),
    ('Écrins',           'Aiguille Dibona',   'granite',   'S',   6.2740, 44.9310),
    ('Paklenica',        'Anica Kuk',         'limestone', 'N',  15.4650, 44.3010)
) AS s(rname, sname, rock, aspect, lon, lat) ON s.rname = r.name;

-- tag fixture areas for re-runnable cleanup
INSERT INTO external_ref (entity_type, entity_id, source_id, external_id)
SELECT 'area', a.id, 'dev-fixtures', 'area:' || a.name
FROM area a
WHERE a.name IN ('Scotland','Wales','England','Northern Ireland','Spain','France','Croatia',
                 'Assynt','Snowdonia','Gower','Lake District','Antrim','Sierra de Gredos','Écrins','Paklenica',
                 'Old Man of Stoer','Idwal Slabs','Three Cliffs Bay','Gimmer Crag','Fair Head',
                 'Los Galayos','Aiguille Dibona','Anica Kuk')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Routes (status 'publish' so retrieval surfaces them)
-- ---------------------------------------------------------------------------
INSERT INTO route (area_id, name, status, geom, length_m, pitches_count,
                   incline_code, aspect,
                   grade_system_code, original_grade, trad_grade, tech_grade, data_grade,
                   protection_code, approach_time_min, approach_difficulty,
                   elevation_m, sun_window_code, best_season, stars)
SELECT a.id, v.rname, 'publish', a.geom, v.len, v.pitches,
       v.incline, NULL,
       v.gsys, v.grade, v.tgrade, v.techg, v.dg,
       v.prot, v.appr, v.apprd,
       v.elev, v.sun, v.season::smallint[], v.stars
FROM (VALUES
    ('Old Man of Stoer', 'Original Route',      67,  5, 'Vertical',        'BAS',  'VS 5a',  'VS',  '5a', 5, 'PG',  50, 3,   60, 'morning',   '{5,6,7,8,9}',   3),
    ('Idwal Slabs',      'Tennis Shoe',        140,  5, 'Slab',            'BAS',  'HS 4a',  'HS',  '4a', 4, 'PG',  20, 1,  450, 'morning',   '{4,5,6,7,8,9}', 3),
    ('Three Cliffs Bay', 'Scavenger',           40,  1, 'Vertical',        'BAS',  'VS 4c',  'VS',  '4c', 5, 'G',   15, 2,   20, 'all-day',   '{3,4,5,6,7,8,9,10}', 2),
    ('Gimmer Crag',      'Ash Tree Slabs',      70,  2, 'Slab & Vertical', 'BAS',  'VD 3c',  'VD',  '3c', 2, 'G',   60, 2,  520, 'afternoon', '{5,6,7,8,9}',   2),
    ('Fair Head',        'Girona',              60,  1, 'Vertical',        'BAS',  'VS 4c',  'VS',  '4c', 5, 'G',   25, 2,  100, 'shade',     '{5,6,7,8,9}',   2),
    ('Los Galayos',      'Sur Clásica (Punta Margarita)', 200, 6, 'Vertical', 'UIAA', 'V+',  NULL, NULL, 5, 'PG',  90, 2, 2200, 'afternoon', '{6,7,8,9}',     3),
    ('Aiguille Dibona',  'Voie Boell',         350, 10, 'Vertical',        'ALP',  'D',     NULL, NULL, 4, 'PG', 120, 3, 3130, 'all-day',   '{7,8,9}',       3),
    ('Anica Kuk',        'Mosoraški',          350, 11, 'Vertical',        'UIAA', 'V+',    NULL, NULL, 5, 'PG',  45, 2,  350, 'shade',     '{4,5,6,9,10}',  3)
) AS v(sector, rname, len, pitches, incline, gsys, grade, tgrade, techg, dg, prot, appr, apprd, elev, sun, season, stars)
JOIN area a ON a.name = v.sector AND a.kind = 'sector';

INSERT INTO external_ref (entity_type, entity_id, source_id, external_id)
SELECT 'route', r.id, 'dev-fixtures', 'route:' || r.name FROM route r
WHERE r.area_id IN (SELECT entity_id FROM external_ref WHERE source_id='dev-fixtures' AND entity_type='area');

-- disciplines
INSERT INTO route_discipline (route_id, discipline_code)
SELECT r.id, d FROM route r, unnest(ARRAY['trad','multi-pitch']) AS d
WHERE r.name IN ('Original Route','Tennis Shoe','Ash Tree Slabs','Sur Clásica (Punta Margarita)','Voie Boell','Mosoraški');
INSERT INTO route_discipline (route_id, discipline_code)
SELECT r.id, d FROM route r, unnest(ARRAY['trad','single-pitch']) AS d
WHERE r.name IN ('Scavenger','Girona');
INSERT INTO route_discipline (route_id, discipline_code)
SELECT r.id, 'alpine' FROM route r WHERE r.name IN ('Voie Boell','Sur Clásica (Punta Margarita)');

-- character (how it climbs) + features + protection style
INSERT INTO route_character (route_id, character_code)
SELECT r.id, c FROM route r
JOIN (VALUES
    ('Original Route', 'exposed'), ('Original Route', 'sustained'),
    ('Tennis Shoe', 'delicate'), ('Tennis Shoe', 'technical'),
    ('Scavenger', 'technical'),
    ('Girona', 'sustained'), ('Girona', 'powerful'),
    ('Sur Clásica (Punta Margarita)', 'exposed'),
    ('Voie Boell', 'sustained'), ('Voie Boell', 'exposed'),
    ('Mosoraški', 'pumpy'), ('Mosoraški', 'sustained')
) AS v(rname, c) ON v.rname = r.name;

INSERT INTO route_feature (route_id, feature_code)
SELECT r.id, f FROM route r
JOIN (VALUES
    ('Original Route', 'crack'), ('Original Route', 'face'),
    ('Tennis Shoe', 'slab'),
    ('Scavenger', 'corner'), ('Scavenger', 'crack'),
    ('Ash Tree Slabs', 'slab'),
    ('Girona', 'corner'), ('Girona', 'crack'),
    ('Sur Clásica (Punta Margarita)', 'ridge'), ('Sur Clásica (Punta Margarita)', 'pillar'),
    ('Voie Boell', 'face'), ('Voie Boell', 'corner'),
    ('Mosoraški', 'face'), ('Mosoraški', 'groove')
) AS v(rname, f) ON v.rname = r.name;

UPDATE route SET protection_style = 'gear', belays = 'gear'
WHERE name IN ('Original Route','Tennis Shoe','Scavenger','Ash Tree Slabs','Girona');
UPDATE route SET protection_style = 'gear', belays = 'mixed' WHERE name = 'Sur Clásica (Punta Margarita)';
UPDATE route SET protection_style = 'mixed', belays = 'bolted' WHERE name IN ('Voie Boell','Mosoraški');

-- hazards (safety-critical ones carry evidence spans)
INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url)
SELECT r.id, 'tidal', 'sea stack; base only accessible at low tide', 'https://example.dev/fixture'
FROM route r WHERE r.name = 'Original Route';
INSERT INTO route_hazard (route_id, hazard_code)
SELECT r.id, h FROM route r, unnest(ARRAY['abseil','traverse','boat']) AS h WHERE r.name = 'Original Route';
INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url)
SELECT r.id, 'tidal', 'approach beach cut off around high water', 'https://example.dev/fixture'
FROM route r WHERE r.name = 'Scavenger';
INSERT INTO route_hazard (route_id, hazard_code, evidence_span, source_url)
SELECT r.id, 'stormExposed', 'high alpine face, no quick retreat in afternoon storms', 'https://example.dev/fixture'
FROM route r WHERE r.name IN ('Voie Boell','Sur Clásica (Punta Margarita)');
INSERT INTO route_hazard (route_id, hazard_code)
SELECT r.id, 'polished' FROM route r WHERE r.name = 'Mosoraški';

-- a little per-route climatology (Jul/Aug) to exercise the climate join
INSERT INTO route_climatology (route_id, month, rainy_days, temp_high, temp_low)
SELECT r.id, m.month, m.rain, m.th, m.tl
FROM route r
JOIN (VALUES
    ('Original Route', 7, 13.0, 16.0, 11.0), ('Original Route', 8, 14.0, 16.0, 11.0),
    ('Mosoraški',      7,  6.0, 30.0, 19.0), ('Mosoraški',      8,  6.0, 30.0, 19.0),
    ('Voie Boell',     7,  9.0, 14.0,  4.0), ('Voie Boell',     8,  9.0, 14.0,  4.0)
) AS m(rname, month, rain, th, tl) ON m.rname = r.name;

COMMIT;

SELECT count(*) AS fixture_routes FROM route r
JOIN external_ref x ON x.entity_type='route' AND x.entity_id = r.id AND x.source_id='dev-fixtures';

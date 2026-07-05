-- 020 — core entities: source registry, area hierarchy, routes, junctions, provenance.
-- The record shape follows knowledge/data/route-schema.md; the structural upgrades
-- (hierarchical areas, inherited gradeContext, multi-system grades, structured pitches)
-- follow knowledge/data/external-models.md P0/P1.
SET search_path = climbing, public;

-- ---------------------------------------------------------------------------
-- Source registry — mirrors sources.json in the ingestion plan (config-as-truth).
-- ---------------------------------------------------------------------------
CREATE TABLE source (
    id      text PRIMARY KEY,              -- openbeta, thecrag, ukclimbing, mountainproject, …
    name    text NOT NULL,
    type    text NOT NULL,                 -- route-db | social | guidebook | blog
    method  text,                          -- graphql | scrape | api | manual
    license text,
    tos     text,
    regions text[],
    cadence text,
    teaches text
);

-- ---------------------------------------------------------------------------
-- Area hierarchy: country → region → crag → sector (OpenBeta model).
-- Properties set on an area (grade_context, rock, aspect) inherit downward —
-- resolved by the views in 030_views.sql.
-- ---------------------------------------------------------------------------
CREATE TABLE area (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id     bigint REFERENCES area (id),
    name          text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('country', 'region', 'crag', 'sector')),
    grade_context text,                    -- short country/region code (GB, US, FR…), inherited
    rock_code     text REFERENCES rock_type (code),
    aspect        aspect_dir,
    timezone      text,                    -- IANA tz
    geom          geography (Point, 4326),
    access_notes  text,                    -- access & stewardship layer (P2)
    UNIQUE (parent_id, name)
);
CREATE INDEX area_geom_gix ON area USING gist (geom);
CREATE INDEX area_name_trgm ON area USING gin (name gin_trgm_ops);

-- Curated area-level external links — absorbs trip-ni-july-2026/extra-climbing.json
-- ("More climbing in the area": {title, source, url, note} per venue). Every URL is
-- reachability-checked before persisting (roadmap Stage 0 #6 rule).
CREATE TABLE area_reference (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area_id     bigint NOT NULL REFERENCES area (id) ON DELETE CASCADE,
    title       text NOT NULL,
    source_name text,                      -- free-text attribution ("theCrag.com", "Desnivel.com")
    url         text NOT NULL,
    note        text,
    verified_at date                       -- when the URL was last reachability-checked
);

-- ---------------------------------------------------------------------------
-- Route — the canonical record (route-schema.md). Every climb maps to a verified
-- sector or stays quarantined (Zero-Garbage UGC): status gates surfacing.
-- ---------------------------------------------------------------------------
CREATE TABLE route (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area_id             bigint NOT NULL REFERENCES area (id),
    name                text NOT NULL,
    status              text NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('publish', 'draft', 'quarantined')),

    -- identity & location
    geom                geography (Point, 4326),
    timezone            text,
    left_right_index    int,               -- order along the crag (OpenBeta)

    -- physical character
    length_m            int,
    pitches_count       smallint,
    rock_code           text REFERENCES rock_type (code),
    incline_code        text REFERENCES incline (code),
    aspect              aspect_dir,

    -- difficulty (grade is system-scoped; original_grade is verbatim, never lost)
    grade_system_code   text REFERENCES grade_system (code),
    original_grade      text,
    trad_grade          text,              -- BAS adjectival part (VS, HVS, E1…)
    tech_grade          text,              -- BAS technical part (4c, 5a, 5b…)
    data_grade          smallint CHECK (data_grade BETWEEN 1 AND 7),

    -- safety & commitment
    protection_code     text NOT NULL DEFAULT 'UNSPECIFIED' REFERENCES protection_grade (code),
    protection_style    text CHECK (protection_style IN ('gear', 'bolted', 'mixed', 'none')),
    belays              text CHECK (belays IN ('gear', 'bolted', 'mixed')),
    commitment_code     text REFERENCES commitment_grade (code),
    escapable           boolean,

    -- approach, gear & descent
    approach_time_min   smallint,
    approach_difficulty smallint CHECK (approach_difficulty BETWEEN 1 AND 3),
    rack                text,
    rope                text,
    bolts_count         int,               -- NULL = unknown
    descent_method      text CHECK (descent_method IN ('walk-off', 'abseil', 'lower-off')),
    descent_abseils     smallint,
    descent_notes       text,

    -- conditions & orientation
    elevation_m         int,
    sun_window_code     text REFERENCES sun_window (code),
    wind_exposed        boolean,
    best_season         smallint[] CHECK (best_season <@ ARRAY[1,2,3,4,5,6,7,8,9,10,11,12]::smallint[]),

    -- editorial
    stars               smallint CHECK (stars BETWEEN 0 AND 3),

    -- prose (generated to the route-schema.md style rules)
    intro_html          text,
    approach_html       text,
    pitch_info_html     text,

    -- media (shape documented in route-schema.md; kept opaque)
    tile_image          jsonb,
    topo                jsonb,
    map_img             jsonb,

    last_update         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (area_id, name)
);
CREATE INDEX route_geom_gix ON route USING gist (geom);
CREATE INDEX route_name_trgm ON route USING gin (name gin_trgm_ops);
CREATE INDEX route_data_grade_ix ON route (data_grade);
CREATE INDEX route_status_ix ON route (status);

-- Set-valued facets (composable, following OpenBeta ClimbType).
CREATE TABLE route_discipline (
    route_id        bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    discipline_code text NOT NULL REFERENCES discipline (code),
    PRIMARY KEY (route_id, discipline_code)
);

CREATE TABLE route_feature (
    route_id     bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    feature_code text NOT NULL REFERENCES feature (code),
    PRIMARY KEY (route_id, feature_code)
);

-- How it climbs (sustained/pumpy/fingery/… — guidebook character shorthand).
CREATE TABLE route_character (
    route_id       bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    character_code text NOT NULL REFERENCES character (code),
    PRIMARY KEY (route_id, character_code)
);

-- Hazard flags. Safety-critical hazards may only be set with explicit source
-- evidence (taxonomy.md rule) — enforced by trigger below.
CREATE TABLE route_hazard (
    route_id      bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    hazard_code   text NOT NULL REFERENCES hazard (code),
    evidence_span text,
    source_url    text,
    PRIMARY KEY (route_id, hazard_code)
);

CREATE FUNCTION enforce_hazard_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT h.safety_critical FROM hazard h WHERE h.code = NEW.hazard_code)
       AND (NEW.evidence_span IS NULL OR NEW.evidence_span = '') THEN
        RAISE EXCEPTION 'hazard % is safety-critical: evidence_span required', NEW.hazard_code
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER route_hazard_evidence
    BEFORE INSERT OR UPDATE ON route_hazard
    FOR EACH ROW EXECUTE FUNCTION enforce_hazard_evidence();

-- All-systems grade object (OpenBeta GradeType): one row per system a grade is
-- known in; data_grade on route stays the sortable proxy.
CREATE TABLE route_grade (
    route_id          bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    grade_system_code text NOT NULL REFERENCES grade_system (code),
    value             text NOT NULL,
    PRIMARY KEY (route_id, grade_system_code)
);

-- Structured pitches (OpenBeta Pitch) — prose pitch_info_html stays for display.
CREATE TABLE pitch (
    route_id          bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    number            smallint NOT NULL CHECK (number >= 1),
    length_m          int,
    original_grade    text,
    grade_system_code text REFERENCES grade_system (code),
    bolts_count       int,
    description       text,
    PRIMARY KEY (route_id, number)
);

-- Structured first ascent (parsed best-effort; the rest stays in intro prose).
CREATE TABLE first_ascent (
    route_id   bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('fa', 'ffa')),
    climber    text,
    year       smallint,
    style_code text REFERENCES ascent_style (code),
    PRIMARY KEY (route_id, kind)
);

-- ---------------------------------------------------------------------------
-- Provenance & interop
-- ---------------------------------------------------------------------------

-- Field-level provenance: source URL, extracted span, confidence (parser rule #2).
CREATE TABLE provenance (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    route_id   bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    field      text NOT NULL,
    source_id  text REFERENCES source (id),
    source_url text,
    span       text,
    confidence real CHECK (confidence BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX provenance_route_field_ix ON provenance (route_id, field);

-- Structured external IDs for dedup/linking (ob_uuid, mp_id, ukc_id, thecrag_id).
CREATE TABLE external_ref (
    entity_type text NOT NULL CHECK (entity_type IN ('route', 'area')),
    entity_id   bigint NOT NULL,
    source_id   text NOT NULL REFERENCES source (id),
    external_id text NOT NULL,
    url         text,
    PRIMARY KEY (entity_type, entity_id, source_id),
    UNIQUE (source_id, external_id)
);

-- Prefixed outbound reference links (Video: / Travel: / Article: / Info: / Tides:).
CREATE TABLE route_reference (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    route_id bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    prefix   text CHECK (prefix IN ('Video', 'Travel', 'Article', 'Info', 'Tides')),
    text     text NOT NULL,
    url      text NOT NULL
);

CREATE TABLE guidebook (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    isbn    text UNIQUE,
    title   text NOT NULL,
    rrp     text,
    img_url text,
    link    text
);

CREATE TABLE route_guidebook (
    route_id     bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    guidebook_id bigint NOT NULL REFERENCES guidebook (id),
    page         text,
    description  text,
    PRIMARY KEY (route_id, guidebook_id)
);

-- Per-route monthly climatology (weatherData: rainyDays/tempH/tempL per month).
CREATE TABLE route_climatology (
    route_id   bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    month      smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    rainy_days real,
    temp_high  real,
    temp_low   real,
    PRIMARY KEY (route_id, month)
);

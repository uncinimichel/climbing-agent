-- 010 — taxonomy lookup tables.
-- One table per closed enum from knowledge/data/taxonomy.md ("every field is a closed
-- enum"). Values are seeded in 100_seed_taxonomy.sql; taxonomy.md stays the human source
-- of truth and these tables are its queryable mirror. Off-dictionary values fail as FK
-- violations — the DB enforces parser rule #1 (repair or reject, never surface).
SET search_path = climbing, public;

CREATE TABLE grade_system (
    code        text PRIMARY KEY,          -- BAS, UIAA, YDS, ALP, FS, N, V, Font, WI, AI, M, A, C
    name        text NOT NULL,
    region      text,
    discipline  text,                      -- rock | bouldering | ice | mixed | aid | alpine
    example     text
);

CREATE TABLE rock_type (
    code             text PRIMARY KEY,     -- granite, limestone, …
    friction_dry     real,                 -- measured dry hand-friction coefficient where known
    seeps            boolean NOT NULL DEFAULT false,
    fragile_when_wet boolean NOT NULL DEFAULT false,
    notes            text                  -- drying / seepage behaviour (feeds the condition model)
);

CREATE TABLE protection_grade (
    code       text PRIMARY KEY,           -- G, PG, PG-13, R, X, runout, terrain, UNSPECIFIED
    meaning    text NOT NULL,
    sort_order smallint                    -- ordinal severity where meaningful (G=0 … X=4)
);

CREATE TABLE discipline (
    code    text PRIMARY KEY,              -- trad, sport, multi-pitch, … (composable set)
    meaning text NOT NULL
);

CREATE TABLE feature (
    code text PRIMARY KEY                  -- slab, face, crack, ridge, arête, chimney, corner, roof, tufa, …
);

CREATE TABLE character (
    code    text PRIMARY KEY,              -- sustained, pumpy, fingery, fluttery, … (Rockfax/theCrag style tags)
    meaning text NOT NULL
);

CREATE TABLE incline (
    code       text PRIMARY KEY,           -- 'Slab' → 'Vertical' → 'Overhanging' compositions
    sort_order smallint NOT NULL
);

CREATE TABLE sun_window (
    code text PRIMARY KEY                  -- morning, afternoon, all-day, shade
);

CREATE TABLE hazard (
    code            text PRIMARY KEY,      -- tidal, seepage, … / rockfall, avalanche, …
    kind            text NOT NULL CHECK (kind IN ('route', 'objective')),
    meaning         text NOT NULL,
    safety_critical boolean NOT NULL DEFAULT false,  -- true → may only be set with explicit source evidence
    feeds           text                   -- downstream logic this flag drives
);

CREATE TABLE ascent_style (
    code        text PRIMARY KEY,          -- onsight, flash, redpoint, … (+ modifiers clean/dog)
    meaning     text NOT NULL,
    is_modifier boolean NOT NULL DEFAULT false
);

CREATE TABLE commitment_grade (
    code    text PRIMARY KEY,              -- NCCS I–VII · IFAS F…ED/ABO
    system  text NOT NULL CHECK (system IN ('NCCS', 'IFAS')),
    meaning text NOT NULL
);

-- Aspect is small and metadata-free — a domain, not a table.
CREATE DOMAIN aspect_dir AS text
    CHECK (VALUE IN ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'));

-- The observed dataGrade 1–7 ladder (knowledge/data/grade-conversion.md).
-- Store raw grade + system, sort by data_grade; never compare raw grades across systems.
CREATE TABLE grade_conversion (
    grade_system_code text NOT NULL REFERENCES grade_system (code),
    original_grade    text NOT NULL,
    data_grade        smallint NOT NULL CHECK (data_grade BETWEEN 1 AND 7),
    PRIMARY KEY (grade_system_code, original_grade)
);

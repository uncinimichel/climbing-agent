-- 032 — publication layer (decision #37): a guide/booklet is a CURATED,
-- ORDERED, freezable selection over the area tree — not a query. Encodes the
-- product decisions of 17 Jul 2026: booklets are a planner feature, they
-- exist only for covered areas ("the classics, verified": ~15-30
-- publish/human routes with approach + pitch prose), and publishing carries
-- disclaimer + per-route provenance in the rendered artifact. The publish
-- gate itself (coverage counts, human-prose-only, media rights) lives in the
-- publishing code, not a constraint — it needs cross-table counts.

CREATE TABLE guide (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug         text NOT NULL UNIQUE,
    title        text NOT NULL,
    subtitle     text,
    area_id      bigint NOT NULL REFERENCES area (id),   -- the booklet's root
    series       text,                     -- the collectible shelf ("Ireland")
    edition      smallint NOT NULL DEFAULT 1,
    status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'review', 'publish')),
    intro_md     text,                     -- editorial voice, owned prose only
    access_md    text,
    logistics_md text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Ordered chapters: essays, one section per sector, logistics.
CREATE TABLE guide_section (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guide_id bigint NOT NULL REFERENCES guide (id) ON DELETE CASCADE,
    position int NOT NULL,
    kind     text NOT NULL CHECK (kind IN ('essay', 'sector', 'logistics')),
    title    text NOT NULL,
    body_md  text,
    area_id  bigint REFERENCES area (id),  -- sector sections point at the tree
    UNIQUE (guide_id, position)
);

-- The picked routes, in narrative order, each with an editorial note —
-- curation-of-selection, distinct from the Studio's curation-of-rows.
CREATE TABLE guide_route (
    guide_id   bigint NOT NULL REFERENCES guide (id) ON DELETE CASCADE,
    section_id bigint REFERENCES guide_section (id) ON DELETE SET NULL,
    route_id   bigint NOT NULL REFERENCES route (id),
    position   int NOT NULL,
    note_md    text,                       -- "the one to fight for"
    PRIMARY KEY (guide_id, route_id)
);

-- A sold/collected booklet is a FROZEN snapshot (the corpus.json pattern):
-- the DB moves daily, an edition never does.
CREATE TABLE guide_edition (
    guide_id  bigint NOT NULL REFERENCES guide (id) ON DELETE CASCADE,
    edition   smallint NOT NULL,
    frozen    jsonb NOT NULL,
    frozen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (guide_id, edition)
);

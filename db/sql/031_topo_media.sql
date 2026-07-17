-- 031 — topo media layer (decision #37): crag photos + route lines as DATA.
-- Ported from multi-pitch.com's proven topoData model (38 live topos): the
-- photo is a media row, each route's line is a topo_line row of pixel
-- coordinates against that photo's ORIGINAL dimensions, and drawing happens
-- at render time — which is why every topo shares one visual language
-- (red line rgba(204,25,29,.95), pink belays, blue dashed descent).
-- Rights are first-class: a media row can't exist without credit + license,
-- because only owned/permissioned photos may ever reach a booklet.

CREATE TABLE media (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area_id     bigint REFERENCES area (id) ON DELETE SET NULL,
    kind        text NOT NULL CHECK (kind IN ('crag_photo', 'approach', 'map', 'other')),
    uri         text NOT NULL,               -- under db/uploads/topos/ (staging)
    width_px    int NOT NULL CHECK (width_px > 0),
    height_px   int NOT NULL CHECK (height_px > 0),
    credit      text NOT NULL,               -- photographer / rights holder
    license     text NOT NULL DEFAULT 'owned'
                CHECK (license IN ('owned', 'permission', 'cc')),
    permission_note text,                    -- who granted it, when, where recorded
    taken_at    date,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX media_area_idx ON media (area_id);

-- One drawable canvas over one photo. status gates what a booklet may embed.
CREATE TABLE topo (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    media_id    bigint NOT NULL REFERENCES media (id) ON DELETE CASCADE,
    area_id     bigint REFERENCES area (id) ON DELETE SET NULL,
    title       text,
    belay_size  int NOT NULL DEFAULT 24,     -- multi-pitch's one scale knob
    status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'publish')),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX topo_area_idx ON topo (area_id);

-- A route's line on a topo. Coordinates are pixels on the original image
-- (exactly multi-pitch's shape, so its 38 topos import losslessly):
--   line    [[x,y], ...]                       the climbing line, bottom → top
--   pitches [{belayPosition:[x,y], labelPosition:[x,y], grade, height}, ...]
--   descent [[x,y], ...]                       abseil / walk-off path
CREATE TABLE topo_line (
    topo_id     bigint NOT NULL REFERENCES topo (id) ON DELETE CASCADE,
    route_id    bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    line        jsonb NOT NULL,
    pitches     jsonb,
    descent     jsonb,
    source_id   text REFERENCES source (id), -- 'multipitch' for imported lines
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topo_id, route_id)
);
CREATE INDEX topo_line_route_idx ON topo_line (route_id);

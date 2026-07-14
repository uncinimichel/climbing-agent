-- 028 — parking becomes a LIST with labels (Michel 2026-07-14: "there may be multiple
-- pins"). Replaces 027's single route.parking point: real approaches have several
-- options (main car park, layby, high-tide alternative), each worth a name.
SET search_path = climbing, public;

CREATE TABLE route_parking (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    route_id bigint NOT NULL REFERENCES route (id) ON DELETE CASCADE,
    label    text NOT NULL DEFAULT 'parking',   -- "Morwenstow tea room car park"
    geom     geography (Point, 4326) NOT NULL,
    ord      smallint NOT NULL DEFAULT 1        -- 1 = the primary/recommended spot
);
CREATE INDEX route_parking_route_ix ON route_parking (route_id);

-- backfill from the 027 single-point column, then retire it
INSERT INTO route_parking (route_id, label, geom, ord)
SELECT id, 'parking', parking, 1 FROM route WHERE parking IS NOT NULL;

ALTER TABLE route DROP COLUMN parking;

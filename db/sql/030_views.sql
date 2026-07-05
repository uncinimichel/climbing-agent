-- 030 — inheritance views.
-- Area properties (grade_context, rock, aspect, timezone) cascade down the tree
-- (OpenBeta/theCrag "Inherits" semantics): the nearest ancestor's value wins unless
-- the row sets its own.
SET search_path = climbing, public;

CREATE VIEW area_resolved AS
WITH RECURSIVE anc AS (
    SELECT a.id, a.parent_id, a.name, a.kind,
           ARRAY[a.name]   AS path_tokens,
           a.grade_context AS eff_grade_context,
           a.rock_code     AS eff_rock_code,
           a.aspect        AS eff_aspect,
           a.timezone      AS eff_timezone
    FROM area a
    WHERE a.parent_id IS NULL
    UNION ALL
    SELECT c.id, c.parent_id, c.name, c.kind,
           anc.path_tokens || c.name,
           COALESCE(c.grade_context, anc.eff_grade_context),
           COALESCE(c.rock_code,     anc.eff_rock_code),
           COALESCE(c.aspect,        anc.eff_aspect),
           COALESCE(c.timezone,      anc.eff_timezone)
    FROM area c
    JOIN anc ON c.parent_id = anc.id
)
SELECT * FROM anc;

CREATE VIEW route_resolved AS
SELECT r.*,
       ar.path_tokens,
       ar.eff_grade_context,
       COALESCE(r.rock_code, ar.eff_rock_code) AS eff_rock_code,
       COALESCE(r.aspect,    ar.eff_aspect)    AS eff_aspect,
       COALESCE(r.timezone,  ar.eff_timezone)  AS eff_timezone
FROM route r
JOIN area_resolved ar ON ar.id = r.area_id;

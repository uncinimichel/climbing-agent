-- 105 — GENERATED taxonomy re-seed (decision #35). Do not edit by hand:
-- values are managed in Postgres via the Curation Studio's Taxonomy page and
-- exported here by db/tools/export_taxonomy.py so apply.sh reproduces the live
-- vocabulary. Exported 2026-07-13.
SET search_path = climbing, public;

-- discipline (14 values)
INSERT INTO discipline (code, meaning) VALUES
    ('aid', 'Weighting gear to progress (A/C grades).'),
    ('alpine', 'Mountain approach, altitude, mixed commitment.'),
    ('big-wall', 'Multi-day / very long.'),
    ('bouldering', 'Ropeless, low, over pads.'),
    ('deepwatersolo', 'Ropeless over water (DWS).'),
    ('ice', 'Frozen falls/ice (WI grades).'),
    ('mixed', 'Rock + ice (M grades).'),
    ('multi-pitch', 'Multiple rope-lengths with belay stances (the platform''s focus).'),
    ('single-pitch', 'One rope-length.'),
    ('snow', 'Snow climbing.'),
    ('sport', 'Pre-placed bolts.'),
    ('tr', 'Top-rope.'),
    ('trad', 'Leader-placed removable protection.'),
    ('via-ferrata', 'Protected cabled route.')
ON CONFLICT (code) DO UPDATE SET meaning = EXCLUDED.meaning;

-- feature (14 values)
INSERT INTO feature (code, meaning) VALUES
    ('arête', NULL),
    ('chimney', NULL),
    ('corner', NULL),
    ('crack', NULL),
    ('face', NULL),
    ('flake', NULL),
    ('groove', NULL),
    ('offwidth', NULL),
    ('pillar', NULL),
    ('pockets', NULL),
    ('ridge', NULL),
    ('roof', NULL),
    ('slab', NULL),
    ('tufa', NULL)
ON CONFLICT (code) DO UPDATE SET meaning = EXCLUDED.meaning;

-- character (10 values)
INSERT INTO character (code, meaning) VALUES
    ('crimpy', 'Specifically small-edge crimping.'),
    ('delicate', 'Balance/friction climbing; precision under little security.'),
    ('exposed', 'Big-air positions beyond what the protection grade captures.'),
    ('fingery', 'Significant small holds on the hard sections (Rockfax "f").'),
    ('fluttery', 'Bold — big fall potential and scary run-outs (Rockfax "h").'),
    ('powerful', 'Demands strength on steep ground (Rockfax "p").'),
    ('pumpy', 'Steep endurance climbing — the pump is the crux.'),
    ('reachy', 'Move spans favour reach; height-dependent.'),
    ('sustained', 'Lots of hard moves with little respite (Rockfax "s").'),
    ('technical', 'Intricate movement; body position over pulling.')
ON CONFLICT (code) DO UPDATE SET meaning = EXCLUDED.meaning;

-- hazard (15 values)
INSERT INTO hazard (code, kind, meaning, safety_critical, feeds) VALUES
    ('abseil', 'route', 'Requires an abseil (approach/descent).', false, 'gear & planning'),
    ('altitude', 'objective', 'High enough for thin air / altitude effects.', true, 'planning'),
    ('avalanche', 'objective', 'Avalanche terrain (snow slopes, couloirs).', true, 'safety'),
    ('boat', 'route', 'Reached by boat or swim.', false, 'logistics'),
    ('cornice', 'objective', 'Corniced ridge/summit.', true, 'safety'),
    ('crevasse', 'objective', 'Crevasse hazard on the approach/route.', true, 'safety'),
    ('grassLedges', 'route', 'Vegetated ledges (wet/awkward).', false, 'conditions'),
    ('loose', 'route', 'Loose / friable rock.', true, 'safety'),
    ('polished', 'route', 'Slick, polished rock.', false, 'difficulty-in-practice'),
    ('rockfall', 'objective', 'Rockfall-prone (loose gullies, thaw, parties above).', true, 'safety'),
    ('seepage', 'route', 'Weeps / holds water after rain.', true, 'Predictive Condition Algorithm'),
    ('serac', 'objective', 'Serac hazard on the approach/route.', true, 'safety'),
    ('stormExposed', 'objective', 'Exposed to lightning / no quick escape in a storm.', true, 'safety'),
    ('tidal', 'route', 'Access/base tide-dependent (sea cliffs).', true, 'tide-window logic (live 2026-07-05: planner tide tiles, Open-Meteo Marine)'),
    ('traverse', 'route', 'Significant traverse.', false, 'rope management / commitment')
ON CONFLICT (code) DO UPDATE SET kind = EXCLUDED.kind, meaning = EXCLUDED.meaning, safety_critical = EXCLUDED.safety_critical, feeds = EXCLUDED.feeds;

-- rock (17 values)
INSERT INTO rock_type (code, friction_dry, seeps, fragile_when_wet, notes) VALUES
    ('andesite', NULL, false, false, 'Volcanic; blocky, variable quality.'),
    ('basalt', NULL, false, false, 'Columnar jointing gives parallel crack systems; moderate drying.'),
    ('chalk', NULL, true, true, 'Soft marine limestone (Dover, Beachy Head) — friable, specialist trad; never climb wet; protection unreliable.'),
    ('conglomerate', NULL, false, false, 'Cobbles in matrix (Montserrat, Meteora, Riglos); pockety; protection often spaced.'),
    ('dolerite', NULL, false, false, 'Fair Head — grippy, dries reasonably; sea-cliff exposure.'),
    ('dolomite', NULL, false, false, 'Alpine; afternoon convection risk.'),
    ('gabbro', NULL, false, false, 'Extremely grippy (Skye); rough.'),
    ('gneiss', NULL, false, false, 'Banded metamorphic (Alps, Norway); generally solid, good friction.'),
    ('granite', NULL, false, false, 'Dries fast; low seepage; good friction when cool. Poorly-cemented grades shed grains.'),
    ('gritstone', NULL, false, true, 'Coarse UK sandstone — superb friction, rounded breaks; dries fast, greasy in humidity; avoid when wet.'),
    ('limestone', 0.64, true, false, 'Seeps for days; overhangs stay wet; slick when humid.'),
    ('quartzite', NULL, false, false, 'Hard, can be polished; variable drying.'),
    ('rhyolite', NULL, false, false, 'Welsh mountain rock; lichenous, slow to dry high up.'),
    ('sandstone', 0.74, false, true, 'Fragile when wet — do not climb wet (holds break). Highest dry friction.'),
    ('schist', NULL, false, false, 'Layered; can be friable and ledgy; holds moisture in breaks.'),
    ('slate', NULL, false, false, 'Non-porous — drains instantly but slick when wet; positive edges; quarried faces.'),
    ('volcanic', NULL, false, false, 'Lake District; broken, mountain drainage.')
ON CONFLICT (code) DO UPDATE SET friction_dry = EXCLUDED.friction_dry, seeps = EXCLUDED.seeps, fragile_when_wet = EXCLUDED.fragile_when_wet, notes = EXCLUDED.notes;

-- sun_window (4 values)
INSERT INTO sun_window (code, meaning) VALUES
    ('afternoon', NULL),
    ('all-day', NULL),
    ('morning', NULL),
    ('shade', NULL)
ON CONFLICT (code) DO UPDATE SET meaning = EXCLUDED.meaning;

-- protection (8 values)
INSERT INTO protection_grade (code, meaning, sort_order) VALUES
    ('G', 'Solid, plentiful protection.', 0),
    ('PG', 'Good protection, generally safe.', 1),
    ('PG-13', 'Mostly good; some runouts or marginal placements.', 2),
    ('R', 'Serious — runout; a fall risks injury.', 3),
    ('runout', 'A stretch with no protection below you (OpenBeta SafetyEnum).', NULL),
    ('terrain', 'Danger from the terrain itself, not fall distance.', NULL),
    ('UNSPECIFIED', 'Protection not yet assessed — the honest default.', NULL),
    ('X', 'Extreme — ground-fall / death potential.', 4)
ON CONFLICT (code) DO UPDATE SET meaning = EXCLUDED.meaning, sort_order = EXCLUDED.sort_order;

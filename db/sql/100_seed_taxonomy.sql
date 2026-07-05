-- 100 — seed the closed enums from knowledge/data/taxonomy.md.
-- taxonomy.md is the human source of truth; keep these in lockstep with it.
-- Extending an enum is a curation decision — add it there first, then here.
SET search_path = climbing, public;

INSERT INTO grade_system (code, name, region, discipline, example) VALUES
    ('BAS',  'British Adjectival (adjective + technical)', 'UK/Ireland',    'rock',       'VS 4c, HVS 5b, E1 5b'),
    ('UIAA', 'UIAA',                                       'Alps/Germany',  'rock',       'IV−, V+, VI+'),
    ('YDS',  'Yosemite Decimal',                           'US',            'rock',       '5.7, 5.10a'),
    ('ALP',  'Alpine (overall commitment)',                'Alps',          'alpine',     'PD, AD, D, TD, ED'),
    ('FS',   'French Sport',                               'Europe/sport',  'rock',       'f4c, f6a+'),
    ('N',    'Norwegian/Scandinavian',                     'Scandinavia',   'rock',       'N6−'),
    ('EW',   'Ewbank',                                     'Australia/NZ/ZA', 'rock',     '18, 24'),
    ('SX',   'Saxon (Dresden)',                            'Saxon Switzerland', 'rock',   'VIIb, VIIIa'),
    ('BRZ',  'Brazilian (overall + technical)',            'Brazil',        'rock',       'VIsup, 7b'),
    ('V',    'Hueco / V-scale',                            'US',            'bouldering', 'V0, V7'),
    ('Font', 'Fontainebleau',                              'Europe',        'bouldering', '6a+, 7c'),
    ('WI',   'Water ice',                                  'worldwide',     'ice',        'WI3, WI5'),
    ('AI',   'Alpine ice',                                 'worldwide',     'ice',        'AI3'),
    ('M',    'Mixed (rock + ice)',                         'worldwide',     'mixed',      'M6, M8'),
    ('D',    'Drytooling',                                 'worldwide',     'mixed',      'D8'),
    ('SCO',  'Scottish Winter (overall + technical)',      'Scotland',      'mixed',      'VI,7'),
    ('A',    'Aid',                                        'worldwide',     'aid',        'A2'),
    ('C',    'Clean aid',                                  'worldwide',     'aid',        'C3'),
    ('VF',   'Via ferrata (Hüsler/Schall)',                'Alps',          'via-ferrata','K3, C'),
    ('S',    'DWS seriousness (tide/depth/fall risk)',     'UK',            'deepwatersolo', 'S0–S3');

INSERT INTO rock_type (code, friction_dry, seeps, fragile_when_wet, notes) VALUES
    ('granite',      NULL, false, false, 'Dries fast; low seepage; good friction when cool. Poorly-cemented grades shed grains.'),
    ('limestone',    0.64, true,  false, 'Seeps for days; overhangs stay wet; slick when humid.'),
    ('dolerite',     NULL, false, false, 'Fair Head — grippy, dries reasonably; sea-cliff exposure.'),
    ('rhyolite',     NULL, false, false, 'Welsh mountain rock; lichenous, slow to dry high up.'),
    ('sandstone',    0.74, false, true,  'Fragile when wet — do not climb wet (holds break). Highest dry friction.'),
    ('gritstone',    NULL, false, true,  'Coarse UK sandstone — superb friction, rounded breaks; dries fast, greasy in humidity; avoid when wet.'),
    ('gabbro',       NULL, false, false, 'Extremely grippy (Skye); rough.'),
    ('quartzite',    NULL, false, false, 'Hard, can be polished; variable drying.'),
    ('volcanic',     NULL, false, false, 'Lake District; broken, mountain drainage.'),
    ('dolomite',     NULL, false, false, 'Alpine; afternoon convection risk.'),
    ('slate',        NULL, false, false, 'Non-porous — drains instantly but slick when wet; positive edges; quarried faces.'),
    ('gneiss',       NULL, false, false, 'Banded metamorphic (Alps, Norway); generally solid, good friction.'),
    ('schist',       NULL, false, false, 'Layered; can be friable and ledgy; holds moisture in breaks.'),
    ('basalt',       NULL, false, false, 'Columnar jointing gives parallel crack systems; moderate drying.'),
    ('conglomerate', NULL, false, false, 'Cobbles in matrix (Montserrat, Meteora, Riglos); pockety; protection often spaced.'),
    ('andesite',     NULL, false, false, 'Volcanic; blocky, variable quality.');

INSERT INTO protection_grade (code, meaning, sort_order) VALUES
    ('G',           'Solid, plentiful protection.',                                   0),
    ('PG',          'Good protection, generally safe.',                               1),
    ('PG-13',       'Mostly good; some runouts or marginal placements.',              2),
    ('R',           'Serious — runout; a fall risks injury.',                         3),
    ('X',           'Extreme — ground-fall / death potential.',                       4),
    ('runout',      'A stretch with no protection below you (OpenBeta SafetyEnum).',  NULL),
    ('terrain',     'Danger from the terrain itself, not fall distance.',             NULL),
    ('UNSPECIFIED', 'Protection not yet assessed — the honest default.',              NULL);

INSERT INTO discipline (code, meaning) VALUES
    ('trad',          'Leader-placed removable protection.'),
    ('sport',         'Pre-placed bolts.'),
    ('multi-pitch',   'Multiple rope-lengths with belay stances (the platform''s focus).'),
    ('single-pitch',  'One rope-length.'),
    ('alpine',        'Mountain approach, altitude, mixed commitment.'),
    ('big-wall',      'Multi-day / very long.'),
    ('bouldering',    'Ropeless, low, over pads.'),
    ('ice',           'Frozen falls/ice (WI grades).'),
    ('mixed',         'Rock + ice (M grades).'),
    ('snow',          'Snow climbing.'),
    ('aid',           'Weighting gear to progress (A/C grades).'),
    ('deepwatersolo', 'Ropeless over water (DWS).'),
    ('tr',            'Top-rope.'),
    ('via-ferrata',   'Protected cabled route.');

INSERT INTO feature (code) VALUES
    ('slab'), ('face'), ('crack'), ('ridge'), ('arête'), ('chimney'),
    ('corner'), ('groove'), ('roof'), ('offwidth'), ('flake'), ('tufa'), ('pockets'), ('pillar');

INSERT INTO character (code, meaning) VALUES
    ('sustained', 'Lots of hard moves with little respite (Rockfax "s").'),
    ('pumpy',     'Steep endurance climbing — the pump is the crux.'),
    ('powerful',  'Demands strength on steep ground (Rockfax "p").'),
    ('technical', 'Intricate movement; body position over pulling.'),
    ('fingery',   'Significant small holds on the hard sections (Rockfax "f").'),
    ('crimpy',    'Specifically small-edge crimping.'),
    ('reachy',    'Move spans favour reach; height-dependent.'),
    ('delicate',  'Balance/friction climbing; precision under little security.'),
    ('exposed',   'Big-air positions beyond what the protection grade captures.'),
    ('fluttery',  'Bold — big fall potential and scary run-outs (Rockfax "h").');

INSERT INTO incline (code, sort_order) VALUES
    ('Slab',                    1),
    ('Slab & Vertical',         2),
    ('Vertical',                3),
    ('Vertical & Overhanging',  4),
    ('Overhanging',             5);

INSERT INTO sun_window (code) VALUES
    ('morning'), ('afternoon'), ('all-day'), ('shade');

INSERT INTO hazard (code, kind, meaning, safety_critical, feeds) VALUES
    -- route character (safety-critical: only from explicit source evidence)
    ('tidal',        'route',     'Access/base tide-dependent (sea cliffs).',          true,  'tide-window logic (planned)'),
    ('seepage',      'route',     'Weeps / holds water after rain.',                   true,  'Predictive Condition Algorithm'),
    ('abseil',       'route',     'Requires an abseil (approach/descent).',            false, 'gear & planning'),
    ('traverse',     'route',     'Significant traverse.',                             false, 'rope management / commitment'),
    ('boat',         'route',     'Reached by boat or swim.',                          false, 'logistics'),
    ('polished',     'route',     'Slick, polished rock.',                             false, 'difficulty-in-practice'),
    ('loose',        'route',     'Loose / friable rock.',                             true,  'safety'),
    ('grassLedges',  'route',     'Vegetated ledges (wet/awkward).',                   false, 'conditions'),
    -- objective mountain hazards (all safety-critical: explicit evidence only)
    ('rockfall',     'objective', 'Rockfall-prone (loose gullies, thaw, parties above).', true, 'safety'),
    ('avalanche',    'objective', 'Avalanche terrain (snow slopes, couloirs).',        true,  'safety'),
    ('serac',        'objective', 'Serac hazard on the approach/route.',               true,  'safety'),
    ('crevasse',     'objective', 'Crevasse hazard on the approach/route.',            true,  'safety'),
    ('altitude',     'objective', 'High enough for thin air / altitude effects.',      true,  'planning'),
    ('stormExposed', 'objective', 'Exposed to lightning / no quick escape in a storm.', true, 'safety'),
    ('cornice',      'objective', 'Corniced ridge/summit.',                            true,  'safety');

INSERT INTO ascent_style (code, meaning, is_modifier) VALUES
    ('onsight',   'Lead first try, clean, no prior beta.',                          false),
    ('flash',     'Lead first try, clean, with prior beta.',                        false),
    ('redpoint',  'Clean lead after rehearsal.',                                    false),
    ('pinkpoint', 'Redpoint with gear pre-placed (now usually folded into redpoint).', false),
    ('headpoint', 'Trad: clean lead after top-rope practice.',                      false),
    ('groundup',  'Attempted from the ground up, no top-rope rehearsal.',           false),
    ('second',    'Climbed after the leader, roped from above.',                    false),
    ('toprope',   'Climbed on a rope anchored above.',                              false),
    ('solo',      'Climbed with no rope.',                                          false),
    ('aid',       'Weighting gear to make upward progress.',                        false),
    ('clean',     'Modifier: no falls, no resting on gear.',                        true),
    ('dog',       'Modifier: worked the route resting on gear (hangdog).',          true);

INSERT INTO commitment_grade (code, system, meaning) VALUES
    ('I',   'NCCS', 'A couple of hours.'),
    ('II',  'NCCS', 'A few hours.'),
    ('III', 'NCCS', 'Most of a morning.'),
    ('IV',  'NCCS', 'A full day.'),
    ('V',   'NCCS', 'Long day / possible bivvy.'),
    ('VI',  'NCCS', 'Multi-day.'),
    ('VII', 'NCCS', 'Remote multi-day big-wall.'),
    ('F',   'IFAS', 'Facile — easy.'),
    ('PD',  'IFAS', 'Peu difficile.'),
    ('AD',  'IFAS', 'Assez difficile.'),
    ('D',   'IFAS', 'Difficile.'),
    ('TD',  'IFAS', 'Très difficile.'),
    ('ED',  'IFAS', 'Extrêmement difficile.'),
    ('ABO', 'IFAS', 'Abominable — beyond ED.');

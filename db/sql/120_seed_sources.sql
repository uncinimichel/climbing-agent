-- 120 — seed the source registry (knowledge/roadmap/ingestion-plan.md starter set).
SET search_path = climbing, public;

INSERT INTO source (id, name, type, method, license, tos, regions, cadence, teaches) VALUES
    ('openbeta',        'OpenBeta',         'route-db', 'graphql', 'CC (open)',      'ingestion-encouraged', '{*}',            'monthly',   'hierarchical areas, cascading gradeContext, all-systems grades, composable disciplines, structured pitches'),
    ('thecrag',         'theCrag',          'route-db', 'scrape',  'proprietary',    'restricted',           '{*}',            'on-demand', 'grade context at any level, structured cascading tag-sets, 0–100 quality → stars'),
    ('ukclimbing',      'UKClimbing',       'route-db', 'scrape',  'proprietary',    'restricted',           '{GB,IE}',        'on-demand', 'faceted crag search (rocktype/aspect/type), first-class access notes'),
    ('mountainproject', 'Mountain Project', 'route-db', 'scrape',  'proprietary',    'restricted',           '{US,*}',         'on-demand', 'multi-discipline route type, grade-system auto-detect from leading chars'),
    ('multipitch',      'multi-pitch.com',  'route-db', 'manual',  'own data',       'owned',                '{*}',            'manual',    'the curated route record + description style this schema is grounded in');

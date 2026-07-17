-- 121 — the local-dev fixture source row. corpus.json carries a few routes
-- referenced to 'dev-fixtures' (see dev/sample_routes.sql), so a fresh clone's
-- first `ingest_corpus.py` restore needs this row to exist or its FKs fail
-- (first hit during the 16 Jul cloud restore; seeded here so every fresh DB —
-- docker first-boot, apply.sh, cloud — gets it automatically).
INSERT INTO source (id, name, type, method, license, tos, regions, cadence, teaches)
VALUES ('dev-fixtures', 'Dev fixtures', 'route-db', 'manual', 'n/a', 'owned', '{*}', 'manual', 'local development only')
ON CONFLICT (id) DO NOTHING;

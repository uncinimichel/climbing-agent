-- 001 — extensions + schema reset.
-- Re-runnable: drops and recreates the `climbing` schema (PostGIS lives in `public`).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP SCHEMA IF EXISTS climbing CASCADE;
CREATE SCHEMA climbing;

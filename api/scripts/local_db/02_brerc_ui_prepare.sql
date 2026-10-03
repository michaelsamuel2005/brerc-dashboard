-- =============================================================================
-- 02_brerc_ui_prepare.sql  —  run against the brerc_ui database, BEFORE
-- db/b6_schema.sql
--
--   psql -U postgres -d brerc_ui -f 02_brerc_ui_prepare.sql
--   psql -U postgres -d brerc_ui -f ..\..\..\db\b6_schema.sql
--
-- The brerc_ui tables themselves (occurrence_public, species,
-- distribution_cell, provenance ...) come from the repo's db/b6_schema.sql —
-- the same file the ETL re-runs on every initial load (force_full_reload), so
-- there is only one definition to keep in step.
--
-- This file only does what b6_schema.sql needs to already exist:
-- the PostGIS extension, used by the safety gate (ST_SnapToGrid) and by
-- distribution_cell.geom. It needs a superuser, once per database.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

SELECT postgis_full_version();

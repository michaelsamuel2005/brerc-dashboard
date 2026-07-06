-- 0001_extensions.sql
-- Enable PostGIS. Idempotent: safe to run repeatedly.
--
-- PostGIS gives us the spatial types and the functions the generalisation gate
-- depends on (ST_SnapToGrid, ST_Transform, ST_AsMVT, ST_TileEnvelope).

CREATE EXTENSION IF NOT EXISTS postgis;

-- Record which PostGIS/PostgreSQL we built against, for the handover docs.
DO $$
BEGIN
  RAISE NOTICE 'PostGIS % on PostgreSQL %', PostGIS_Lib_Version(), version();
END $$;

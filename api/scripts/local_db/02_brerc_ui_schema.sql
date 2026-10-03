-- =============================================================================
-- 02_brerc_ui_schema.sql  —  run in pgAdmin's Query Tool on the brerc_ui database
--
-- Creates everything inside the schema brerc_ui (every name is written as
-- brerc_ui.<name>, so nothing is created in, or dropped from, public):
--   tables  brerc_ui.species, brerc_ui.occurrence_public,
--           brerc_ui.distribution_cell, brerc_ui.provenance
--   views   brerc_ui.public_species, brerc_ui.public_records,
--           brerc_ui.public_cells, brerc_ui.public_provenance
--   role    brerc_api_ro  (read-only: the views, never the base tables)
--
-- The only thing placed in public is the PostGIS extension, which is where
-- PostGIS normally lives (the geometry type is referenced as public.geometry).
--
-- Safe to re-run: drops and recreates the brerc_ui tables (and their data).
-- =============================================================================

-- 1. PostGIS (needs a superuser; install via Stack Builder if this errors).
CREATE EXTENSION IF NOT EXISTS postgis SCHEMA public;

--    Stop here with a clear message if PostGIS is missing or was installed
--    into another schema (CREATE EXTENSION IF NOT EXISTS silently skips then).
DO $$
DECLARE
    ext_schema TEXT;
BEGIN
    SELECT extnamespace::regnamespace::text INTO ext_schema
    FROM pg_extension WHERE extname = 'postgis';

    IF ext_schema IS NULL THEN
        RAISE EXCEPTION 'PostGIS is not installed in this database.';
    ELSIF ext_schema <> 'public' THEN
        RAISE EXCEPTION 'PostGIS is installed in schema "%", not public. Run: DROP EXTENSION postgis CASCADE; CREATE EXTENSION postgis SCHEMA public;', ext_schema;
    END IF;
END
$$;

-- 2. The schema.
CREATE SCHEMA IF NOT EXISTS brerc_ui;

-- 3. The ETL and API use unqualified names (FROM occurrence_public ...), so
--    every new connection to this database must look in brerc_ui first.
--    Uses whichever database this Query Tool is connected to, so it works
--    whatever that database is called.
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET search_path = brerc_ui, public',
                   current_database());
END
$$;

-- 4. Clear out any previous run (brerc_ui only — public is never touched).
DROP VIEW  IF EXISTS brerc_ui.public_species, brerc_ui.public_records,
                     brerc_ui.public_cells, brerc_ui.public_provenance;
DROP TABLE IF EXISTS brerc_ui.distribution_cell, brerc_ui.occurrence_public,
                     brerc_ui.species, brerc_ui.provenance CASCADE;

-- -----------------------------------------------------------------------------
-- species — one row per species seen in the data (etl/aggregation/persist.py)
-- -----------------------------------------------------------------------------
CREATE TABLE brerc_ui.species (
    species_id       TEXT PRIMARY KEY,           -- BRERC species_no, as text
    scientific_name  TEXT,
    common_name      TEXT,
    species_group    TEXT NOT NULL,              -- 'unknown' when not in the dictionary
    record_count     INTEGER NOT NULL,
    first_year       INTEGER,
    last_year        INTEGER,
    has_image        BOOLEAN NOT NULL DEFAULT false,
    "Load"           TEXT,                       -- 'initial' / 'incremental'
    "Load_date"      TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- occurrence_public — one row per published record, already generalised
-- (etl/reconciliation/load.py). No precise coordinates are ever stored here.
-- -----------------------------------------------------------------------------
CREATE TABLE brerc_ui.occurrence_public (
    record_id          VARCHAR PRIMARY KEY,      -- BRERC unique_no
    species_id         TEXT NOT NULL REFERENCES brerc_ui.species (species_id),
    record_year        INTEGER NOT NULL,
    grid_ref           TEXT,                     -- 1 km grid square, e.g. ST6074
    precision_metres   INTEGER NOT NULL CHECK (precision_metres >= 100),  -- D0 floor
    locality           TEXT,
    verified           BOOLEAN,
    content_hash       TEXT,                     -- change detection
    date_mdb_modified  TIMESTAMPTZ,              -- change detection
    "Load"             TEXT,
    "Load_date"        TIMESTAMPTZ
);

CREATE INDEX occurrence_public_species_idx ON brerc_ui.occurrence_public (species_id);
CREATE INDEX occurrence_public_year_idx    ON brerc_ui.occurrence_public (record_year);

-- -----------------------------------------------------------------------------
-- distribution_cell — species x 1 km cell x year counts for the map, with
-- low counts already suppressed. Rebuilt every run (TRUNCATE + INSERT).
-- -----------------------------------------------------------------------------
CREATE TABLE brerc_ui.distribution_cell (
    cell_id           TEXT NOT NULL,             -- grid square, e.g. ST6074
    species_id        TEXT NOT NULL REFERENCES brerc_ui.species (species_id),
    record_year       INTEGER NOT NULL,
    precision_metres  INTEGER NOT NULL CHECK (precision_metres >= 100),
    record_count      INTEGER NOT NULL,
    verified_count    INTEGER NOT NULL,
    geom              public.geometry(Polygon, 4326) NOT NULL,
    "Load"            TEXT,
    "Load_date"       TIMESTAMPTZ,
    PRIMARY KEY (cell_id, species_id, record_year)
);

CREATE INDEX distribution_cell_geom_idx    ON brerc_ui.distribution_cell USING GIST (geom);
CREATE INDEX distribution_cell_species_idx ON brerc_ui.distribution_cell (species_id);

-- -----------------------------------------------------------------------------
-- provenance — the single "About this data" row (etl/provenance.py)
-- -----------------------------------------------------------------------------
CREATE TABLE brerc_ui.provenance (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    sources                     TEXT[],
    caveats                     TEXT[],
    last_updated                DATE,
    sensitivity_policy_summary  TEXT,
    "Load"                      TEXT,
    "Load_date"                 TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- Views — the ONLY things the API reads (api/app/routers).
-- -----------------------------------------------------------------------------
CREATE VIEW brerc_ui.public_species AS
SELECT species_id, scientific_name, common_name, species_group,
       record_count, first_year, last_year, has_image
FROM brerc_ui.species;

CREATE VIEW brerc_ui.public_records AS
SELECT o.record_id,
       o.species_id,
       s.scientific_name,
       s.common_name,
       o.record_year,
       o.grid_ref,
       o.precision_metres,
       o.locality AS place,                      -- coarse grid square, never the site name
       o.verified
FROM brerc_ui.occurrence_public o
JOIN brerc_ui.species s USING (species_id);

CREATE VIEW brerc_ui.public_cells AS
SELECT cell_id, species_id, record_year, precision_metres,
       record_count, verified_count, geom
FROM brerc_ui.distribution_cell;

CREATE VIEW brerc_ui.public_provenance AS
SELECT sources, caveats, last_updated, sensitivity_policy_summary
FROM brerc_ui.provenance
WHERE id = 1;

-- -----------------------------------------------------------------------------
-- Read-only API role: may read the views, nothing else.
-- Set its password separately:  ALTER ROLE brerc_api_ro PASSWORD '...';
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brerc_api_ro') THEN
        CREATE ROLE brerc_api_ro LOGIN;
    END IF;
END
$$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO brerc_api_ro', current_database());
END
$$;
GRANT USAGE ON SCHEMA brerc_ui, public TO brerc_api_ro;
REVOKE ALL ON brerc_ui.species, brerc_ui.occurrence_public,
              brerc_ui.distribution_cell, brerc_ui.provenance FROM brerc_api_ro;
GRANT SELECT ON brerc_ui.public_species, brerc_ui.public_records,
                brerc_ui.public_cells, brerc_ui.public_provenance TO brerc_api_ro;

-- Check: should list 4 tables and 4 views, all in schema brerc_ui,
-- plus the database you ran this in (use that name in api/.env).
SELECT current_database() AS database, table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'brerc_ui'
ORDER BY table_type, table_name;

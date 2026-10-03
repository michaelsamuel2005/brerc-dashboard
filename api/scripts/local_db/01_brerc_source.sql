-- =============================================================================
-- 01_brerc_source.sql  —  run against the brerc_source database
--
--   psql -U postgres -d brerc_source -f 01_brerc_source.sql
--
-- Creates a mock of BRERC's source database:
--   brerc_source.occurrences_raw        every column of the BRERC export, as-is
--   brerc_source.species_dictionary     the master species dictionary
--   brerc_source.vw_occurrences         what the ETL reads (source.records_query)
--   brerc_source.vw_species_dictionary  what the ETL reads (source.dictionary_query)
--
-- The views rename BRERC's export headers to the names in safety.yaml's
-- 'columns:' block, so safety.yaml.example works unchanged. In particular:
--   DateMDBmodified -> date_mdb_modified
--   YearEnd         -> year_end
--
-- Safe to re-run: drops and recreates the schema (and its data).
-- =============================================================================

DROP SCHEMA IF EXISTS brerc_source CASCADE;
CREATE SCHEMA brerc_source;

-- -----------------------------------------------------------------------------
-- Raw export: one column per header in the BRERC .xls, lower-cased.
-- Loaded by load_source_data.py.
-- -----------------------------------------------------------------------------
CREATE TABLE brerc_source.occurrences_raw (
    scientific_name   TEXT,
    common_name       TEXT,
    grid_ref          TEXT,
    place             TEXT,
    date_of_record    TEXT,        -- free text: "10/06/2014", "June 2014", "circa 1787"
    abundance         TEXT,
    sex_stage         TEXT,
    record_type       TEXT,
    startdate         DATE,
    species_no        TEXT,        -- TEXT: BRERC also uses masked ids such as BRERC1234
    precise_date      DATE,
    vague_date        TEXT,
    vitality          TEXT,
    digital_or_paper  TEXT,
    date_entered      DATE,
    bnes              TEXT,
    bcc               TEXT,
    sglos             TEXT,
    nsom              TEXT,
    yearend           INTEGER,
    yearstart         INTEGER,
    enddate           DATE,
    comments          TEXT,
    source            TEXT,
    bliss             TEXT,
    taxabrerc         TEXT,
    unique_no         BIGINT PRIMARY KEY,
    licence           TEXT,
    sensitive         TEXT,        -- 'Yes' / 'No'
    taxonid           TEXT,        -- NBN taxon version key
    easting           INTEGER,
    northing          INTEGER,
    taxanb            TEXT,
    brercstatus       TEXT,
    national_status   TEXT,
    legalprotect      TEXT,
    bap               TEXT,
    rspb_list         TEXT,
    brercnotable      TEXT,
    datemdbmodified   DATE,
    verified          TEXT,        -- 'Accepted – correct' (en dash) etc.
    eastings          INTEGER,
    northings         INTEGER
);

-- -----------------------------------------------------------------------------
-- Species dictionary, using BRERC's own column names (safety.yaml
-- 'dictionary_columns:'). Loaded by load_source_data.py.
-- -----------------------------------------------------------------------------
CREATE TABLE brerc_source.species_dictionary (
    species_no  TEXT PRIMARY KEY,
    scientific  TEXT NOT NULL,
    common_nam  TEXT,
    nbn_number  TEXT,
    taxanb      TEXT
);

-- -----------------------------------------------------------------------------
-- The views the ETL queries. Only the columns safety.yaml maps are exposed:
-- place, comments, grid_ref and recorder details never leave this database.
-- -----------------------------------------------------------------------------
CREATE VIEW brerc_source.vw_occurrences AS
SELECT
    unique_no,
    scientific_name,
    common_name,
    species_no,
    record_type,
    verified,
    easting,
    northing,
    date_of_record,
    datemdbmodified AS date_mdb_modified,
    yearend         AS year_end,
    sensitive,
    abundance,
    sex_stage,
    vitality
FROM brerc_source.occurrences_raw;

CREATE VIEW brerc_source.vw_species_dictionary AS
SELECT
    scientific,
    species_no,
    nbn_number,
    common_nam,
    taxanb
FROM brerc_source.species_dictionary;

-- -----------------------------------------------------------------------------
-- Optional: a read-only role for the ETL's source connection, mirroring
-- production ("the ETL only ever SELECTs from it"). Uncomment and set a
-- password if you want to test with it instead of postgres.
-- -----------------------------------------------------------------------------
-- CREATE ROLE brerc_source_ro LOGIN PASSWORD 'CHANGE_ME';
-- GRANT CONNECT ON DATABASE brerc_source TO brerc_source_ro;
-- GRANT USAGE ON SCHEMA brerc_source TO brerc_source_ro;
-- GRANT SELECT ON brerc_source.vw_occurrences, brerc_source.vw_species_dictionary
--     TO brerc_source_ro;

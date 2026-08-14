-- =============================================================================
-- END-TO-END TEST — STEPS 1 & 2: a mock of BRERC's OWN database and view
-- =============================================================================
-- WHAT THIS IS FOR
-- Everything we have built so far starts from the UI database — i.e. from data
-- that is already safe. This file provides the missing piece at the other end:
-- a stand-in for BRERC's source database, so the whole chain can be tested
-- source -> ETL -> UI database -> dashboard without touching real records.
--
-- IMPORTANT: every row here is INVENTED. No real BRERC data is in this file and
-- none must ever be added to it. The point is to exercise the pipeline, not to
-- reproduce their holdings.
--
-- WHY THE UNSAFE COLUMNS ARE DELIBERATELY PRESENT
-- The source table below intentionally contains the things that must NEVER reach
-- the public: precise eastings/northings, a recorder name, free-text comments and
-- a precise place name. That is the entire point. If they were left out, the test
-- could not prove the safety boundary works — it would only prove that data we
-- never supplied does not appear. We supply them, and then assert they are gone.
--
-- HOW TO RUN (against a throwaway database, never your real one):
--   psql -v ON_ERROR_STOP=1 "$SOURCE_URL" -f db/test/e2e_source_mock.sql
--
-- The pipeline is pointed at this by setting, in config/safety.yaml:
--   source:
--     mode: "database"
--     records_query:    "SELECT * FROM brerc_source.vw_occurrences"
--     dictionary_query: "SELECT * FROM brerc_source.vw_species_dictionary"
-- =============================================================================

DROP SCHEMA IF EXISTS brerc_source CASCADE;
CREATE SCHEMA brerc_source;


-- =============================================================================
-- 1. THE SOURCE TABLE — what BRERC's own database holds
-- =============================================================================
-- Column names follow the mapping the pipeline expects (config/safety.yaml
-- `columns:`). BRERC's real view has ~39 columns; these are the ones the ETL
-- actually consumes, plus the unsafe ones we need in order to test that they are
-- stripped. Adding the remaining attribute columns later will not change the
-- pipeline's behaviour, because it selects the columns it needs by name.
CREATE TABLE brerc_source.occurrences (
    unique_no          VARCHAR PRIMARY KEY,   -- record key (D7). Not always numeric.
    species_no         TEXT    NOT NULL,      -- BRERC SPECIES_NO. Digits, or BRERC-prefixed.
    scientific_name    TEXT    NOT NULL,
    nbn_number         TEXT,                  -- NULL for BRERC-created species (their email)
    record_type        TEXT,                  -- feature sensitivity lives here (roost/sett/holt)
    sensitive          TEXT,                  -- the view's own flag: 'Yes' / 'No'
    verified           TEXT,                  -- verification status as supplied
    eastings           INTEGER,               -- PRECISE — must never reach the public tier
    northings          INTEGER,               -- PRECISE — must never reach the public tier
    date_of_record     DATE,
    date_mdb_modified  TIMESTAMPTZ NOT NULL,  -- drives incremental loading
    -- The three below are the classic leak risks. Present on purpose so the test
    -- can prove they are dropped, never because the pipeline needs them.
    recorder1          TEXT,                  -- personal data (UK GDPR)
    place              TEXT,                  -- precise site name
    comments           TEXT                   -- free text; often contains exact locations
);


-- =============================================================================
-- 2. THE SPECIES DICTIONARY — used to resolve names to SPECIES_NO
-- =============================================================================
-- BRERC's real dictionary is 96,824 species, of which only 14,830 have records.
-- A handful is enough here: what matters is that resolution, synonyms and
-- BRERC-created species (no NBN number) all behave.
-- These are BRERC's REAL column names, as supplied. Several are truncated to ten
-- characters (COMMON_NAM, BRERCSTATU, VERIFYCOD2, OUTOFAVON) — the signature of
-- a DBF/shapefile export, so don't "tidy" them: the pipeline matches on them.
-- PostgreSQL folds unquoted identifiers to lower case, which is what the ETL's
-- cleaning step expects.
CREATE TABLE brerc_source.species_dictionary (
    SPECIES_NO   TEXT PRIMARY KEY,
    AUTHORITY    TEXT,          -- taxonomic authority, e.g. "(Linnaeus, 1758)"
    SCIENTIFIC   TEXT NOT NULL,
    COMMON_NAM   TEXT,          -- common name (truncated column name)
    FAMILY       TEXT,
    BRERCSTATU   TEXT,          -- BRERC's own status field
    TAXANB       TEXT,          -- taxon number
    NBN_NUMBER   TEXT,          -- NULL where BRERC created the entry
    VERIFYCODE   TEXT,
    OUTOFAVON    TEXT,          -- CAREFUL: 'No' = we DO hold records.
                                -- 'Yes' = we do NOT. Inverted, per BRERC's email.
    SENSITIVE    TEXT,          -- 'Yes' / 'No' — the dictionary's own flag
    VERIFYCOD2   TEXT
);


-- =============================================================================
-- 3. THE VIEWS — what the pipeline actually reads
-- =============================================================================
-- BRERC serve us a view rather than the base table, so the mock does the same.
CREATE VIEW brerc_source.vw_occurrences AS
SELECT * FROM brerc_source.occurrences;

CREATE VIEW brerc_source.vw_species_dictionary AS
SELECT * FROM brerc_source.species_dictionary;

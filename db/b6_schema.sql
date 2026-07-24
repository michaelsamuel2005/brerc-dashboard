-- =============================================================================
-- B6 — UI-database schema, fail-closed public views, indexes, read-only role
-- =============================================================================
-- STATUS: DRAFT PROPOSAL (Victor). The exact columns are the SEAM between the
--   pipeline (Ting Ting, B1-B5, which WRITES these tables) and serving (Victor,
--   B6-B9, which READS them). Agree the shape with Ting Ting before relying on
--   it. See the "OPEN QUESTIONS FOR TING TING" note at the bottom.
--
-- WHAT THIS FILE IS: the real version of the safety boundary that b0_staging_
--   setup.sql only sketched. The rule (Backend Plan §2): the UI database is the
--   safety boundary. The pipeline writes ONLY already-safe data into the base
--   tables; the PUBLIC VIEWS below re-enforce safety on the way out, and are the
--   ONLY thing Martin and FastAPI are allowed to read. So even if an upstream
--   bug slips through, a leak is structurally impossible.
--
-- SAFETY GUARANTEES THIS FILE ENFORCES (the B6 "definition of done"):
--   1. Forbidden fields (recorder name, precise coords, free-text, source db,
--      sensitivity flag) do not EXIST in the public views — excluded by column.
--   2. No coordinate is finer than the 100 m floor (D0) — a CHECK constraint,
--      re-asserted in the views.
--   3. The API's database role can SELECT the public views and NOTHING else —
--      it cannot write, and cannot touch the base tables at all.
--
-- HOW TO RUN (local dev):
--   psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
--   psql "$DATABASE_URL" -f db/b6_schema.sql
--   then: pytest api/tests/test_b6_safety.py   (proves the guarantees above)
--
-- IMPORTANT: contains NO real data and NO real BRERC field names beyond the
--   safe, public ones. Never paste real records here.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- =============================================================================
-- SECTION 1 — BASE TABLES  (written by the pipeline; the "safe copy")
-- These deliberately DO NOT HAVE columns for recorder name, precise eastings/
-- northings, free-text place/comments, the source database (BLISS), the precise
-- date, or the sensitivity flag. Those never enter the UI database at all.
-- =============================================================================

-- 1a. Species index — one row per species actually loaded (Backend Plan B4).
--     species_id is the real SPECIES_NO from the dictionary (synonym-resolved,
--     D4), so it is stable and safe to expose.
DROP TABLE IF EXISTS species CASCADE;
CREATE TABLE species (
    species_id      BIGINT      PRIMARY KEY,        -- real SPECIES_NO (D4)
    scientific_name TEXT        NOT NULL,
    common_name     TEXT,
    species_group   TEXT        NOT NULL,           -- e.g. birds / mammals
    record_count    INTEGER     NOT NULL DEFAULT 0,
    first_year      INTEGER,
    last_year       INTEGER,
    has_image       BOOLEAN     NOT NULL DEFAULT FALSE
);

-- 1b. Per-record public rows (feeds /api/records). Already generalised by the
--     pipeline: only a grid reference at a stated precision + a COARSE locality.
--     No precise point is stored — not even a geometry column.
DROP TABLE IF EXISTS occurrence_public CASCADE;
CREATE TABLE occurrence_public (
    record_id        BIGINT   PRIMARY KEY,          -- unique_No (D7 recon key)
    species_id       BIGINT   NOT NULL REFERENCES species(species_id),
    record_year      INTEGER  NOT NULL,             -- YEAR only — never precise date
    grid_ref         TEXT     NOT NULL,             -- generalised OS grid ref
    precision_metres INTEGER  NOT NULL
                     CHECK (precision_metres >= 100),   -- D0 100 m floor
    locality         TEXT,                          -- coarse: authority + grid sq
    verified         BOOLEAN  NOT NULL DEFAULT FALSE -- D5 (accepted); legacy marked
    -- NO eastings, northings, recorder1, bliss, comments, precise_date,
    -- is_sensitive — absent by construction.
);

-- 1c. Pre-aggregated distribution grid (species x cell x year). This is the
--     MATERIALISED layer Martin turns into tiles (B7) and /api/distribution/cells
--     reads — never the ~5M raw rows. Geometry is the (already generalised) cell
--     polygon, so a tile can only ever carry a coarse square, never a point.
DROP TABLE IF EXISTS distribution_cell CASCADE;
CREATE TABLE distribution_cell (
    cell_id          TEXT     NOT NULL,             -- e.g. "ST57" (grid square)
    species_id       BIGINT   NOT NULL REFERENCES species(species_id),
    record_year      INTEGER  NOT NULL,
    precision_metres INTEGER  NOT NULL
                     CHECK (precision_metres >= 100),   -- D0 100 m floor
    record_count     INTEGER  NOT NULL CHECK (record_count  >= 0),
    verified_count   INTEGER  NOT NULL CHECK (verified_count >= 0),
    geom             geometry(Polygon, 4326) NOT NULL,  -- cell polygon (WGS84)
    PRIMARY KEY (cell_id, species_id, record_year)
    -- Low-count suppression (k-anonymity) for rare/sensitive cells is applied by
    -- the pipeline (B4) BEFORE writing here; the serving layer trusts safe input
    -- and re-checks the floor. See OPEN QUESTIONS.
);

-- 1d. Dataset-level provenance (feeds /api/meta/provenance). Single row.
DROP TABLE IF EXISTS provenance CASCADE;
CREATE TABLE provenance (
    id                         INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    sources                    TEXT[]  NOT NULL,
    caveats                    TEXT[]  NOT NULL,
    last_updated               DATE    NOT NULL,
    sensitivity_policy_summary TEXT    NOT NULL
);


-- =============================================================================
-- SECTION 2 — INDEXES
-- =============================================================================
-- Spatial index for the map/tiles (GiST is the PostGIS spatial index type).
CREATE INDEX idx_cell_geom      ON distribution_cell USING GIST (geom);
-- Filtering the grid by species / year (the common map queries).
CREATE INDEX idx_cell_species   ON distribution_cell (species_id);
CREATE INDEX idx_cell_year      ON distribution_cell (record_year);
-- Filtering / sorting the record list.
CREATE INDEX idx_occ_species    ON occurrence_public (species_id);
CREATE INDEX idx_occ_year       ON occurrence_public (record_year);
-- Species list ordering + grouping.
CREATE INDEX idx_species_name   ON species (scientific_name);
CREATE INDEX idx_species_group  ON species (species_group);
-- NOTE (B8): species search/autocomplete may want a pg_trgm trigram index on
-- scientific_name / common_name — add it when the search endpoint is built.


-- =============================================================================
-- SECTION 3 — PUBLIC VIEWS  (the fail-closed serving boundary)
-- The API and Martin read ONLY these. Each selects only safe columns, so the
-- forbidden fields cannot be returned, and re-asserts the 100 m floor.
-- (Views run with the owner's rights by default, so the read-only API role
--  needs SELECT on the VIEW only — never on the base tables. That is the boundary.)
-- =============================================================================

CREATE OR REPLACE VIEW public_species AS
SELECT species_id, scientific_name, common_name, species_group,
       record_count, first_year, last_year, has_image
FROM species;

CREATE OR REPLACE VIEW public_records AS
SELECT o.record_id,
       s.scientific_name,
       s.common_name,
       o.record_year,
       o.grid_ref,
       o.precision_metres,
       o.locality AS place,          -- contract calls it "place": coarse only
       o.verified
FROM occurrence_public AS o
JOIN species AS s USING (species_id)
WHERE o.precision_metres >= 100;      -- belt-and-braces on top of the CHECK

CREATE OR REPLACE VIEW public_cells AS
SELECT cell_id, species_id, record_year, precision_metres,
       record_count, verified_count, geom
FROM distribution_cell
WHERE precision_metres >= 100;

CREATE OR REPLACE VIEW public_provenance AS
SELECT sources, caveats, last_updated, sensitivity_policy_summary
FROM provenance
WHERE id = 1;


-- =============================================================================
-- SECTION 4 — READ-ONLY API ROLE
-- The FastAPI service connects as this role. It may SELECT the four public views
-- and NOTHING else — no writes, and no access to the base tables.
-- =============================================================================

-- Create the role once (no password here — never commit secrets). Set the
-- password out-of-band, e.g.:  ALTER ROLE brerc_api_ro WITH PASSWORD '...';
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'brerc_api_ro') THEN
        CREATE ROLE brerc_api_ro LOGIN;
    END IF;
END
$$;

-- Least privilege: usage on the schema, SELECT on the public views only.
GRANT USAGE ON SCHEMA public TO brerc_api_ro;
GRANT SELECT ON public_species, public_records, public_cells, public_provenance
    TO brerc_api_ro;
-- Base tables are deliberately NOT granted, so the role cannot reach raw data.
-- (Defence in depth — a new role has no table rights by default anyway.)


-- =============================================================================
-- SECTION 5 — QUICK MANUAL CHECK (optional; the real proof is test_b6_safety.py)
-- =============================================================================
-- Expect: the four views exist and none lists a forbidden column.
--   \dv public_*
-- Expect: brerc_api_ro can read a view but not a base table.
--   SELECT has_table_privilege('brerc_api_ro','public_records','SELECT');  -- t
--   SELECT has_table_privilege('brerc_api_ro','occurrence_public','SELECT');-- f


-- =============================================================================
-- OPEN QUESTIONS FOR TING TING (agree before this is final)
-- =============================================================================
-- 1. Column shape: does your pipeline output match these tables (names/types)?
--    Especially: species_id = resolved SPECIES_NO; record_id = unique_No.
-- 2. Grid cells: what identifies a cell (grid_ref string like "ST57"), and do you
--    write the cell POLYGON geometry, or should the view build it from the ref?
-- 3. Year grain: is distribution_cell keyed per (cell, species, YEAR) as here, or
--    do you pre-sum across years? (Affects /api/summary recordsByYear + filters.)
-- 4. Verified/legacy (D5): do you write only Accepted rows, or Accepted + legacy
--    with a marker? If marked, we need a safe column for "legacy" that is not a
--    sensitivity marker.
-- 5. Low-count suppression: confirm it happens in your aggregation (B4) so the
--    serving views never see a count that could pinpoint a sensitive record.
-- =============================================================================

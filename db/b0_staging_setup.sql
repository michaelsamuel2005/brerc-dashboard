-- IMPORTANT: the rows below are made up for testing. Never paste real BRERC
-- records into this file — it lives in the repo.
-- =============================================================================

-- 1. Staging table: roughly the shape of a source occurrence record.
--    Deliberately includes the UNSAFE columns (recorder name, precise coords)
--    so we can prove the view strips them out.

-- =============================================================================

DROP TABLE IF EXISTS occurrences_staging CASCADE;

CREATE TABLE occurrences_staging (
    unique_no        BIGINT PRIMARY KEY,       -- true unique key (confirmed in EDA)
    species_no       INTEGER NOT NULL,         -- BRERC SPECIES_NO
    scientific_name  TEXT NOT NULL,
    common_name      TEXT,
    species_group    TEXT NOT NULL,            -- e.g. birds / mammals
    record_year      INTEGER NOT NULL,
    eastings         INTEGER NOT NULL,         -- precise BNG — NEVER public
    northings        INTEGER NOT NULL,         -- precise BNG — NEVER public
    recorder1        TEXT,                     -- personal data — NEVER public
    place            TEXT,                     -- free text — dropped for public
    verified         BOOLEAN NOT NULL DEFAULT FALSE,
    is_sensitive     BOOLEAN NOT NULL DEFAULT FALSE  -- placeholder flag; the
    -- real classifier is B2/B6
);

-- =============================================================================
-- 2. Sample rows — ALL INVENTED. Coordinates are plausible-for-Bristol numbers
--    chosen by hand, not taken from any real record.
-- =============================================================================

INSERT INTO occurrences_staging
(
    unique_no,
    species_no,
    scientific_name,
    common_name,
    species_group,
    record_year,
    eastings,
    northings,
    recorder1,
    place,
    verified,
    is_sensitive
)
VALUES
(1, 100, 'Erithacus rubecula', 'Robin',       'birds',
    2024, 358400, 172600, 'A. Example', 'Test Park',  TRUE,  FALSE),

(2, 100, 'Erithacus rubecula', 'Robin',       'birds',
    2023, 359100, 173200, 'B. Example', 'Test Green', TRUE,  FALSE),

(3, 100, 'Erithacus rubecula', 'Robin',       'birds',
    2022, 357800, 171900, 'A. Example', 'Test Wood',  FALSE, FALSE),

(4, 200, 'Bufo bufo', 'Common Toad', 'amphibians',
    2024, 360200, 174100, 'C. Example', 'Test Pond',  TRUE,  FALSE),

(5, 200, 'Bufo bufo', 'Common Toad', 'amphibians',
    2021, 361000, 174800, 'C. Example', 'Test Ditch', TRUE,  FALSE),

-- A deliberately "sensitive" row, to prove the view blurs it harder:
(6, 300, 'Lutra lutra', 'Otter', 'mammals',
    2025, 356500, 170300, 'D. Example', 'Test River', TRUE,  TRUE),

(7, 300, 'Lutra lutra', 'Otter', 'mammals',
    2024, 356900, 170700, 'D. Example', 'Test Bank',  FALSE, TRUE);

-- =============================================================================
-- 3. THE SAFE OCCURRENCE VIEW — this is the boundary the API is allowed to read.
--
--    ST_SnapToGrid rounds a point down to the nearest grid corner, which is how
--    "blurring" is done — the real position is replaced by its grid cell.
-- =============================================================================

DROP VIEW IF EXISTS public_occurrences;

CREATE VIEW public_occurrences AS
SELECT
    o.unique_no AS record_id,
    o.species_no AS species_id,
    o.scientific_name,
    o.common_name,
    o.species_group,
    o.record_year,
    o.verified,

    -- Precision depends on sensitivity: coarser for sensitive records.
    CASE
        WHEN o.is_sensitive THEN 10000
        ELSE 1000
    END AS precision_metres,

    -- Snap the precise BNG point to the chosen grid, in EPSG:27700,
    -- then hand back WGS84 (EPSG:4326) for the map front end.
    ST_Y(
        ST_Transform(
            ST_SnapToGrid(
                ST_SetSRID(
                    ST_MakePoint(o.eastings, o.northings),
                    27700
                ),
                CASE
                    WHEN o.is_sensitive THEN 10000
                    ELSE 1000
                END
            ),
            4326
        )
    ) AS latitude,

    ST_X(
        ST_Transform(
            ST_SnapToGrid(
                ST_SetSRID(
                    ST_MakePoint(o.eastings, o.northings),
                    27700
                ),
                CASE
                    WHEN o.is_sensitive THEN 10000
                    ELSE 1000
                END
            ),
            4326
        )
    ) AS longitude

FROM occurrences_staging AS o;

-- NOTE: recorder1, place, eastings, northings are absent by construction.
-- The API must query ONLY this view, never occurrences_staging.

-- =============================================================================
-- 4. SAFE SPECIES VIEW — this is what /api/species reads.
--
--    Species information is derived from the staging records. No unsafe
--    occurrence-level fields are exposed.
-- =============================================================================

DROP VIEW IF EXISTS public_species;

CREATE VIEW public_species AS
SELECT
    o.species_no AS species_id,
    o.scientific_name,
    MAX(o.common_name) AS common_name,
    MAX(o.species_group) AS species_group,
    COUNT(*) AS record_count,
    MIN(o.record_year) AS first_year,
    MAX(o.record_year) AS last_year,
    FALSE AS has_image

FROM occurrences_staging AS o

GROUP BY
    o.species_no,
    o.scientific_name;

-- =============================================================================
-- 5. Check it worked.
--
--    public_occurrences should contain 7 rows.
--    public_species should contain 3 species.
--    Record counts should be 3, 2, and 2.
--    Lutra lutra should have precision_metres = 10000.
-- =============================================================================

SELECT *
FROM public_occurrences
ORDER BY record_id;

SELECT *
FROM public_species
ORDER BY species_id;
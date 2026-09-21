\set ON_ERROR_STOP on

-- Synthetic-only five-million-row source for the manually triggered scale gate.
-- Values are generated here; this file contains no BRERC records or identifiers.
DROP SCHEMA IF EXISTS dashboard CASCADE;
DO $fixture$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brerc_extract') THEN
        EXECUTE 'DROP OWNED BY brerc_extract';
        EXECUTE 'DROP ROLE brerc_extract';
    END IF;
END
$fixture$;

CREATE SCHEMA dashboard AUTHORIZATION postgres;

CREATE TABLE dashboard.synthetic_records (
    scientific_name varchar(120),
    common_name varchar(120),
    grid_ref varchar(25),
    place varchar(254),
    date_of_record varchar(50),
    abundance varchar(35),
    sex_stage varchar(45),
    record_type varchar(55),
    start_date date,
    species_no varchar(20),
    precise_date date,
    vague_date varchar(35),
    vitality varchar(15),
    digital_or_paper varchar(10),
    date_entered date,
    bnes varchar(4),
    bcc varchar(3),
    sglos varchar(4),
    nsom varchar(4),
    year_end varchar(5),
    year_start varchar(5),
    end_date date,
    comments varchar(254),
    source varchar(50),
    bliss varchar(100),
    taxa_brerc varchar(60),
    unique_no numeric(13,2),
    licence varchar(1),
    sensitive varchar(4),
    taxo_id varchar(20),
    easting numeric(13,2),
    northing numeric(13,2),
    taxa_nb text,
    brerc_status text,
    national_status text,
    legal_protection text,
    bap text,
    rspb text,
    brerc_notable text
);

-- Cohort design, independently asserted by the scale runner:
--   1..2  : licensed two-row sparse cohort, suppressed when k=3;
--   3     : unlicensed, withheld before publication;
--   4..6  : licensed sensitive cohort, published at no finer than 1 km;
--   7..9  : licensed ordinary control cohort;
--   10..5,000,000: 100 large licensed ordinary cohorts.
INSERT INTO dashboard.synthetic_records (
    scientific_name,
    common_name,
    grid_ref,
    place,
    abundance,
    record_type,
    species_no,
    year_end,
    comments,
    source,
    unique_no,
    licence,
    sensitive,
    easting,
    northing,
    taxa_nb
)
SELECT
    CASE
        WHEN sequence_no <= 2 THEN 'Synthetic sparse species'
        WHEN sequence_no = 3 THEN 'Synthetic unlicensed species'
        WHEN sequence_no <= 6 THEN 'Synthetic sensitive species'
        WHEN sequence_no <= 9 THEN 'Synthetic ordinary control species'
        ELSE 'Synthetic bulk species ' || lpad((sequence_no % 100)::text, 2, '0')
    END,
    CASE
        WHEN sequence_no <= 2 THEN 'Synthetic sparse'
        WHEN sequence_no = 3 THEN 'Synthetic unlicensed'
        WHEN sequence_no <= 6 THEN 'Synthetic sensitive'
        WHEN sequence_no <= 9 THEN 'Synthetic ordinary control'
        ELSE 'Synthetic bulk ' || lpad((sequence_no % 100)::text, 2, '0')
    END,
    CASE
        WHEN sequence_no <= 6 THEN 'ST587721'
        WHEN sequence_no <= 9 THEN 'ST597721'
        WHEN sequence_no % 2 = 0 THEN 'ST587721'
        ELSE 'ST597721'
    END,
    'SYNTHETIC-PRIVATE-SCALE-PLACE-MUST-NOT-CROSS',
    '1',
    'field record',
    -- species_no is varchar(20) in the reviewed 39-column contract, so every
    -- cohort identifier here must be at most twenty characters.  The earlier
    -- spellings SYNTH-SCALE-UNLICENSED (22) and SYNTH-SCALE-SENSITIVE (21)
    -- overflowed the column and aborted the whole 5,000,000-row generation.
    CASE
        WHEN sequence_no <= 2 THEN 'SYNTH-SCALE-SPARSE'
        WHEN sequence_no = 3 THEN 'SYNTH-SCALE-UNLIC'
        WHEN sequence_no <= 6 THEN 'SYNTH-SCALE-SENS'
        WHEN sequence_no <= 9 THEN 'SYNTH-SCALE-ORDINARY'
        ELSE 'SYNTH-SCALE-' || lpad((sequence_no % 100)::text, 3, '0')
    END,
    CASE
        WHEN sequence_no <= 9 THEN '2024'
        ELSE (2020 + (sequence_no % 5))::text
    END,
    'SYNTHETIC-PRIVATE-SCALE-COMMENT-MUST-NOT-CROSS',
    'SYNTHETIC-PRIVATE-SCALE-SOURCE-MUST-NOT-CROSS',
    sequence_no::numeric(13,2),
    CASE WHEN sequence_no = 3 THEN 'n' ELSE 'y' END,
    CASE WHEN sequence_no BETWEEN 4 AND 6 THEN 'Yes' ELSE 'No' END,
    CASE
        WHEN sequence_no <= 6 THEN 358721.25
        WHEN sequence_no <= 9 THEN 359721.50
        WHEN sequence_no % 2 = 0 THEN 358721.25
        ELSE 359721.50
    END,
    CASE
        WHEN sequence_no <= 6 THEN 172145.75
        WHEN sequence_no <= 9 THEN 172166.50
        WHEN sequence_no % 2 = 0 THEN 172145.75
        ELSE 172166.50
    END,
    'Synthetic deferred taxon group'
FROM generate_series(1, 5000000) AS generated(sequence_no);

CREATE VIEW dashboard.main_data_dash AS
SELECT
    scientific_name,
    common_name,
    grid_ref,
    place,
    date_of_record,
    abundance,
    sex_stage,
    record_type,
    start_date,
    species_no,
    precise_date,
    vague_date,
    vitality,
    digital_or_paper,
    date_entered,
    bnes,
    bcc,
    sglos,
    nsom,
    year_end,
    year_start,
    end_date,
    comments,
    source,
    bliss,
    taxa_brerc,
    unique_no,
    licence,
    sensitive,
    taxo_id,
    easting,
    northing,
    taxa_nb,
    brerc_status,
    national_status,
    legal_protection,
    bap,
    rspb,
    brerc_notable
FROM dashboard.synthetic_records;

CREATE ROLE brerc_extract LOGIN PASSWORD 'synthetic-e2e-extract-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE brerc_extract SET default_transaction_read_only = on;
REVOKE TEMPORARY ON DATABASE brerc_loader_source_e2e FROM PUBLIC;
GRANT CONNECT ON DATABASE brerc_loader_source_e2e TO brerc_extract;
GRANT USAGE ON SCHEMA dashboard TO brerc_extract;
GRANT SELECT ON TABLE dashboard.main_data_dash TO brerc_extract;

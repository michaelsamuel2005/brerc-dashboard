\set ON_ERROR_STOP on

-- One entirely synthetic source row for the real connector -> loader test.
-- The exact 39-column shape mirrors the reviewed source contract, while the
-- values are invented and deliberately include private-looking sentinels that
-- must be removed before anything reaches the destination publication tier.
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
) VALUES
    (
        'Synthetic species safety',
        'Synthetic safety species',
        'ST587721',
        'PRIVATE-E2E-PLACE-SENSITIVE-MUST-NOT-CROSS',
        '7',
        'field record',
        'SYNTH-E2E-1',
        '2024',
        'PRIVATE-E2E-COMMENT-SENSITIVE-MUST-NOT-CROSS',
        'PRIVATE-E2E-RAW-SOURCE-MUST-NOT-CROSS',
        9001.00,
        'y',
        'Yes',
        358721.25,
        172145.75,
        'Synthetic taxon group'
    ),
    (
        'Synthetic species ordinary',
        'Synthetic ordinary species',
        'ST597221',
        'PRIVATE-E2E-PLACE-ORDINARY-MUST-NOT-CROSS',
        '2',
        'field record',
        'SYNTH-E2E-2',
        '2023',
        'PRIVATE-E2E-COMMENT-ORDINARY-MUST-NOT-CROSS',
        'PRIVATE-E2E-RAW-SOURCE-MUST-NOT-CROSS',
        9002.00,
        'y',
        'No',
        359221.50,
        172166.50,
        'Synthetic taxon group'
    ),
    (
        'Synthetic species unlicensed',
        'Synthetic unlicensed species',
        'ST587721',
        'PRIVATE-E2E-PLACE-UNLICENSED-MUST-NOT-CROSS',
        '1',
        'field record',
        'SYNTH-E2E-3',
        '2022',
        'PRIVATE-E2E-COMMENT-UNLICENSED-MUST-NOT-CROSS',
        'PRIVATE-E2E-RAW-SOURCE-MUST-NOT-CROSS',
        9003.00,
        'n',
        'No',
        358733.25,
        172177.75,
        'Synthetic taxon group'
    );

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

\set ON_ERROR_STOP on

DROP SCHEMA IF EXISTS dashboard CASCADE;
DO $fixture$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brerc_extract') THEN
        EXECUTE 'DROP OWNED BY brerc_extract';
        EXECUTE 'DROP ROLE brerc_extract';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brerc_column_reader') THEN
        EXECUTE 'DROP OWNED BY brerc_column_reader';
        EXECUTE 'DROP ROLE brerc_column_reader';
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
    unique_no,
    licence,
    sensitive,
    easting,
    northing
) VALUES
    (
        'Synthetic species alpha', 'Synthetic alpha', 'ST587721',
        'PRIVATE-SYNTHETIC-PLACE-A', '1', 'field record', 'SYNTH-1', '2024',
        'PRIVATE-SYNTHETIC-COMMENT-A', 1.00, 'y', 'No', 358700.00, 172100.00
    ),
    (
        'Synthetic species beta', 'Synthetic beta', 'ST587721',
        'PRIVATE-SYNTHETIC-PLACE-B', '2', 'field record', 'SYNTH-2', '2023',
        'PRIVATE-SYNTHETIC-COMMENT-B', 2.00, 'y', 'Yes', 358701.00, 172101.00
    ),
    (
        'Synthetic species alpha', 'Synthetic alpha', 'ST5972',
        'PRIVATE-SYNTHETIC-PLACE-C', NULL, 'field record', 'SYNTH-1', '2022',
        'PRIVATE-SYNTHETIC-COMMENT-C', 3.00, 'y', 'No', 359000.00, 172000.00
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

CREATE ROLE brerc_extract LOGIN PASSWORD 'synthetic-extract-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE brerc_extract SET default_transaction_read_only = on;
REVOKE TEMPORARY ON DATABASE brerc_connector FROM PUBLIC;
GRANT CONNECT ON DATABASE brerc_connector TO brerc_extract;
GRANT USAGE ON SCHEMA dashboard TO brerc_extract;
GRANT SELECT ON TABLE dashboard.main_data_dash TO brerc_extract;

CREATE ROLE brerc_column_reader LOGIN PASSWORD 'synthetic-column-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE brerc_column_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE brerc_connector TO brerc_column_reader;
GRANT USAGE ON SCHEMA dashboard TO brerc_column_reader;
GRANT SELECT (
    unique_no,
    species_no,
    scientific_name,
    grid_ref,
    year_end,
    common_name,
    abundance,
    record_type,
    licence,
    sensitive
) ON dashboard.main_data_dash TO brerc_column_reader;

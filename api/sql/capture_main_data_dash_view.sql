-- BRERC source-view identity capture.  Reads catalogue metadata only: no rows.
-- Run with psql -X -qAt --set=ON_ERROR_STOP=1 and retain the output securely.

\set ON_ERROR_STOP on

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

-- The rendering settings through lc_numeric are part of the digest profile.
-- The runtime connector must use them before calling pg_get_viewdef(oid,
-- false).  The following timeouts and lock are acquisition safeguards; they
-- are not fields in the captured identity document.
SET LOCAL search_path = pg_catalog;
SET LOCAL client_encoding = 'UTF8';
SET LOCAL quote_all_identifiers = on;
SET LOCAL standard_conforming_strings = on;
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL IntervalStyle = 'postgres';
SET LOCAL TimeZone = 'UTC';
SET LOCAL extra_float_digits = 3;
SET LOCAL bytea_output = 'hex';
SET LOCAL lc_numeric = 'C';
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';

-- Freeze the named view against CREATE OR REPLACE VIEW, ALTER VIEW, DROP and
-- ownership/option changes while its definition and catalogue columns are
-- captured.  REPEATABLE READ fixes the data/catalogue snapshot, but acquiring
-- the relation lock explicitly also closes the DDL race between looking up the
-- object and calling pg_get_viewdef.  ACCESS SHARE is the weakest table lock
-- and is permitted in a read-only transaction.  A concurrent migration waits;
-- this capture fails after lock_timeout rather than attesting mixed evidence.
LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE;

WITH target AS MATERIALIZED (
    SELECT
        c.oid,
        c.relkind,
        c.relpersistence,
        c.relowner,
        c.reloptions,
        n.nspname,
        c.relname
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n
      ON n.oid = c.relnamespace
    WHERE n.nspname = 'dashboard'
      AND c.relname = 'main_data_dash'
      AND c.relkind = 'v'
),
exactly_one AS MATERIALIZED (
    -- Division by zero makes an absent/wrong-kind object a loud failure.
    SELECT 1 / count(*)::integer AS assertion
    FROM target
),
definition AS MATERIALIZED (
    SELECT
        t.*,
        pg_catalog.pg_get_viewdef(t.oid, false) AS sql_text,
        x.assertion
    FROM target AS t
    CROSS JOIN exactly_one AS x
),
column_evidence AS (
    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'ordinal_position', ordinal_position,
                'column_name', column_name,
                'data_type', data_type,
                'udt_schema', udt_schema,
                'udt_name', udt_name,
                'character_maximum_length', character_maximum_length,
                'numeric_precision', numeric_precision,
                'numeric_scale', numeric_scale,
                'is_nullable', is_nullable,
                'collation_schema', collation_schema,
                'collation_name', collation_name
            )
            ORDER BY ordinal_position
        ),
        '[]'::jsonb
    ) AS columns
    FROM information_schema.columns
    WHERE table_catalog = current_database()
      AND table_schema = 'dashboard'
      AND table_name = 'main_data_dash'
)
SELECT jsonb_build_object(
    'artifact_format', 'brerc-view-capture/v1',
    'captured_at_utc',
        to_char(
            transaction_timestamp() AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
    'postgres', jsonb_build_object(
        'database', current_database(),
        'server_version', current_setting('server_version'),
        'server_version_num', current_setting('server_version_num')::integer,
        'server_major', current_setting('server_version_num')::integer / 10000,
        'server_encoding', current_setting('server_encoding'),
        'captured_by_database_role', current_user
    ),
    'session', jsonb_build_object(
        'search_path', current_setting('search_path'),
        'client_encoding', current_setting('client_encoding'),
        'quote_all_identifiers', current_setting('quote_all_identifiers'),
        'standard_conforming_strings', current_setting('standard_conforming_strings'),
        'DateStyle', current_setting('DateStyle'),
        'IntervalStyle', current_setting('IntervalStyle'),
        'TimeZone', current_setting('TimeZone'),
        'extra_float_digits', current_setting('extra_float_digits'),
        'bytea_output', current_setting('bytea_output'),
        'lc_numeric', current_setting('lc_numeric')
    ),
    'object', jsonb_build_object(
        'schema', d.nspname,
        'name', d.relname,
        'qualified_name', d.nspname || '.' || d.relname,
        'relation_oid', d.oid,
        'relkind', d.relkind,
        'relpersistence', d.relpersistence,
        'owner', pg_catalog.pg_get_userbyid(d.relowner),
        'reloptions', COALESCE(
            (
                SELECT jsonb_agg(option ORDER BY option)
                FROM unnest(COALESCE(d.reloptions, ARRAY[]::text[])) AS options(option)
            ),
            '[]'::jsonb
        )
    ),
    'view_definition', d.sql_text,
    -- Hex preserves the exact bytes across JSON, shells and line endings.
    'view_definition_utf8_hex', encode(convert_to(d.sql_text, 'UTF8'), 'hex'),
    'columns', ce.columns
)::text
FROM definition AS d
CROSS JOIN column_evidence AS ce
WHERE d.assertion = 1;

ROLLBACK;

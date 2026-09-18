\set ON_ERROR_STOP on

-- Read-only catalogue audit for the two production web-service login roles.
-- Run as the destination database owner during controlled provisioning. The
-- values below are role/database names, never passwords or connection strings.
\if :{?expected_database}
\else
  \echo 'expected_database psql variable is required' >&2
  \quit 3
\endif
\if :{?api_login}
\else
  \echo 'api_login psql variable is required' >&2
  \quit 3
\endif
\if :{?monitor_login}
\else
  \echo 'monitor_login psql variable is required' >&2
  \quit 3
\endif

SELECT pg_catalog.set_config(
    'brerc.audit.expected_database', :'expected_database', false
);
SELECT pg_catalog.set_config('brerc.audit.api_login', :'api_login', false);
SELECT pg_catalog.set_config('brerc.audit.monitor_login', :'monitor_login', false);

DO $audit$
DECLARE
    expected_database text := pg_catalog.current_setting(
        'brerc.audit.expected_database'
    );
    api_login text := pg_catalog.current_setting('brerc.audit.api_login');
    monitor_login text := pg_catalog.current_setting('brerc.audit.monitor_login');
    login_name text;
    capability_name text;
    login_oid oid;
    login_attributes record;
    direct_roles text[];
    effective_roles text[];
BEGIN
    IF expected_database = '' OR api_login = '' OR monitor_login = '' THEN
        RAISE EXCEPTION 'runtime-login audit inputs must be nonempty';
    END IF;
    IF api_login = monitor_login THEN
        RAISE EXCEPTION 'API and monitor login roles must be distinct';
    END IF;
    IF pg_catalog.current_database() <> expected_database THEN
        RAISE EXCEPTION 'runtime-login audit is connected to the wrong database';
    END IF;

    FOR login_name, capability_name IN
        SELECT *
        FROM (
            VALUES (api_login, 'brerc_api'), (monitor_login, 'brerc_monitor')
        ) AS expected(login_name, capability_name)
    LOOP
        SELECT
            role.oid,
            role.rolcanlogin,
            role.rolinherit,
            role.rolsuper,
            role.rolcreatedb,
            role.rolcreaterole,
            role.rolreplication,
            role.rolbypassrls,
            role.rolconfig
        INTO login_attributes
        FROM pg_catalog.pg_roles AS role
        WHERE role.rolname = login_name;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'required runtime login role does not exist';
        END IF;
        login_oid := login_attributes.oid;

        IF NOT login_attributes.rolcanlogin
            OR NOT login_attributes.rolinherit
            OR login_attributes.rolsuper
            OR login_attributes.rolcreatedb
            OR login_attributes.rolcreaterole
            OR login_attributes.rolreplication
            OR login_attributes.rolbypassrls
        THEN
            RAISE EXCEPTION 'runtime login has unsafe role attributes';
        END IF;
        IF NOT (
            COALESCE(login_attributes.rolconfig, ARRAY[]::text[])
            @> ARRAY['default_transaction_read_only=on']::text[]
        ) THEN
            RAISE EXCEPTION 'runtime login lacks a read-only role default';
        END IF;

        SELECT COALESCE(
            pg_catalog.array_agg(parent.rolname::text ORDER BY parent.rolname),
            ARRAY[]::text[]
        )
        INTO direct_roles
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS parent
            ON parent.oid = membership.roleid
        WHERE membership.member = login_oid;

        SELECT COALESCE(
            pg_catalog.array_agg(role.rolname::text ORDER BY role.rolname),
            ARRAY[]::text[]
        )
        INTO effective_roles
        FROM pg_catalog.pg_roles AS role
        WHERE role.oid <> login_oid
          AND pg_catalog.pg_has_role(login_oid, role.oid, 'USAGE');

        IF direct_roles <> ARRAY[capability_name]::text[]
            OR effective_roles <> ARRAY[capability_name]::text[]
        THEN
            RAISE EXCEPTION 'runtime login has unexpected role membership';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS parent
                ON parent.oid = membership.roleid
            WHERE membership.member = login_oid
              AND parent.rolname = capability_name
              AND (
                  membership.admin_option
                  OR NOT membership.inherit_option
              )
        ) THEN
            RAISE EXCEPTION 'runtime login has unsafe membership options';
        END IF;

        -- Runtime logins inherit narrowly granted capabilities from one
        -- reviewed NOLOGIN role. They must not own database objects or receive
        -- parallel direct grants that bypass that capability boundary.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_database AS database
            WHERE database.datname = pg_catalog.current_database()
              AND database.datdba = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS namespace
            WHERE namespace.nspowner = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            WHERE relation.relowner = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS routine
            WHERE routine.proowner = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_type AS type
            WHERE type.typowner = login_oid
        ) THEN
            RAISE EXCEPTION 'runtime login owns a database object';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_database AS database
            CROSS JOIN LATERAL pg_catalog.aclexplode(database.datacl) AS acl
            WHERE database.datname = pg_catalog.current_database()
              AND acl.grantee = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS namespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
            WHERE acl.grantee = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
            WHERE acl.grantee = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS routine
            CROSS JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl
            WHERE acl.grantee = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_type AS type
            CROSS JOIN LATERAL pg_catalog.aclexplode(type.typacl) AS acl
            WHERE acl.grantee = login_oid
        ) OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_default_acl AS defaults
            CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
            WHERE defaults.defaclrole = login_oid
               OR acl.grantee = login_oid
        ) THEN
            RAISE EXCEPTION 'runtime login has a direct or default object grant';
        END IF;
    END LOOP;
END
$audit$;

SELECT 'runtime login audit passed' AS result;

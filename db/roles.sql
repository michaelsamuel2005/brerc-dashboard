-- BRERC destination-database group roles.
--
-- Run once as a PostgreSQL administrator before the schema migration. Login
-- roles are deployment-specific and receive membership in these NOLOGIN group
-- roles outside source control. This file never creates users or credentials.
--
-- Re-running is safe only when an existing role already has the exact
-- non-privileged posture below. It refuses an unsafe pre-existing role rather
-- than silently weakening it with ALTER ROLE.

BEGIN;

DO $roles$
DECLARE
    role_name text;
    role_row record;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'brerc_loader',
        'brerc_api',
        'brerc_martin',
        'brerc_monitor'
    ]
    LOOP
        SELECT
            rolcanlogin,
            rolsuper,
            rolcreatedb,
            rolcreaterole,
            rolreplication,
            rolbypassrls,
            rolinherit,
            oid
        INTO role_row
        FROM pg_catalog.pg_roles
        WHERE rolname = role_name;

        IF NOT FOUND THEN
            EXECUTE pg_catalog.format(
                'CREATE ROLE %I NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB '
                'NOCREATEROLE NOREPLICATION NOBYPASSRLS',
                role_name
            );
        ELSIF role_row.rolcanlogin
            OR role_row.rolsuper
            OR role_row.rolcreatedb
            OR role_row.rolcreaterole
            OR role_row.rolreplication
            OR role_row.rolbypassrls
            OR role_row.rolinherit
        THEN
            RAISE EXCEPTION
                'role % exists with an unsafe attribute; refusing to alter it',
                role_name;
        END IF;

        -- A harmless-looking NOLOGIN role can still inherit or SET ROLE into a
        -- powerful parent role. Repository group roles may have members, but
        -- they must never themselves be members of another role.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members
            WHERE member = role_row.oid
        ) THEN
            RAISE EXCEPTION
                'role % inherits another role; refusing effective privilege leakage',
                role_name;
        END IF;
    END LOOP;
END
$roles$;

COMMIT;

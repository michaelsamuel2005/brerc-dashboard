-- BRERC notification-delivery group roles.
--
-- Apply as a PostgreSQL administrator after db/roles.sql and before migration
-- 0002.  Deployment-specific LOGIN roles and credentials are intentionally not
-- created here.  Each service/operator login receives membership in exactly one
-- of these NOLOGIN capability roles outside source control.

BEGIN;

DO $notifier_roles$
DECLARE
    role_name text;
    role_row record;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'brerc_notifier',
        'brerc_notifier_operator'
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

            SELECT
                rolcanlogin,
                rolsuper,
                rolcreatedb,
                rolcreaterole,
                rolreplication,
                rolbypassrls,
                rolinherit,
                oid
            INTO STRICT role_row
            FROM pg_catalog.pg_roles
            WHERE rolname = role_name;
        END IF;

        IF role_row.rolcanlogin
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

        -- Members may inherit this capability role.  The capability role itself
        -- must never inherit or SET ROLE into a more privileged parent.
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
$notifier_roles$;

COMMIT;

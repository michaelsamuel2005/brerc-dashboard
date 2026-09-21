\set ON_ERROR_STOP on

-- Synthetic deployment logins for the destination integration test only.
-- The reviewed migration owns privileges through NOLOGIN group roles.  These
-- deliberately unprivileged LOGIN roles inherit only their one reviewed
-- NOLOGIN capability role.  The loader validates current_user as the distinct
-- deployment login, which catches a grant that exists only on paper.
CREATE ROLE brerc_release_loader_test LOGIN PASSWORD 'synthetic-loader-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE brerc_api_test LOGIN PASSWORD 'synthetic-api-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE brerc_martin_test LOGIN PASSWORD 'synthetic-martin-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE brerc_monitor_test LOGIN PASSWORD 'synthetic-monitor-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS;

GRANT brerc_loader TO brerc_release_loader_test;
GRANT brerc_api TO brerc_api_test;
GRANT brerc_martin TO brerc_martin_test;
GRANT brerc_monitor TO brerc_monitor_test;

ALTER ROLE brerc_api_test SET default_transaction_read_only = on;
ALTER ROLE brerc_martin_test SET default_transaction_read_only = on;
ALTER ROLE brerc_monitor_test SET default_transaction_read_only = on;

REVOKE TEMPORARY ON DATABASE brerc_ui_integration FROM PUBLIC;

#!/bin/sh
# Creates the deployment login the API connects as.
#
# It is a LOGIN role whose only privilege comes from membership of the reviewed
# NOLOGIN group role `brerc_api`, which the migration grants SELECT on the
# serve.* views and nothing else. Keeping the login separate from the group is
# what lets the privileges be reviewed once and the credential be rotated
# independently.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE brerc_api_service LOGIN PASSWORD '${API_DB_PASSWORD}'
    NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS;
GRANT brerc_api TO brerc_api_service;
-- Belt and braces: even a mistaken grant elsewhere cannot make this session
-- write, because every transaction it opens starts read-only.
ALTER ROLE brerc_api_service SET default_transaction_read_only = on;
REVOKE TEMPORARY ON DATABASE ${POSTGRES_DB} FROM PUBLIC;
SQL

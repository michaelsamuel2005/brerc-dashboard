#!/bin/bash
# Runs once, the first time the database container starts, AFTER the schema
# scripts have created the read-only role `brerc_api_ro`. It sets that role's
# password from the RO_PASSWORD environment variable (supplied by docker-compose),
# so the password never has to live in a committed .sql file.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    ALTER ROLE brerc_api_ro LOGIN PASSWORD '${RO_PASSWORD}';
EOSQL

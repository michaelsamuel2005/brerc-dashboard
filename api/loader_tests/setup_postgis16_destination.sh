#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 7 ]]; then
  echo "usage: setup_postgis16_destination.sh CONTAINER ROLES_SQL MIGRATION_0001_SQL MIGRATION_0002_SQL MIGRATION_0003_SQL FIXTURE_SQL OUTPUT_DIRECTORY" >&2
  exit 2
fi

container="$1"
roles_sql="$2"
migration_0001_sql="$3"
migration_0002_sql="$4"
migration_0003_sql="$5"
fixture_sql="$6"
output_directory="$7"

mkdir -p "$output_directory"
chmod 700 "$output_directory"

# A one-day synthetic CA is enough for the isolated CI service.  Both DNS and
# IP subject names are present because libpq verify-full checks the name used by
# the test connection, not merely whether TLS was negotiated.
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -subj "/CN=BRERC synthetic destination test CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -keyout "$output_directory/ca.key" \
  -out "$output_directory/ca.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout "$output_directory/server.key" \
  -out "$output_directory/server.csr" >/dev/null 2>&1
openssl x509 -req -sha256 -days 1 \
  -in "$output_directory/server.csr" \
  -CA "$output_directory/ca.crt" \
  -CAkey "$output_directory/ca.key" \
  -CAcreateserial \
  -extfile <(printf '%s\n' \
    'basicConstraints=critical,CA:FALSE' \
    'keyUsage=critical,digitalSignature,keyEncipherment' \
    'extendedKeyUsage=serverAuth' \
    'subjectAltName=DNS:localhost,IP:127.0.0.1') \
  -out "$output_directory/server.crt" >/dev/null 2>&1

docker exec -u root "$container" mkdir -p /var/lib/postgresql/tls
docker exec -u root "$container" chown postgres:postgres /var/lib/postgresql/tls
docker cp "$output_directory/server.crt" "$container:/var/lib/postgresql/tls/server.crt"
docker cp "$output_directory/server.key" "$container:/var/lib/postgresql/tls/server.key"
docker exec -u root "$container" chown postgres:postgres \
  /var/lib/postgresql/tls/server.crt /var/lib/postgresql/tls/server.key
docker exec -u root "$container" chmod 600 /var/lib/postgresql/tls/server.key
docker exec -u root "$container" chmod 644 /var/lib/postgresql/tls/server.crt

docker exec -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_ui_integration \
  --command "ALTER SYSTEM SET ssl = 'on'" \
  --command "ALTER SYSTEM SET ssl_cert_file = '/var/lib/postgresql/tls/server.crt'" \
  --command "ALTER SYSTEM SET ssl_key_file = '/var/lib/postgresql/tls/server.key'" \
  --command "ALTER SYSTEM SET ssl_min_protocol_version = 'TLSv1.2'"

docker kill --signal HUP "$container" >/dev/null
for _attempt in $(seq 1 30); do
  if docker exec -u postgres "$container" pg_isready --dbname brerc_ui_integration \
      >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec -u postgres "$container" pg_isready --dbname brerc_ui_integration >/dev/null

# These are deliberately separate ON_ERROR_STOP applications.  A role,
# migration or deployment-login error must stop provisioning before tests run.
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_ui_integration < "$roles_sql"
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_ui_integration < "$migration_0001_sql"
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_ui_integration < "$migration_0002_sql"
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_ui_integration < "$migration_0003_sql"
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_ui_integration < "$fixture_sql"

environment_id="$(
  docker exec -u postgres "$container" psql -v ON_ERROR_STOP=1 \
    --dbname brerc_ui_integration --tuples-only --no-align \
    --command "SELECT environment_id FROM loader_control.deployment_identity WHERE singleton"
)"
if [[ ! "$environment_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]; then
  echo "migration did not create one canonical destination environment UUID" >&2
  exit 1
fi

printf '%s\n' \
  'localhost:5432:brerc_ui_integration:brerc_release_loader_test:synthetic-loader-password' \
  'localhost:5432:brerc_ui_integration:brerc_api_test:synthetic-api-password' \
  'localhost:5432:brerc_ui_integration:brerc_martin_test:synthetic-martin-password' \
  'localhost:5432:brerc_ui_integration:brerc_monitor_test:synthetic-monitor-password' \
  > "$output_directory/destination.pgpass"
chmod 600 "$output_directory/destination.pgpass"

# Hostile sslmode/application_name values prove the loader's mandatory explicit
# parameters win.  The distinct login receives its rights only through
# membership in the reviewed NOLOGIN capability role.
printf '%s\n' \
  '[synthetic_loader]' \
  'host=localhost' \
  'port=5432' \
  'dbname=brerc_ui_integration' \
  'user=brerc_release_loader_test' \
  'sslmode=disable' \
  'application_name=service-file-value-must-not-win' \
  > "$output_directory/pg_service.conf"
chmod 600 "$output_directory/pg_service.conf"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    printf 'BRERC_LOADER_PG_INTEGRATION=1\n'
    printf 'BRERC_DESTINATION_HOST=localhost\n'
    printf 'BRERC_DESTINATION_PORT=5432\n'
    printf 'BRERC_DESTINATION_DATABASE=brerc_ui_integration\n'
    printf 'BRERC_TARGET_ENVIRONMENT_ID=%s\n' "$environment_id"
    printf 'BRERC_TARGET_SERVICE=synthetic_loader\n'
    printf 'BRERC_TARGET_PASSFILE=%s\n' "$output_directory/destination.pgpass"
    printf 'BRERC_TARGET_SSLROOTCERT=%s\n' "$output_directory/ca.crt"
    printf 'BRERC_PG_ADMIN_SECRET=%s\n' 'synthetic-admin-password'
    printf 'PGSERVICEFILE=%s\n' "$output_directory/pg_service.conf"
  } >> "$GITHUB_ENV"
fi

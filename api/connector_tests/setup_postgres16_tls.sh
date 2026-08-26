#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: setup_postgres16_tls.sh CONTAINER FIXTURE_SQL OUTPUT_DIRECTORY" >&2
  exit 2
fi

container="$1"
fixture_sql="$2"
output_directory="$3"

mkdir -p "$output_directory"
chmod 700 "$output_directory"

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -subj "/CN=BRERC synthetic connector test CA" \
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
  --dbname brerc_connector \
  --command "ALTER SYSTEM SET ssl = 'on'" \
  --command "ALTER SYSTEM SET ssl_cert_file = '/var/lib/postgresql/tls/server.crt'" \
  --command "ALTER SYSTEM SET ssl_key_file = '/var/lib/postgresql/tls/server.key'" \
  --command "ALTER SYSTEM SET ssl_min_protocol_version = 'TLSv1.2'"

docker kill --signal HUP "$container" >/dev/null
for _attempt in $(seq 1 30); do
  if docker exec -u postgres "$container" pg_isready --dbname brerc_connector >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec -u postgres "$container" pg_isready --dbname brerc_connector >/dev/null
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_connector < "$fixture_sql"

printf '%s\n' \
  'localhost:5432:brerc_connector:brerc_extract:synthetic-extract-password' \
  > "$output_directory/extract.pgpass"
printf '%s\n' \
  'localhost:5432:brerc_connector:brerc_column_reader:synthetic-column-password' \
  > "$output_directory/column.pgpass"
printf '%s\n' \
  'localhost:5432:brerc_connector:brerc_startup:synthetic-startup-password' \
  > "$output_directory/startup.pgpass"
chmod 600 \
  "$output_directory/extract.pgpass" \
  "$output_directory/column.pgpass" \
  "$output_directory/startup.pgpass"

# Deliberately hostile defaults. The connector's explicit verify-full and
# application_name parameters must override these service-file values.
printf '%s\n' \
  '[synthetic_brerc]' \
  'host=localhost' \
  'port=5432' \
  'dbname=brerc_connector' \
  'user=brerc_extract' \
  'sslmode=disable' \
  'application_name=service-file-value-must-not-win' \
  '' \
  '[synthetic_startup]' \
  'host=localhost' \
  'port=5432' \
  'dbname=brerc_connector' \
  'user=brerc_startup' \
  'options=-c role=brerc_extract' \
  'sslmode=disable' \
  > "$output_directory/pg_service.conf"
chmod 600 "$output_directory/pg_service.conf"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    printf 'BRERC_PG_INTEGRATION=1\n'
    printf 'BRERC_SOURCE_HOST=localhost\n'
    printf 'BRERC_SOURCE_PORT=5432\n'
    printf 'BRERC_SOURCE_DATABASE=brerc_connector\n'
    printf 'BRERC_SOURCE_USER=brerc_extract\n'
    printf 'BRERC_SOURCE_SERVICE=synthetic_brerc\n'
    printf 'BRERC_SOURCE_PASSFILE=%s\n' "$output_directory/extract.pgpass"
    printf 'BRERC_COLUMN_PASSFILE=%s\n' "$output_directory/column.pgpass"
    printf 'BRERC_STARTUP_PASSFILE=%s\n' "$output_directory/startup.pgpass"
    printf 'BRERC_PG_ADMIN_SECRET=%s\n' 'synthetic-admin-password'
    printf 'BRERC_SOURCE_SSLROOTCERT=%s\n' "$output_directory/ca.crt"
    printf 'PGSERVICEFILE=%s\n' "$output_directory/pg_service.conf"
  } >> "$GITHUB_ENV"
fi

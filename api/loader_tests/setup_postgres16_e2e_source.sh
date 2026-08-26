#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "usage: setup_postgres16_e2e_source.sh CONTAINER FIXTURE_SQL OUTPUT_DIRECTORY HOST_PORT" >&2
  exit 2
fi

container="$1"
fixture_sql="$2"
output_directory="$3"
host_port="$4"

if [[ ! "$host_port" =~ ^[0-9]+$ ]] || ((host_port < 1 || host_port > 65535)); then
  echo "HOST_PORT must be a decimal TCP port" >&2
  exit 2
fi

mkdir -p "$output_directory"
chmod 700 "$output_directory"

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -subj "/CN=BRERC synthetic loader source test CA" \
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
  --dbname brerc_loader_source_e2e \
  --command "ALTER SYSTEM SET ssl = 'on'" \
  --command "ALTER SYSTEM SET ssl_cert_file = '/var/lib/postgresql/tls/server.crt'" \
  --command "ALTER SYSTEM SET ssl_key_file = '/var/lib/postgresql/tls/server.key'" \
  --command "ALTER SYSTEM SET ssl_min_protocol_version = 'TLSv1.2'"

docker kill --signal HUP "$container" >/dev/null
for _attempt in $(seq 1 30); do
  if docker exec -u postgres "$container" pg_isready --dbname brerc_loader_source_e2e \
      >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec -u postgres "$container" pg_isready --dbname brerc_loader_source_e2e >/dev/null
docker exec -i -u postgres "$container" psql -v ON_ERROR_STOP=1 \
  --dbname brerc_loader_source_e2e < "$fixture_sql"

printf '%s\n' \
  "localhost:${host_port}:brerc_loader_source_e2e:brerc_extract:synthetic-e2e-extract-password" \
  > "$output_directory/source.pgpass"
chmod 600 "$output_directory/source.pgpass"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    printf 'BRERC_LOADER_E2E_SOURCE_HOST=localhost\n'
    printf 'BRERC_LOADER_E2E_SOURCE_PORT=%s\n' "$host_port"
    printf 'BRERC_LOADER_E2E_SOURCE_DATABASE=brerc_loader_source_e2e\n'
    printf 'BRERC_LOADER_E2E_SOURCE_USER=brerc_extract\n'
    printf 'BRERC_LOADER_E2E_SOURCE_PASSFILE=%s\n' "$output_directory/source.pgpass"
    printf 'BRERC_LOADER_E2E_SOURCE_SSLROOTCERT=%s\n' "$output_directory/ca.crt"
    printf 'BRERC_LOADER_E2E_SOURCE_ADMIN_SECRET=%s\n' 'synthetic-source-admin-password'
  } >> "$GITHUB_ENV"
fi

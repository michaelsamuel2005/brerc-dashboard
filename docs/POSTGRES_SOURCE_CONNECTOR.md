# Trusted PostgreSQL source connector

**Status:** Initial-load connector implemented and unit-tested with a synthetic DB-API
driver. CI now provisions an entirely synthetic PostgreSQL 16 service with certificate-verified
TLS and runs a real-driver integration gate; that new workflow must complete on GitHub before its
result is claimed as executed evidence. The connector has not been run against BRERC's network or
real records. Incremental loading, the public-database writer and public-release activation remain
blocked.

**Source:** `dashboard.main_data_dash`

**Code:** `api/brerc_source/postgres.py`

The connector closes a specific trust gap. The ETL can validate metadata, headers and rows,
but those values are trustworthy only if one component obtains all of them directly from
PostgreSQL in the same protected snapshot. Application callers therefore provide policy and
deployment settings; they cannot provide a view digest, catalogue metadata, cursor header or
source rows.

## Two deliberately different operations

`TrustedPostgreSQLSourceConnector.preflight(source_contract, columns)` is safe to run before the
source is approved for release. It opens the same locked, read-only snapshot, derives and validates
the live identity/schema, declares the exact projection only to validate its cursor description,
and performs **no row fetch**. It returns a frozen `SourcePreflightReport` containing only contract
and definition/identity digests, confirmed column/header counts and `release_ready`. Under the
current unapproved BRERC contract that final value must be `False`.

Preflight does not approve the view, does not transform a candidate, does not return raw SQL or
metadata, and cannot be passed to the release builder. Its purpose is to produce a safe readiness
diagnosis for BRERC and the project team while leaving the release gate closed.

`TrustedPostgreSQLSourceConnector.extract_initial(...)` is the data-bearing operation. It requires
the exact release-ready source contract and an approved publication policy before connecting,
then returns only `ValidatedSourceRun`. A preflight success is never a substitute for those
approvals.

## What one initial extraction does

The connector follows this order and fails closed if any step fails:

1. Validate the explicit `initial` load mode, approved publication policy, versioned source
   contract and exact safety mapping before opening a connection.
2. Resolve connection values from the named environment variables. Credentials are never
   accepted in repository configuration.
3. Start `REPEATABLE READ READ ONLY` and apply fixed session settings plus bounded statement,
   lock and idle-transaction timeouts.
4. Acquire `ACCESS SHARE` on the exact quoted view before the first `SELECT`. This is the weakest
   relation lock and does
   not block ordinary readers or writers to underlying tables. It does block concurrent
   replacement, alteration, ownership change or drop of the view until extraction finishes.
5. Read the settings back and verify the transaction is read-only and at the required isolation
   level.
6. Derive the live view definition, owner, options, PostgreSQL version and complete ordered
   catalogue-column evidence directly from that connection.
7. Compare that evidence with the BRERC-approved source identity and 39-column contract before
   executing the record query.
8. Open a named cursor over the fixed, explicitly quoted ten-column projection. It never uses
   `SELECT *` and never fetches precise coordinates, place, comments or raw source text.
9. Validate the cursor description even if the view contains zero rows, then read with bounded
   `fetchmany` calls.
10. Pass the captured evidence, validated header and complete rows directly to
    `run_pipeline_for_source`. The connector returns only its opaque `ValidatedSourceRun`.
11. Close cursors, roll back the source transaction and close the connection on success or
    failure. The source connector never commits.

`REPEATABLE READ` gives the record queries one data snapshot. The explicit relation lock closes
the separate DDL race: without it, a concurrent `CREATE OR REPLACE VIEW` or `ALTER VIEW` could
occur between identity inspection and preparation of the extraction query. The lock is acquired
before any `SELECT`, as PostgreSQL requires when a repeatable-read transaction needs its first
snapshot to follow the lock. See the official
[LOCK documentation](https://www.postgresql.org/docs/current/sql-lock.html).
`lock_timeout` makes contention a failed job instead of an indefinite wait. The standalone
approval-capture SQL uses the same lock discipline.

## Installation and configuration

Install the connector dependencies using one repository-pinned extra; do not install an arbitrary
current database driver into production:

```bash
# Production where system libpq is maintained by the operator
python -m pip install ".[connector-c]"

# Local development and CI only
python -m pip install ".[connector-binary]"
```

Both extras pin Psycopg and PyYAML. `connector-c` uses the system libpq; `connector-binary` bundles
libpq and is not the default production choice. CI exercises the common Psycopg API through the
binary build. The C build depends on the exact production host's compiler and maintained libpq, so
BRERC's operator must install `connector-c`, record the resulting Psycopg/libpq versions, run the
full connector suite and preflight on that controlled host before scheduling it; CI's binary result
is not evidence that the production C/libpq installation works. Copy `api/configuration.example.yaml` to a
controlled deployment location and keep the real file outside Git.

The versioned file contains environment-variable **names**, not their values. Supply exactly one
connection method:

- a protected libpq service name, recommended for BRERC; or
- explicit host, port, database and user environment variables.

The password, if password authentication is used, belongs in a protected libpq passfile, protected
service profile, or secret manager. A libpq service file can itself contain a password, so both it
and the explicitly configured passfile are part of the credential trust boundary and require the
same restricted ownership and storage. Credentials must not appear in YAML, a command argument,
shell history, email, logs or Git. The connector rejects `PGPASSWORD` both while loading
configuration and immediately before a connection, so an ambient process password cannot silently
override the reviewed files.
Require TCP with TLS certificate and hostname verification (`sslmode=verify-full`). The
implemented connector rejects a Unix socket, a non-TLS session and every weaker TLS mode. A
service-mode deployment must export the standard `PGSERVICEFILE` environment variable with the
absolute path to its protected service file. Psycopg/libpq reads that process variable directly;
`servicefile` is not a valid connection keyword and is deliberately never passed to the driver. A
`source_environment` value in configuration or an approval file is a comparison label, not proof
of the server: Shankar must independently confirm the approved service/endpoint and the deployment
must prevent operators from redirecting it to an unapproved clone.

At runtime the connector requires both PostgreSQL `session_user` (the authenticated login) and
`current_user` (the effective role) to equal the approved extraction role. This rejects a service
profile that logs in through a broader startup role and uses `options` to switch into the expected
role after authentication.

The connector's configuration parser is strict. Duplicate keys, unknown keys, YAML aliases and
YAML 1.1 shorthand/coercion forms are rejected; only lowercase JSON-style booleans/null and
canonical decimal integers are typed implicitly. The source object, ordered schema, projection and safety
mapping must equal the code-reviewed source contract; YAML cannot add a private column or disable
the `sensitive` control.

Repository ignore rules and the tracked-file guard block the standard connector configuration,
passfile, service-file and private-key naming conventions (including any `*.key`, `*.pgpass` or
`*.pg_service.conf`). They are defense in depth, not a general secret scanner: a credential renamed
to arbitrary plain text may evade filename checks. BRERC must still use its secret store, review
the staged diff, and run organisation-level secret scanning before merge.

## Dedicated, read-only PostgreSQL role

BRERC's database administrator should create or select a dedicated extraction role. The project
team must not request or store a superuser, owner or general reporting account. The following is
the minimum **relation-level** privilege set for this implementation:

```sql
ALTER ROLE brerc_dashboard_extract WITH
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

GRANT CONNECT ON DATABASE brerc_database TO brerc_dashboard_extract;
GRANT USAGE ON SCHEMA dashboard TO brerc_dashboard_extract;
GRANT SELECT ON TABLE dashboard.main_data_dash TO brerc_dashboard_extract;

ALTER ROLE brerc_dashboard_extract SET default_transaction_read_only = on;
ALTER ROLE brerc_dashboard_extract SET statement_timeout = '30s';
ALTER ROLE brerc_dashboard_extract SET lock_timeout = '5s';
ALTER ROLE brerc_dashboard_extract SET idle_in_transaction_session_timeout = '60s';
```

`brerc_database` and `brerc_dashboard_extract` are examples for BRERC to replace. `SELECT ON
TABLE` allows a holder who logs in outside this application to query every view column, including
precise coordinates and free text. It is required here because the connector locks the relation
and captures the complete 39-column schema before issuing its own ten-column projection; it is
read-only but not column-minimised. Keep the account on BRERC's internal network, store its
passfile and service file as protected secrets, prevent interactive/general reporting use, and
audit authentication and queries. Do not grant
table creation, schema creation, writes, role administration or blanket access to source tables.
BRERC's database administrator must also inspect privileges inherited from role membership and
grants to `PUBLIC`; the statements above do not revoke access inherited by another route.
If the approved view uses PostgreSQL's `security_invoker` option, BRERC must review the minimum
underlying read grants separately; do not solve that by granting broad database access. The view's
owner and options are part of the approved identity, so changing them requires review.

If BRERC requires a role that cannot read the other 29 private columns at all, it must provide a
BRERC-owned projection/capture interface designed for column grants. That changes the trust and
identity protocol and needs a new reviewed source contract; it cannot be achieved by weakening
the present full-schema check in deployment configuration.

## Operational preflight

Before any real-data run:

- BRERC runs the catalogue-only capture and a named authorised BRERC data owner approves the exact
  view identity using `VIEW_DEFINITION_APPROVAL.md`.
- Shankar verifies the approver and source environment through the agreed trusted channel.
- A reviewed source-contract revision binds that approval; the current contract deliberately has
  no live approval.
- The deployed secret is readable only by the service account, and the service/passfile has the
  permissions required by libpq (normally `0600` for a passfile).
- The extraction role's effective privileges are reviewed, including inherited and `PUBLIC`
  privileges.
- The connection is tested against a synthetic development view first. Never copy BRERC records
  into CI, developer fixtures, screenshots or issue reports.

Run the only operator command against the configured BRERC source before attempting extraction:

```bash
brerc-source preflight --config /a/brerc-controlled/location/configuration.yaml
```

It emits one fixed JSON object containing safe digests, the validated result-column names and
`releaseReady`; failures emit only a stable code and exit non-zero. Confirm that its digests equal
the evidence being reviewed and retain only this safe report in ordinary job logs.
`releaseReady:false` is the expected current result; there is no override. Once BRERC's approval is
bound into a reviewed contract, repeat preflight and require `releaseReady:true` before scheduling
the separately controlled data-bearing extraction.

## Safe operation and failure handling

An extraction failure must make the job state `failed`, leave the current public release active
and produce a non-sensitive diagnostic. Logs may contain:

- run identifier and UTC times;
- connector, contract and policy versions;
- safe row counts and predetermined sensitivity buckets;
- definition, identity and candidate digests;
- failure stage and a stable application error code.

Logs must not contain raw rows, original `unique_no`, grid references, place, comments, unexpected
source values, view SQL, credentials, DSNs or full driver exception representations. Report an
unexpected sensitivity value under the fixed `other` bucket rather than logging the value. Retain
the detailed raw capture only in BRERC's controlled evidence location.

The connector does not retry policy, identity, schema, header or data-validation failures. A
deployment may retry a clearly transient connection/timeout failure as a new run, with bounded
attempts and no public-state change. It must never provide a force or skip-validation flag.

## Test strategy

The fast connector suite uses a scripted fake connection and no BRERC records. It
asserts transaction and SQL ordering for both preflight and extraction, lock-before-first-SELECT,
one-connection provenance, strict cursor headers, zero fetches during preflight, bounded extraction
batches, rollback/close behaviour, absence of commit, fail-before-fetch behaviour and safe
exceptions. It also passes both service and direct keyword sets through the pinned real Psycopg
conninfo parser, which catches unsupported driver options.

The separate `postgres-integration` CI job provisions PostgreSQL 16 with a one-run synthetic CA
and hostname-verified server certificate, then creates the exact 39-column view using fabricated
rows only. It exercises both strict YAML connection modes, the public connector API, a hostile
service-file default overridden by mandatory connection settings, real JSONB catalogue values,
cursor descriptions, the named extraction cursor, an approved synthetic extract, rollback,
read-only role attributes, a stable repeatable-read snapshot and concurrent view DDL waiting
behind `ACCESS SHARE`. It also asserts that a ten-column-only grant cannot satisfy the
full-schema/lock trust protocol while denying direct access to `easting`; the first observed green
run will turn that expectation into empirical evidence. This is why the deployed account is
described above as relation-level read-only rather than column-minimised.
Run it with the normal API gates:

```bash
cd api
python -m pip install ".[connector-binary,dev]"
python -m unittest discover -s connector_tests -t . -p 'test_*.py'
python scripts/guard_stdlib_only.py --etl-dir etl
python -m ruff check .
python -m ruff format --check .
```

API CI has connector tests on Python 3.10 and 3.13 plus the independent PostgreSQL 16 TLS job; the
bare Python matrix continues to run the dependency-free ETL suite. Until the new integration job
has run green in GitHub Actions, treat it as implemented but not yet observed. It never requires
access to BRERC.

## Honest completion boundary

This work completes the trusted **initial-source connector** and its unit-testable trust boundary.
It does not make the dashboard publicly releasable and it does not complete a five-million-row
production load. The current ETL ultimately materialises the extracted rows in memory; bounded
database fetches prevent driver-level `fetchall`, but do not remove that whole-run memory cost.
Chunked transformation/external staging and a representative performance test remain required
before operating at BRERC's estimated scale.

The following also remain separate blockers:

- BRERC's live-view capture, named approval and independently confirmed environment;
- catastrophic empty-result and count-drop activation thresholds;
- public PostgreSQL/PostGIS writer, reconciliation and atomic release switching;
- `date_mdb_modified`, stable-key and deletion guarantees for incremental loading;
- publication-policy decisions and any other blockers recorded in the source contract.

Until those are complete, the correct status is **connector implemented; public release held**.

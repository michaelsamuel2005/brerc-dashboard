# PostgreSQL/PostGIS release loader

## Status and scope

The release loader builds an **inactive, publication-safe candidate** in the UI
PostgreSQL/PostGIS database and activates it only after automatic reconciliation.
It is separate from the trusted source connector:

```text
BRERC view (private)
  -> trusted read-only source connector
  -> bounded safe/generalised dispositions
  -> inactive destination candidate
  -> whole-candidate suppression, aggregation and validation
  -> one atomic active-release switch
  -> serve.* views
```

The implemented command surface is:

```sh
brerc-load initial --config /controlled/path/loader.configuration.yaml
brerc-load incremental --config /controlled/path/loader.configuration.yaml
```

`incremental` is intentionally blocked before configuration parsing or either
database connection. The approved 39-column BRERC source contract does not yet
contain the evidence required for a correct incremental load. This is a safety
control, not an unfinished command-line check.

An initial load is allowed only when the destination has no active release. It
is not a full-refresh mechanism for replacing an existing release. A future
replacement or incremental protocol must preserve the reviewed base-release,
deletion and watermark semantics.

## Why loading is release-based

The public application must never see a half-written update. Every candidate
therefore receives its own `release_id`. Inserts, suppression and aggregates are
created under that inactive ID while the `serve.*` views continue to read the old
active release. The database-owned activation function validates the candidate
and changes the active pointer, watermark and job state in one transaction.

If extraction, transformation, staging, aggregation or validation fails, the
active pointer does not change. If a worker process disappears, the next worker
must first recover the orphaned inactive job while holding the same per-source
advisory lock. Recovery commits a fixed `WORKER_LOST` state, notification outbox
event and `cleanup_pending` flag before attempting the potentially large purge.
No new candidate may begin while cleanup remains pending. Immediate ACK recovery
and best-effort terminal cleanup use a separate five-second control window; they
do not inherit the remainder of a potentially hours-long workload deadline.
If the activation response is lost after commit, the coordinator
reconciles the known job/release identifiers and treats an already-committed
matching activation as success; it must not try to fail an active release.

## Privacy boundary

Raw BRERC rows do not cross into the destination writer. The trusted source
connector transforms each row while the locked, repeatable-read source snapshot
is open. The writer receives only:

- a private 32-byte HMAC source token;
- a private HMAC fingerprint;
- a fixed withholding reason; or
- an allow-listed, already-generalised public record plus safe cell bounds.

The destination must never contain the original `unique_no`, source easting or
northing, precise source grid reference, comments, recorder information, the
raw sensitivity flag, raw place/source text, database credentials or raw adapter
errors. Reconciliation and public record identifiers use different secrets.

The row transform is bounded by the configured batch size. Cell suppression and
aggregation are deliberately **not** performed per batch: they run only after the
complete safe candidate has been staged, so changing batch size or input order
cannot change whether a cohort is published.

## Destination schemas

The versioned migration is in `db/migrations/0001_publication_store.sql`.
This implementation is pinned to PostgreSQL major version 16 and PostGIS 3.5;
the target preflight reads both server-side and fails before loading if either
version family differs. Migration 0001 also generates a single destination
environment UUID in `loader_control.deployment_identity`. Operations must copy
that UUID into the protected loader configuration through a trusted channel;
the loader compares it, the database name and the execution role before it
acquires the source lock. It also requires an unprivileged LOGIN identity that
inherits exactly the `brerc_loader` group directly and no other group role.

| Schema | Purpose |
|---|---|
| `loader_control` | Job/release state, manifests, safe audit counts, outbox and immutable release-scoped dispositions. |
| `loader_stage` | Inactive job-scoped inventory, deltas and reconciliation evidence. |
| `publication` | Release-scoped public-safe species, cells, year totals and optional records. |
| `serve` | Active-release-only, capability-masked views for FastAPI, Martin and monitoring. |

Apply roles and migration as a database administrator with `ON_ERROR_STOP`:

```sh
psql -X -v ON_ERROR_STOP=1 -f db/roles.sql "$CONTROLLED_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 \
  -f db/migrations/0001_publication_store.sql "$CONTROLLED_ADMIN_DSN"
```

The variable is illustrative. Do not place a DSN or password in source control,
shell history or scheduler logs. Production should use a protected libpq service
file, passfile and CA certificate or an equivalent secret-managed deployment.
After a backup is restored as a different logical environment, an administrator
must assign the clone a new environment UUID before enabling loader credentials.
Copying the production UUID into a clone defeats this wrong-target safeguard.

## Database authority

The destination migration/owner account is a trusted deployment boundary. The
version row and environment UUID catch wrong targets and accidental drift; they
cannot attest against an administrator who can alter tables, functions or ACLs.
Operations must apply the exact reviewed migration in a dedicated database and
retain the green real-database privilege/function integration evidence.

The loader role can insert candidates but cannot directly update release status,
the active pointer or successful watermark. It invokes narrowly reviewed
`SECURITY DEFINER` functions:

- `loader_control.recover_orphaned_job(text)`;
- `loader_control.activate_validated_release(uuid)`;
- `loader_control.fail_candidate(uuid, text)`; and
- `loader_control.discard_inactive_candidate(uuid)`.

Finalisation authorises exactly one candidate release in its database
transaction. A `BEFORE INSERT ... FOR EACH STATEMENT` guard on every durable
release-scoped publication/audit table rechecks `release.status = 'candidate'`,
`job.status = 'reconciling'` and the source advisory lock once per insert. Row
level security then requires every inserted row's `release_id` to equal that
transaction-local authorisation. This avoids both per-row catalogue queries and
a multi-million-row transition table, while preventing insert privilege from
appending to an active release after validation.

Activation independently checks source-token parity, complete safe disposition
fields, policy capabilities, the approved suppression rule, every map/year/species
aggregate, optional public rows, geometry and count equations. Application SHA-256
digests are retained integrity evidence; they are not a substitute for these
database-owned comparisons and do not authenticate BRERC approval.

The loader can read but cannot update the notification outbox. A separate future
notifier role/worker must deliver email and update delivery state. The presence of
an outbox row does not mean an email service or ETL dashboard is already built.

## Configuration and secrets

Copy `api/loader.configuration.example.yaml` to a controlled location outside the
repository. The tracked template is deliberately not runnable. It references:

- the reviewed source-connector configuration;
- exact bytes and SHA-256 of an approved publication-policy artifact;
- an independent public-record HMAC secret;
- initial source-count activation bounds;
- the expected target database, role and independently recorded environment UUID;
- a TLS `verify-full` target service/direct connection; and
- an independent reconciliation HMAC secret.

Configuration parsing rejects duplicate/unknown keys, unsafe YAML coercions,
inline passwords/DSNs, ambient `PGPASSWORD`, non-TLS target settings, arbitrary
source queries and bypass switches. Resolved credentials and secrets are redacted
from representations and operator errors.

The environment UUID is a deployment assertion, not proof of BRERC approval and
not a replacement for hostname-verified TLS, protected service configuration or
operational verification of the destination endpoint.

The overall deadline is enforced between phases and batches, while remaining
time is pushed into PostgreSQL statement and lock timeouts and the source
connector's cancellation path. It is a cooperative/server-bounded control, not
an operating-system hard kill for a broken network stack; the scheduler should
retain its own outer job timeout.

The target connection must remain pinned to one PostgreSQL backend session for
the complete run because the per-source advisory lock survives committed batch
transactions on that session. Direct PostgreSQL connections and explicitly
session-pooled proxies are compatible. PgBouncer transaction or statement
pooling is not compatible and must not sit on this loader connection path.

## Automatic failure behaviour

The CLI returns one fixed JSON object. A success includes only opaque job/release
IDs, structural counts and a digest. A failure contains a stable code and no SQL,
row, hostname, credential or raw exception text. Examples:

```json
{"activated":true,"candidateSha256":"<sha256>","distributionCells":123,"mode":"initial","publicRecords":0,"releaseId":"<uuid>","runId":"<uuid>","sourceRows":5000000,"state":"succeeded","status":"ok"}
```

```json
{"code":"LOADER_CANDIDATE_INVALID","status":"failed"}
```

No manual review or `--force` option can turn a failed candidate into an active
release. The previous active release remains visible. Operators investigate the
fixed failure code and safe job/manifest/event counts; record samples must never
be added to logs.

Failure state is authoritative once `fail_candidate` has committed the fixed
code and outbox event. Large inactive payload deletion is a separate, durable
`cleanup_pending` obligation. The loader tries it immediately, but a timeout or
process crash does not rewrite the original outcome as `LOADER_CLEANUP_FAILED`.
The internal release-status view exposes the pending flag, and the next lock
owner retries cleanup before any new work. If it still cannot purge safely, the
new run stops with `LOADER_CLEANUP_PENDING`; public serving remains on the prior
active release throughout.

## Tests and release evidence

Run the local unit/static gates from `api/`:

```sh
python -m unittest discover \
  --start-directory loader_tests --top-level-directory . --pattern 'test_*.py'
python -m ruff check .
python -m ruff format --check .
```

CI also executes the migration and lifecycle against a fully synthetic pinned
PostgreSQL 16 + PostGIS service. That integration must be green before merge. It
contains no BRERC data and does not replace a live BRERC-network preflight or a
realistic, BRERC-approved scale/runtime test.

The separate manual five-million-row gate and its evidence rules are documented
in `docs/POSTGRES_LOADER_SCALE_ACCEPTANCE.md`. The harness being present is not a
passing result; retain and review a green evidence artifact before closing the
scale blocker.

## External decisions still required

Production activation remains blocked until the retained external evidence is
real and Shankar verifies the named BRERC authority through the agreed channel:

- approved live view identity and environment/role evidence;
- an approved publication policy for precision, licensing, suppression,
  record types and row-level output;
- approved initial count/drop thresholds;
- BRERC scheduling and operational limits for the approximately five-million-row
  source snapshot; and
- the missing incremental contract below.

The confirmed source view includes `taxa_nb`, but the current safe projection and
disposition do not yet carry an approved taxon-group mapping. Consequently the
destination `taxon_group` remains unavailable and the frontend group filter must
not be described as live-data-complete. Record verification is likewise
unavailable in the confirmed 39-column source view.

## What BRERC must approve before incremental loading

The next source-contract version must define all of the following:

1. `date_mdb_modified`: exact type, nullability, timezone/date semantics and
   whether every publication-affecting change updates it.
2. `unique_no`: non-null, globally unique, permanent and never reused, including
   canonical treatment of numeric values such as `1` and `1.00`.
3. Deletions/withdrawals: an authoritative tombstone feed, or approval for a
   complete same-snapshot source-key inventory anti-join.
4. Lookup changes: how sensitivity, licensing, taxonomy or record-type changes
   invalidate affected records if their own modified date does not change.
5. Count-drop/growth thresholds and the action required when they are crossed.

If the marker remains a PostgreSQL `date`, every run must re-read the entire last
successful date with `date_mdb_modified >= watermark_date`; a strict composite
`(date, id) > previous` cursor can miss a late same-day update whose ID sorts
lower. A row-count difference is monitoring only—it cannot identify deletions and
can miss an equal-count delete-plus-insert.

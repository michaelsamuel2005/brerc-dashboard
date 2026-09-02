# PostgreSQL/PostGIS release loader

## Status and scope

The release loader builds an **inactive, publication-safe candidate** in the UI
PostgreSQL/PostGIS database and activates it only after automatic reconciliation.
It is separate from the trusted source connector:

```text
BRERC view (private)
  -> trusted read-only source connector
  -> bounded policy dispositions (safe-v1 sensitive rows withheld)
  -> inactive destination candidate
  -> whole-candidate suppression, aggregation and validation
  -> one atomic active-release switch
  -> serve.* views
```

The implemented command surface is:

```sh
brerc-load initial --config /controlled/path/loader.configuration.yaml
brerc-load refresh --config /controlled/path/loader.configuration.yaml
brerc-load incremental --config /controlled/path/loader.configuration.yaml
```

The three names have deliberately different meanings:

| Mode | When it is allowed | What it reads and publishes |
|---|---|---|
| `initial` | Only when the destination has no active release. | One complete, locked source snapshot becomes the first active release. |
| `refresh` | Only when the same source already has an active release. | One newer, complete, locked source snapshot becomes a fresh candidate and, after validation, replaces the previous release atomically. |
| `incremental` | Not currently allowed. | It exits before configuration parsing and before either database is contacted. |

`refresh` is a full replacement, not a renamed incremental load. It deliberately
uses the approved complete-snapshot source protocol and carries no modification
watermark. Every source row in that snapshot receives one inventory,
disposition and non-delete delta entry. A record removed from the source is
therefore absent from the complete candidate and disappears when that candidate
is activated; the loader does not need a tombstone or infer a per-row delete.
Lookup changes are likewise reflected because the complete reviewed view is
read again.

`incremental` remains intentionally blocked because the approved 39-column
BRERC source contract does not yet contain the evidence required for a correct
change-window load. This is a safety control, not an unfinished command-line
check. The implemented full-snapshot refresh is the supported scheduled-update
mechanism until a later incremental contract is approved and implemented.

## Why loading is release-based

The public application must never see a half-written update. Every candidate
therefore receives its own `release_id`. Inserts, suppression and aggregates are
created under that inactive ID while the `serve.*` views continue to read the old
active release. The database-owned dispatcher validates the candidate and
changes the active pointer, source-snapshot evidence and job state in one
transaction. Refreshes leave the incremental watermark fields null.

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

A refresh is bound to the active release that existed when the candidate began.
Activation rejects a stale base or a source-snapshot timestamp that does not
strictly advance the last accepted evidence. If the fully validated candidate is
exactly identical to the active payload, the database keeps the current active
release, records the refresh job as succeeded with `reused_active_release=true`,
advances the source-snapshot evidence, and discards the duplicate candidate with
durable cleanup debt. The coordinator immediately attempts its purge; if that
best-effort cleanup cannot finish, the successful result remains authoritative
and the next source-lock owner must clear the debt before new work. The public
`releaseId` remains unchanged in this no-change case.

## API release consistency

FastAPI never reads a candidate or a publication table directly. Its dedicated
`brerc_api` role can read only the active `serve.*` views. Every request uses a
transaction-read-only, `REPEATABLE READ` connection, and the live session is
checked for that isolation plus absence of loader, Martin, monitor or broad write
roles before a router query runs. If activation commits between two SQL
statements in one request, both statements still see the same release snapshot.

Every public data response returns the active release's UUID as `releaseId` and
the non-blank publication `datasetVersion`; the database-independent health
response is the only exception. The frontend contract rejects a data response
without either field. It pins the first pair observed across the whole page and
rejects a mismatch before it can enter the query cache. During recovery it hides
the page, cancels and clears old query fragments, fetches fresh provenance as
the authority, then remounts and refetches. This is not polling: a browser that
makes no further request remains consistently on its cached release until its
next fetch or reload.

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

Safe v1 withholds a row classified as sensitive by any of four axes—the retained
taxon snapshot, digest-bound dictionary, source row flag or approved record-type
rule—before public geometry or public-id generation. Otherwise eligible ordinary
rows are reduced to at least 1 km and a coarser source is never sharpened. Safe v1
is aggregate-only and binds `k=1`, so no additional minimum-count suppression is
applied after the safety gate.

The row transform is bounded by the configured batch size. Cell suppression and
aggregation are deliberately **not** performed per batch: they run only after the
complete safe candidate has been staged, so changing batch size or input order
cannot change whether a cohort is published.

## Destination schemas

The destination schema consists of ordered migrations
`db/migrations/0001_publication_store.sql`,
`db/migrations/0002_sensitive_record_action.sql` and
`db/migrations/0003_full_snapshot_refresh.sql`.
This implementation is pinned to PostgreSQL major version 16 and PostGIS 3.5;
the target preflight reads both server-side and fails before loading if either
version family differs or the migration history is not exactly the expected
ordered sequence of three. Migration 0001 also generates a single destination
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
psql -X -v ON_ERROR_STOP=1 \
  -f db/migrations/0002_sensitive_record_action.sql "$CONTROLLED_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 \
  -f db/migrations/0003_full_snapshot_refresh.sql "$CONTROLLED_ADMIN_DSN"
```

The variable is illustrative. Do not place a DSN or password in source control,
shell history or scheduler logs. Production should use a protected libpq service
file, passfile and CA certificate or an equivalent secret-managed deployment.
After a backup is restored as a different logical environment, an administrator
must assign the clone a new environment UUID before enabling loader credentials.
Copying the production UUID into a clone defeats this wrong-target safeguard.

Migration 0002 adds the approval-bound `sensitive_record_action` to both
`loader_control.release_manifest` and `publication.public_release`, exposes it
through `serve.public_release`, and installs a deferred symmetric constraint
that refuses a committed mismatch. Existing pre-v2 development rows are
truthfully backfilled as `generalise`, the only action artifact v1 supported;
this backfill is historical labelling, not evidence of safe-v1 activation.

Migration 0003 adds the explicit `refresh` lifecycle, immutable refresh
threshold evidence and the database-owned
`loader_control.activate_release_candidate(uuid)` dispatcher. The migration
refuses reapplication and refuses to run while non-terminal ETL jobs exist. It
must be reviewed and applied during a controlled deployment window; it is not a
routine command for every scheduled refresh.

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
- `loader_control.activate_release_candidate(uuid)`;
- `loader_control.fail_candidate(uuid, text)`; and
- `loader_control.discard_inactive_candidate(uuid)`.

The earlier `loader_control.activate_validated_release(uuid)` function remains
an internal implementation used by the dispatcher, but migration 0003 revokes
its execution from both `PUBLIC` and `brerc_loader`. Operators and loader code
must not call it directly: doing so would bypass refresh-specific base,
freshness, completeness and comparative-threshold checks.

Finalisation authorises exactly one candidate release in its database
transaction. A `BEFORE INSERT ... FOR EACH STATEMENT` guard on every durable
release-scoped publication/audit table rechecks `release.status = 'candidate'`,
`job.status = 'reconciling'` and the source advisory lock once per insert. Row
level security then requires every inserted row's `release_id` to equal that
transaction-local authorisation. This avoids both per-row catalogue queries and
a multi-million-row transition table, while preventing insert privilege from
appending to an active release after validation.

Activation independently checks source-token parity, complete safe disposition
fields, policy capabilities, the approval-bound sensitive-record action, the
approved suppression rule (`k=1`/none for safe v1), every map/year/species
aggregate, optional public rows, geometry and count equations. Application SHA-256
digests are retained integrity evidence; they are not a substitute for these
database-owned comparisons and do not authenticate BRERC approval.

The loader can read but cannot update the notification outbox. A separate
least-privilege notifier role/worker must deliver messages and update delivery
state. The presence of an outbox row does not mean a message has been delivered.
Operational consumers must read the fixed, redacted
`serve.etl_job_status`, `serve.etl_release_status` and
`serve.etl_notification_status` views as `brerc_monitor`. The current
`run-dashboard/` application reads `serve.etl_job_status` through an exact,
read-only `brerc_monitor` login and refuses broader or wrong-target sessions.
The retained SQLite writer under `api/etl/run_history.py` is a legacy-only
component and is not part of this production contract. Delivery from the
notification outbox remains a separately reviewed worker responsibility.

## Configuration and secrets

Copy `api/loader.configuration.example.yaml` to a controlled location outside the
repository. The tracked template is deliberately not runnable. It references:

- the reviewed source-connector configuration;
- exact bytes and SHA-256 of an approved strict
  `brerc-publication-policy/v2` artifact;
- exact bytes and raw SHA-256 of the controlled species-dictionary CSV, whose
  normalised semantic digest must also match the approved policy;
- an independent public-record HMAC secret;
- initial source-count activation bounds and all required refresh thresholds;
- the expected target database, role and independently recorded environment UUID;
- a TLS `verify-full` target service/direct connection; and
- an independent reconciliation HMAC secret.

Configuration parsing rejects duplicate/unknown keys, unsafe YAML coercions,
inline passwords/DSNs, ambient `PGPASSWORD`, non-TLS target settings, arbitrary
source queries and bypass switches. Resolved credentials and secrets are redacted
from representations and operator errors.

The tracked template is configuration version `brerc-loader-v3`. A v3 runtime
must bind all eight refresh values; there are no unattended defaults:

| Setting | Meaning | Accepted range |
|---|---|---:|
| `refresh_min_source_rows` | Absolute minimum rows in the new complete snapshot. | 1–1,000,000,000 |
| `refresh_max_source_rows` | Absolute maximum rows in the new complete snapshot. | minimum–1,000,000,000 |
| `refresh_max_source_row_drop_bps` | Maximum source-row decrease from the active base. | 0–10,000 bps |
| `refresh_max_source_row_growth_bps` | Maximum source-row increase from the active base. | 0–1,000,000,000 bps |
| `refresh_max_publication_basis_drop_bps` | Maximum decrease in otherwise publishable rows. | 0–10,000 bps |
| `refresh_max_species_drop_bps` | Maximum published-species decrease. | 0–10,000 bps |
| `refresh_max_cell_drop_bps` | Maximum published-cell decrease. | 0–10,000 bps |
| `refresh_max_species_year_drop_bps` | Maximum species/year aggregate decrease. | 0–10,000 bps |

One basis point is 0.01% (`100` is 1%; `10,000` is 100%). These values are
persisted in the immutable candidate manifest and rechecked with exact integer
inequalities in PostgreSQL. They must be approved from BRERC's production data
and operating expectations; copying the deliberately permissive synthetic-test
values into production would defeat the gate.

Artifact v2 binds `sensitiveRecordAction` and the approval-authority basis into
the digest. A direct approval identifies the BRERC approver. A delegated approval
must instead identify the actual approver and organisation as well as the BRERC
delegator, delegator role, scope, date and retained delegation evidence. Version 1
is rejected rather than silently inheriting those new decisions. The digest detects
changed bytes and stale decision sets; it does not authenticate a person or evidence
reference without the separate trusted-channel verification.

The environment UUID is a deployment assertion, not proof of BRERC approval and
not a replacement for hostname-verified TLS, protected service configuration or
operational verification of the destination endpoint.

The overall deadline is enforced between phases and batches, while remaining
time is pushed into PostgreSQL statement and lock timeouts and the source
connector's cancellation path. It is a cooperative/server-bounded control, not
an operating-system hard kill for a broken network stack; the scheduler should
retain its own outer job timeout. The reviewed but deliberately inert systemd
templates, approval boundary and production preflight are in
[`../deploy/refresh/README.md`](../deploy/refresh/README.md); their example
cadence, timeout and catch-up behavior are not production decisions.

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
{"activated":true,"candidateSha256":"<sha256>","distributionCells":123,"mode":"initial","publicRecords":0,"releaseId":"<uuid>","reusedActiveRelease":false,"runId":"<uuid>","sourceRows":5000000,"state":"succeeded","status":"ok"}
```

```json
{"activated":true,"candidateSha256":"<sha256>","distributionCells":124,"mode":"refresh","publicRecords":0,"releaseId":"<uuid>","reusedActiveRelease":false,"runId":"<uuid>","sourceRows":5000010,"state":"succeeded","status":"ok"}
```

For a no-change refresh, `releaseId` is the reused active release ID even though
the refresh candidate had a different internal ID and `reusedActiveRelease` is
`true`. `activated:true` means the loader successfully established the
authoritative active result; it does not promise that the public release ID
changed.

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
performs an initial load, modifies and removes rows in the synthetic source,
runs a complete refresh, and then exercises FastAPI and the mocks-disabled
browser against the refreshed active release. The focused procedure and its
expected evidence are in
[`FULL_SNAPSHOT_REFRESH.md`](FULL_SNAPSHOT_REFRESH.md). It contains no BRERC data
and does not replace a live BRERC-network preflight or a realistic,
BRERC-approved scale/runtime test.

The separate manual five-million-row gate and its evidence rules are documented
in `docs/POSTGRES_LOADER_SCALE_ACCEPTANCE.md`. Existing evidence covers an
initial publication only. A changed full-snapshot refresh must also be run from
the exact protected-`main` merge SHA, with a retained and reviewed green
artifact, before the refresh path is accepted at BRERC scale. A workflow or
harness merely being present is not a passing result.

## Production evidence and inputs still required

The safe-v1 mechanism and decision envelope are implemented, but no production
activation is claimed. Activation remains blocked until the retained external
evidence is real and the named authority is verified through the agreed channel:

- approved live view identity and environment/role evidence;
- exact version-2 policy bytes and SHA-256 recording sensitive
  `withhold`, ordinary 1 km, aggregates-only and `k=1`, plus the remaining
  licensing/content decisions;
- direct authority evidence or the complete actual-approver + BRERC-delegator
  chain and delegation evidence;
- digest-bound species dictionary and corrected approved record-type vocabulary;
- controlled real sensitive-row examples and the real BRERC candidate acceptance
  report proving each sensitivity axis was withheld;
- approved initial bounds and all eight production refresh thresholds;
- BRERC scheduling and operational limits for the approximately five-million-row
  source snapshot;
- production PostgreSQL/PostGIS provisioning, verify-full TLS identity, secrets,
  service ownership and retained deployment evidence; and
- a reviewed schedule and outer job timeout for complete-snapshot refreshes.

The missing incremental contract below is **not** a blocker to scheduled
updates now that full-snapshot refresh exists. It is required only before the
separate `incremental` command can be enabled.

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

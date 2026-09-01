# BRERC destination PostgreSQL/PostGIS store

**Status:** destination schema implemented for synthetic integration and review. It is not a
production release approval, a live BRERC connection, or an incremental-source contract.

This directory defines the database that will hold publication-safe BRERC releases. It contains
schema only: no client rows, credentials, hostnames, email addresses or private keys.

## Files

| File | Purpose |
|---|---|
| `roles.sql` | Creates or verifies four non-login, least-privilege group roles. |
| `migrations/0001_publication_store.sql` | Installs the versioned schemas, tables, constraints, indexes, PostGIS geometry and serving views. |
| `migrations/0002_sensitive_record_action.sql` | Adds approval-bound sensitive-record action evidence to manifests, releases and the serving view. |

Apply each file with a migration/administrator account and `ON_ERROR_STOP`:

```sh
psql -X -v ON_ERROR_STOP=1 -f db/roles.sql "$BRERC_DESTINATION_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 -f db/migrations/0001_publication_store.sql \
  "$BRERC_DESTINATION_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 -f db/migrations/0002_sensitive_record_action.sql \
  "$BRERC_DESTINATION_ADMIN_DSN"
```

The variable above is illustrative. Do not put a DSN, password or real service file in this
repository. Production should use a protected service/pass file or the platform's secret store.

Migration `0001` is one transaction and takes a transaction-scoped advisory lock. It bootstraps
`loader_control.schema_migration`, checks that version 1 has not already been applied, and records
the version only as its final statement. Re-running an installed migration raises an error. It
does not use `CREATE TABLE IF NOT EXISTS` to make an unknown installation resemble the reviewed
one. A partial failure rolls back the entire migration.

Migration `0002` is also transactional and must follow exactly `0001`. It records whether the
approved action generalises or withholds sensitive records in both the immutable manifest and
public-release capabilities. Its deferred database check refuses a committed mismatch. Retained v1
development releases are labelled `generalise`, the only action supported by policy artifact v1.

The migration expects PostgreSQL 16 and PostGIS 3.5 installed in `public`; the concrete loader
preflight verifies both version families before it acquires the source lock. A real PostgreSQL/PostGIS
integration run is still required before merge; the Python test is intentionally a static contract
test and is not a substitute for executing the SQL.

Migration 0001 creates exactly one `loader_control.deployment_identity` row with a generated UUID.
Record that UUID through a trusted operational channel and pin it in the protected loader
configuration. The loader verifies the UUID, database and role before taking a source lock. A clone
or restored copy used as a different logical environment must be assigned a new controlled UUID
before loader credentials are enabled. This is a wrong-target guard, not approval evidence or a
replacement for hostname-verified TLS.

Target preflight also verifies that the live login is not superuser, database/role creator,
replication or row-security bypass authority, that it inherits privileges, and that its only direct
group membership is `brerc_loader`. Direct object grants are still a deployment-review concern;
create a dedicated login and do not reuse an administrator or reporting account.

## Security boundary

The migration/owner account is trusted. An administrator able to alter these
tables, SECURITY DEFINER functions or ACLs could also rewrite any in-database
checksum or UUID. The migration history and deployment identity are wrong-target
and drift guards, not hostile-DBA attestation; production must apply the exact
reviewed SQL in a dedicated database and retain real privilege-test evidence.

The destination database must receive only generalised, allow-listed values emitted by the trusted
connector and ETL safety boundary. It must never receive:

- source eastings or northings;
- comments, unapproved/raw place or source text, or recorder information;
- the source sensitivity flag;
- the original `unique_no`;
- database credentials or lower-level exception messages.

Deletion/reconciliation state uses a full 32-byte, domain-separated HMAC token derived from the
canonical source key. The key itself is never stored here. HMAC keys live in a secret manager and
must be different from the key used to form any public record identifier.

The four schemas are deliberately separate:

| Schema | Contents | Who can access it |
|---|---|---|
| `loader_control` | Jobs, releases, watermarks, manifests, safe audit counts, notification outbox and immutable release-scoped pseudonymous dispositions. | Loader only; monitoring uses restricted views. |
| `loader_stage` | Job-scoped inventory, deltas and reconciliation results. | Loader only. |
| `publication` | Release-scoped, public-safe species, cells, years and optional occurrence rows. | Loader only; serving roles use views. |
| `serve` | Active-release public views and fixed-field ETL status views. | FastAPI, Martin or monitor as explicitly granted. |

`PUBLIC` receives no privilege on any of these schemas, tables or sequences. Future objects also
default to no `PUBLIC` table/sequence access. A later migration must grant each new serving object
explicitly.

## Group roles

All repository-defined roles are `NOLOGIN`, `NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`,
`NOREPLICATION` and `NOBYPASSRLS`:

- `brerc_loader`: inserts immutable candidates and invokes guarded lifecycle functions; it cannot
  update a release status or active pointer directly;
- `brerc_api`: reads active-release API views only;
- `brerc_martin`: reads only active release metadata and map cells;
- `brerc_monitor`: reads redacted ETL job/release/notification status views.

Deployment creates separate login/service identities and grants membership in exactly one suitable
group role. The migration does not create users or passwords. If `roles.sql` finds an existing
group name with a privileged/login attribute or an inherited parent role, it fails instead of
altering it silently.

## Atomic release visibility

Every public-safe data row carries a `release_id`. Candidate data is written under a new ID while
the serving views continue to join the previous `loader_control.source_state.active_release_id`.
The worker first holds the same per-source **session** advisory lock used by the target connector.
After a crashed worker, `loader_control.recover_orphaned_job(text)` verifies that this session owns
that lock, marks the one committed open job `WORKER_LOST`, queues its failure notification and
records a durable `cleanup_pending` obligation. The same lock owner then invokes the checked
janitor; a new job cannot begin until every pending inactive payload for the source is gone. This
keeps the terminal failure/outbox transition quick even when the candidate contains millions of
rows. No wall-clock timeout guesses that a live worker died.

The loader then invokes `loader_control.activate_validated_release(uuid)`, which performs one atomic
target-database validation-and-activation transaction:

1. take the per-source advisory lock and lock `source_state` `FOR UPDATE`;
2. confirm the expected base release is still active;
3. validate the manifest, policy capabilities and approval-bound suppression threshold;
4. independently compare the complete source inventory token set, immutable disposition ledger,
   every cell/year/species aggregate and optional public row—loader-supplied pass flags alone do
   not authorise activation;
5. retire the old release and mark the candidate active;
6. change `active_release_id`;
7. advance the successful watermark and source counts;
8. mark the job successful and insert the notification outbox item;
9. delete job-scoped staging rows;
10. commit once.

That transaction scans the candidate ledger and removes job-scoped staging evidence. Its runtime,
lock duration and peak storage must be measured with the representative approximately five-million-
row workload before production; “atomic” does not imply “instantaneous”.

The serving views require the pointer **and** `release.status = 'active'` to agree. An incomplete or
inconsistent activation returns no candidate rows. Any activation failure rolls back the pointer,
watermark, private state and job-success transition together, leaving the previous release visible.

The loader has only `SELECT` and constrained column-level `INSERT` on source/release state, plus
`SELECT` and `INSERT` on publication rows and release-scoped dispositions. It cannot insert an
active release or pointer, nor directly update either. Finalisation authorises one candidate in its
transaction; a statement-level trigger checks that release/job/lock once per durable insert and an
RLS policy requires every inserted row to carry the authorised release ID. Publication and ledger
rows therefore become immutable after activation without a per-row catalogue lookup or a
multi-million-row trigger transition table.
`fail_candidate(uuid,text)` accepts only a fixed operational code and atomically
records the failed state, outbox event and cleanup debt. A security-definer janitor can delete data
only for an inactive release already marked `failed` or `discarded`; it refuses an active pointer
and clears the debt in the same purge transaction. Retired-release retention remains a separately
reviewed administrator operation.

Open jobs expose bounded progress updates. Once a job is `succeeded`, `failed` or `cancelled`, a
database trigger makes its status, counts and timestamps immutable. The loader has no insert access
to the reserved typed event ledger, so future event-writing semantics require a reviewed migration.

A lost activation acknowledgement is idempotent. Reinvoking the same active release returns its ID;
a separately rebuilt, fully validated candidate with the same stable source/policy/code identity is
marked `discarded`, its job points to the already-active release, and the release-level outbox
constraint prevents a duplicate success email. Its unused payload is marked `cleanup_pending` and
is purged best-effort immediately or obligatorily by the next source-lock owner.

Do not update active publication rows in place, rename tables during a release, or commit the
watermark separately. The BRERC source transaction is read-only and separate; distributed two-phase
commit is neither required nor desired.

## Watermarks and reconciliation

The successful watermark is represented by:

- `last_successful_modified_date`; and
- `last_successful_modified_key_token` (an HMAC audit token, not a resumable source key).

If the eventual BRERC marker is a PostgreSQL `date`, the next run must query with an inclusive
overlap (`date_mdb_modified >= last_successful_modified_date`) and perform idempotent upserts. A
strict `(date, id) > previous tuple` can miss a later modification on the same date with a lower
identifier. In-run ordering/upper-bound evidence may use the canonical source tuple while the
read-only source snapshot is open, but raw source keys are not persisted here. A lost source
snapshot is restarted; it is never resumed from the token.

Raw-source and public-table counts are not comparable: licensing, withholding, suppression and
aggregation intentionally change them. Deletions require an approved tombstone feed or a complete
source-key inventory from the same source snapshot. A count difference is only an alarm and cannot
identify a deletion; a deletion and insertion can also cancel numerically.

The manifest and database constraints support these exact equations:

```text
source rows = eligible before suppression + transform-withheld rows
eligible before suppression = published cell basis + suppression-withheld rows
source inventory count = source row count
```

Before activation, the database itself proves the inventory and disposition token sets are exactly
equal, fingerprints agree, transform-withheld and suppression-withheld rows are distinct, withheld
reason summaries match, and all cell/species-year/species keys and counts match the eligible ledger.
The approved suppression mode and `min_records_per_cell` are stored in both manifest and release
metadata: every published cohort must meet the threshold, every suppressed cohort must be below it,
and one cohort cannot be split between both dispositions. Required reconciliation rows and digests
remain additional audit evidence, not self-attested authority to switch the pointer.

The database validates digest shape and candidate/database equality, but it does **not** independently
recompute the application's canonical SHA-256 documents in SQL. The trusted coordinator computes
those digests; database-owned row-set, key, geometry, threshold and count comparisons are the
independent controls that prevent a copied or incorrect digest alone from activating bad rows.

## PostGIS map cells

`publication.public_distribution_cell.geom` is a British National Grid polygon with SRID 27700.
It is created from the already-generalised grid reference and its precision—never source point
coordinates. `loader_control.bng_cell_polygon` independently derives the exact BNG envelope;
constraints require the stored geometry to be topologically equal to it as well as valid,
non-empty and correctly sized. The private safe ledger also requires each record square to match
its declared precision and be covered by its aggregation cell. Martin receives only the active
`serve.public_distribution_cell` view. Cross-language corpus tests must still pin parity with the
Python and TypeScript grid-reference implementations.

## Release and operational records

- `etl_job` and `etl_job_event` store fixed status/error codes and typed numeric metrics, not record
  samples, arbitrary JSON or exception strings.
- `release` carries lifecycle state and preserves the base-release lineage.
- `release_manifest` is insert-only to the loader and binds source/view, query, policy, code,
  watermark, count and data digests.
- `withheld_summary` records fixed withholding reasons and counts.
- `notification_outbox` atomically records that a success/failure notification must be delivered;
  it stores a destination configuration alias, not an email address. Migration `0001` deliberately
  grants the loader only `SELECT` on this table: a later reviewed notifier role/worker must own the
  narrow delivery-state update, so the publication worker cannot mark its own alert delivered.
- `source_disposition` is immutable per release and contains only a private HMAC token and
  publication-safe/generalised state. `eligible`, transform-`withheld`, and `suppressed` are
  distinct. Suppressed rows retain only the safe species/year/cell cohort evidence needed for the
  database to prove the approved threshold; they carry no public row ID or optional row fields.
  Incremental candidates build a complete new ledger from the
  active base plus their validated delta before pointer activation. This deliberately costs more
  storage in exchange for rollback-safe visibility; retention must keep the active and required
  rollback releases.

Serving views enforce the capability flags in `public_release`: individual rows disappear when
disabled, optional place/abundance/record-type fields are masked independently, and verification
counts/statuses become null unless their corresponding aggregate/row capability is enabled. This
is a second fail-closed guard after the ETL policy—not permission to insert unapproved values.

`Load` and `Load_date` do not need to be copied into every data row. `release_id` is the row's exact
provenance; `release.load_mode` and its timestamps provide those values once without allowing them
to drift between tables.

## Deliberately unresolved external prerequisites

The schema does not make these client decisions true. Live incremental activation remains blocked
until BRERC supplies or approves:

- a versioned source view containing `date_mdb_modified`, including type/nullability/semantics;
- `unique_no` as non-null, unique, stable and never reused;
- a deletion/withdrawal signal or permission for complete inventory reconciliation;
- handling of publication-affecting lookup changes that may not update the record marker;
- catastrophic-empty and large-count-drop thresholds;
- live source/view/service/role identity evidence;
- precision, licensing, suppression, record-type and row-level publication policy.

The current frontend policy is aggregate-only, so `publication.public_record` must remain empty
unless a future approved policy explicitly enables individual rows and their exact fields.

The current safe streaming record does not yet carry BRERC `taxa_nb`, so
`publication.public_species.taxon_group` must remain null until a reviewed mapping is added to the
safe transform and its contract tests. The supplied source view also has no verified-status field:
`verification_available` and `record_verification_available` must remain false and both aggregate
verified counts and row verdicts must remain null. The database refuses contradictory rows; it does
not invent either value.

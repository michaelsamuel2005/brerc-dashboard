# Atomic full-snapshot refresh

## Outcome and boundary

The supported update path is now:

```text
complete BRERC view snapshot
  -> fail-closed transformation and reconciliation
  -> inactive PostgreSQL/PostGIS candidate
  -> database-owned validation
  -> one atomic active-release switch
  -> read-only FastAPI
  -> React dashboard
```

Use `brerc-load initial` once, when the destination has no active release. Use
`brerc-load refresh` for every later scheduled replacement. The refresh reads
the entire approved view again. It does not use the legacy nightly tables, a
modification watermark, a tombstone feed or the blocked `incremental` command.

This closes the engineering gap for safe scheduled updates. It does not provide
BRERC approval, production credentials, production infrastructure, a schedule
or scale evidence by itself.

## What refresh guarantees

- The source connector uses one locked, read-only, repeatable-read snapshot of
  the exact approved 39-column view.
- The destination candidate is bound to the active base release and to a source
  snapshot time that must strictly advance previously accepted evidence.
- Every row in the new source snapshot has exactly one inventory entry, one safe
  disposition and one non-delete delta entry.
- An updated source row is transformed from its current value. A removed source
  row is absent from the complete candidate. Neither change is public until the
  candidate passes all checks.
- Absolute row bounds and comparative drop/growth thresholds are immutable
  manifest evidence and are enforced again inside PostgreSQL.
- `serve.*` exposes only the active release. A failed, stale, incomplete or
  threshold-rejected candidate leaves the previous release active.
- A changed candidate retires the previous release and becomes active in one
  transaction. There is no half-old, half-new public state.
- An exactly identical candidate is validated, recorded as a successful reused
  release, then discarded with durable cleanup debt. Cleanup is attempted
  immediately and, if it cannot finish, must complete before the next job. Its
  newer source-snapshot evidence is retained, while the public `releaseId` stays
  unchanged.
- FastAPI reads each response through a read-only, repeatable-read transaction.
  Every public data response exposes the same active `releaseId` and
  `datasetVersion`. The browser pins that identity across a rendered page and
  fails closed, clears, re-anchors on provenance and refetches if it observes a
  release switch between requests.

## One-time destination upgrade

An administrator must apply all migrations in order. Migration 0003 refuses to
run twice and refuses to run while any ETL job is non-terminal:

```sh
psql -X -v ON_ERROR_STOP=1 -f db/roles.sql "$CONTROLLED_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 \
  -f db/migrations/0001_publication_store.sql "$CONTROLLED_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 \
  -f db/migrations/0002_sensitive_record_action.sql "$CONTROLLED_ADMIN_DSN"
psql -X -v ON_ERROR_STOP=1 \
  -f db/migrations/0003_full_snapshot_refresh.sql "$CONTROLLED_ADMIN_DSN"
```

`$CONTROLLED_ADMIN_DSN` is illustrative. Do not put a production DSN or
password in Git, ordinary email, shell history or scheduler output. Follow the
secret-managed `verify-full` TLS procedure in
[`POSTGRES_RELEASE_LOADER.md`](POSTGRES_RELEASE_LOADER.md).

After migration 0003, `brerc_loader` can execute
`loader_control.activate_release_candidate(uuid)`. It cannot execute the older
`activate_validated_release(uuid)` function directly.

## Configure the two modes

Copy `api/loader.configuration.example.yaml` to protected deployment storage and
replace every placeholder with a controlled value. Version
`brerc-loader-v3` requires separate initial bounds and all eight refresh
thresholds. BRERC's authorised data owner must approve the production values
after measuring the production candidate; do not reuse synthetic-test values.

The first run is:

```sh
brerc-load initial --config /controlled/path/loader.configuration.yaml
```

Every subsequent complete replacement is:

```sh
brerc-load refresh --config /controlled/path/loader.configuration.yaml
```

Treat exit status zero plus the fixed JSON `status:"ok"`, `state:"succeeded"`
and `activated:true` fields as success. For a changed refresh, record the new
`releaseId`. For a no-change refresh, the reported `releaseId` is the existing
active release, because the duplicate candidate was deliberately not published.
Never add a force path around a rejection.

## Scheduling it nightly

Once BRERC approves the cadence and production thresholds, the scheduler's
nightly command is simply the same `brerc-load refresh` command above. Schedule
one run at a time, use the protected configuration and secret store, retain an
outer scheduler timeout, and route the fixed terminal outcome to the monitoring
and notification worker. The per-source advisory lock rejects overlap; do not
configure a second invocation to bypass it.

Do not schedule the older `nightly_job()` implementation as a substitute. That
legacy path writes tables such as `occurrence_public`, `species` and
`distribution_cell`; the current FastAPI reads only the atomic `serve.*` release
views. The full-snapshot `refresh` command is the path that changes the dataset
the current dashboard actually reads.

## Synthetic two-snapshot acceptance

The authoritative automated rehearsal is the `postgis-loader-integration` CI
job in `.github/workflows/ci.yml`. It uses only invented data and performs all
of these steps:

1. Provision a separate TLS PostgreSQL 16 source with the exact 39-column view.
2. Provision a TLS PostgreSQL 16/PostGIS 3.5 destination, reviewed roles and
   migrations 0001–0003.
3. Run the complete destination lifecycle and adversarial database tests.
4. Load the three-row source as the initial active release.
5. Remove one ordinary source row and change a different row from disallowed to
   allowed licensing.
6. Run a complete `refresh`.
7. Verify that the former public species disappeared, the newly permitted
   species became the only public aggregate, and the sensitive species remained
   withheld.
8. Verify that the refresh release is active, the initial release is retired,
   both watermark endpoints remain null, and inventory/disposition counts cover
   the complete new snapshot.
9. Run the API suite against that refreshed release.
10. Build the production frontend with mocks disabled and run Playwright against
    the real FastAPI/PostGIS stack, including `releaseId` and `datasetVersion`.

The focused real-database test is:

```sh
cd api
BRERC_LOADER_PG_INTEGRATION=1 python -m unittest \
  loader_tests.test_postgis16_destination_integration.TestPostGIS16DestinationIntegration.test_real_source_full_snapshot_refresh_applies_updates_and_deletions
```

It intentionally skips unless the isolated source and destination services and
their test-only environment variables have been provisioned. The CI workflow is
the canonical, repeatable provisioning recipe. For a local run, use the same
pinned images, fixtures, TLS setup scripts and environment names from that job;
do not weaken TLS or substitute a developer's shared database merely to avoid a
skip.

After the focused test, these read-only checks describe the expected active
synthetic publication:

```sql
SELECT release_id, dataset_version
FROM serve.public_release;

SELECT species_id, total_records, first_year, last_year
FROM serve.public_species;

SELECT species_id, cell_id, record_year, precision_metres, record_count
FROM serve.public_distribution_cell;
```

The expected visible species is `SYNTH-E2E-3`, in 1 km cell `ST5872` for 2022,
with count 1. `SYNTH-E2E-1` is withheld and deleted source species
`SYNTH-E2E-2` is absent. These identifiers are synthetic test fixtures, never
BRERC data.

For a full local browser check, leave the refreshed destination running, then
use three terminals:

1. Start FastAPI from `api/` with `APP_ENV=prod` and `DATABASE_URL` set to the
   test-only `brerc_api_test` `verify-full` connection.
2. From `web/`, set `BRERC_LOCAL_API=http://127.0.0.1:8000`, run `npm ci`,
   `npm run build`, `npm run guard:bundle`, then
   `npm run preview -- --host 127.0.0.1 --port 4173`.
3. From `web/`, set `LIVE_BASE_URL=http://127.0.0.1:4173` and run
   `npx --no-install playwright test --config playwright.live.config.ts`.

The browser test is intentionally mocks-disabled for application/API requests.
It stubs only the external CARTO raster tile image so third-party availability
cannot make the same-origin integration result flaky.

## Evidence to retain for each production refresh

Retain only safe operational evidence:

- protected-main commit and deployed artifact/container digest;
- opaque job ID and resulting active release ID;
- source snapshot time, structural counts and candidate/database digests;
- the immutable initial/refresh threshold values used;
- terminal job/release state and notification delivery outcome; and
- post-run API provenance (`releaseId`, `datasetVersion`) plus a dashboard smoke
  result.

Do not copy source rows, coordinates, source-key tokens, DSNs, passwords or raw
exceptions into tickets, chat, email or artifacts.

## External acceptance gates that remain

Engineering tests cannot approve production policy or infrastructure. Do not
claim production completion until all of the following are retained:

1. BRERC's approved live-view identity, version-2 publication policy, species
   dictionary, licence/record-type mappings and real sensitive-record acceptance
   evidence.
2. Approved production values for the initial bounds and all eight refresh
   thresholds, plus the refresh schedule, runtime window and failure owner.
3. A green changed **five-million-row refresh** artifact from the exact
   protected-`main` merge SHA containing this implementation. Existing
   initial-only evidence does not cover refresh cost or behaviour.
4. Comparable green initial and changed-refresh acceptance on the intended
   BRERC-controlled PostgreSQL/PostGIS infrastructure over `verify-full` TLS.
5. Production monitoring/notification delivery, backup/recovery ownership and
   deployment/handover evidence.

The absent incremental contract is not one of these refresh gates. It remains a
gate only for enabling the separate `incremental` command.

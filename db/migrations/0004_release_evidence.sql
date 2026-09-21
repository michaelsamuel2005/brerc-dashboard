-- BRERC destination publication store -- migration 0004.
--
-- Adds narrow, privacy-safe evidence views for the monitor role. Operators can
-- bind evidence to the intended deployment and reconcile a completed loader
-- invocation with the active public release without granting the monitoring
-- login access to loader_control or publication base tables.

BEGIN;

SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('brerc:destination-schema-migration', 0)
);

DO $migration_guard$
BEGIN
    IF pg_catalog.to_regclass('loader_control.schema_migration') IS NULL THEN
        RAISE EXCEPTION
            'BRERC migrations 0001 through 0003 are absent; refusing migration 0004';
    ELSIF EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 4
           OR migration_key = '0004_release_evidence'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration 0004_release_evidence is already applied; refusing to re-run';
    ELSIF (
        SELECT count(*)
        FROM loader_control.schema_migration
    ) <> 3 OR NOT EXISTS (
        SELECT 1 FROM loader_control.schema_migration
        WHERE migration_version = 1 AND migration_key = '0001_publication_store'
    ) OR NOT EXISTS (
        SELECT 1 FROM loader_control.schema_migration
        WHERE migration_version = 2 AND migration_key = '0002_sensitive_record_action'
    ) OR NOT EXISTS (
        SELECT 1 FROM loader_control.schema_migration
        WHERE migration_version = 3 AND migration_key = '0003_full_snapshot_refresh'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration history is not exactly 0001 through 0003; refusing out-of-order migration 0004';
    END IF;
END
$migration_guard$;

CREATE VIEW serve.etl_release_evidence WITH (security_barrier = true) AS
SELECT
    job.job_id AS run_id,
    job.result_release_id AS release_id,
    source.active_release_id,
    public_release.dataset_version,
    manifest.source_snapshot_at AS source_data_as_of,
    manifest.candidate_sha256,
    job.base_release_id,
    job.reused_active_release,
    job.source_rows_seen AS source_rows,
    manifest.public_record_count AS public_records,
    manifest.cell_count AS distribution_cells,
    job.load_mode,
    job.status,
    job.started_at,
    job.finished_at
FROM loader_control.etl_job AS job
JOIN loader_control.source_state AS source
  ON source.source_id = job.source_id
 AND source.active_release_id = job.result_release_id
JOIN loader_control.release AS active_release
  ON active_release.release_id = source.active_release_id
 AND active_release.source_id = source.source_id
 AND active_release.status = 'active'
JOIN loader_control.release AS attempted_release
  ON attempted_release.job_id = job.job_id
 AND attempted_release.source_id = job.source_id
JOIN loader_control.release_manifest AS manifest
  ON manifest.release_id = attempted_release.release_id
JOIN publication.public_release AS public_release
  ON public_release.release_id = active_release.release_id
WHERE job.status = 'succeeded';

CREATE VIEW serve.etl_monitor_identity WITH (security_barrier = true) AS
SELECT environment_id, database_name
FROM loader_control.deployment_identity
WHERE singleton;

REVOKE ALL ON serve.etl_release_evidence FROM PUBLIC;
REVOKE ALL ON serve.etl_monitor_identity FROM PUBLIC;
GRANT SELECT ON serve.etl_release_evidence TO brerc_monitor;
GRANT SELECT ON serve.etl_monitor_identity TO brerc_monitor;

INSERT INTO loader_control.schema_migration (
    migration_version,
    migration_key,
    migration_name
) VALUES (
    4,
    '0004_release_evidence',
    'Least-privilege active-release evidence for monitored loader runs'
);

COMMIT;

-- BRERC destination publication store -- migration 0003.
--
-- Adds an explicit full-snapshot refresh lifecycle.  A refresh is deliberately
-- not an incremental load: it must carry one complete source inventory, one
-- complete disposition for every observed key, no delete actions and no source
-- watermarks.  Activation remains atomic and continues to use every validation
-- performed by migration 0001's activation routine.

BEGIN;

SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('brerc:destination-schema-migration', 0)
);

DO $migration_guard$
BEGIN
    IF pg_catalog.to_regclass('loader_control.schema_migration') IS NULL THEN
        RAISE EXCEPTION
            'BRERC migrations 0001 and 0002 are absent; refusing migration 0003';
    ELSIF EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 3
           OR migration_key = '0003_full_snapshot_refresh'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration 0003_full_snapshot_refresh is already applied; refusing to re-run';
    ELSIF (
        SELECT count(*)
        FROM loader_control.schema_migration
    ) <> 2 OR NOT EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 1
          AND migration_key = '0001_publication_store'
    ) OR NOT EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 2
          AND migration_key = '0002_sensitive_record_action'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration history is not exactly 0001 plus 0002; refusing out-of-order migration 0003';
    END IF;
END
$migration_guard$;

-- Migration and loader coordination use the same source-key lock namespace.
-- Fail instead of waiting indefinitely when a worker still owns a session lock.
-- The nonblocking SHARE lock freezes the source-id set while those advisory
-- locks are acquired; supported and future sources therefore cannot race the
-- enumeration by inserting a new source_state row.
LOCK TABLE loader_control.source_state IN SHARE MODE NOWAIT;

DO $source_locks$
DECLARE
    locked_source_id text;
BEGIN
    FOR locked_source_id IN
        SELECT source_id
        FROM (
            SELECT 'dashboard.main_data_dash'::text AS source_id
            UNION
            SELECT s.source_id FROM loader_control.source_state AS s
        ) AS known_sources
        ORDER BY source_id COLLATE "C"
    LOOP
        IF NOT pg_catalog.pg_try_advisory_xact_lock(
            pg_catalog.hashtextextended(locked_source_id, 0)
        ) THEN
            RAISE EXCEPTION USING
                ERRCODE = '55P03',
                MESSAGE = 'an ETL worker owns a source lock; refusing migration';
        END IF;
    END LOOP;
END
$source_locks$;

-- Only after the nonblocking source-lock test succeeds do we take DDL locks.
-- This prevents the migration from waiting behind a live worker transaction.
-- It also stops a v2 loader which passed preflight immediately before this
-- transaction from creating a partly migrated candidate.
LOCK TABLE loader_control.source_state IN ACCESS EXCLUSIVE MODE;
LOCK TABLE loader_control.etl_job IN ACCESS EXCLUSIVE MODE;
LOCK TABLE loader_control.release IN ACCESS EXCLUSIVE MODE;
LOCK TABLE loader_control.release_manifest IN ACCESS EXCLUSIVE MODE;

DO $open_job_guard$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM loader_control.etl_job
        WHERE status NOT IN ('succeeded', 'failed', 'cancelled')
    ) THEN
        RAISE EXCEPTION
            'nonterminal ETL jobs exist; refusing full-snapshot refresh migration';
    END IF;
END
$open_job_guard$;

ALTER TABLE loader_control.etl_job
    DROP CONSTRAINT etl_job_load_mode,
    DROP CONSTRAINT etl_job_base_matches_mode,
    ADD CONSTRAINT etl_job_load_mode CHECK (
        load_mode IN ('initial', 'incremental', 'refresh')
    ),
    ADD CONSTRAINT etl_job_base_matches_mode CHECK (
        (load_mode = 'initial' AND base_release_id IS NULL)
        OR (
            load_mode IN ('incremental', 'refresh')
            AND base_release_id IS NOT NULL
        )
    );

ALTER TABLE loader_control.release
    DROP CONSTRAINT release_load_mode,
    DROP CONSTRAINT release_base_matches_mode,
    ADD CONSTRAINT release_load_mode CHECK (
        load_mode IN ('initial', 'incremental', 'refresh')
    ),
    ADD CONSTRAINT release_base_matches_mode CHECK (
        (load_mode = 'initial' AND base_release_id IS NULL)
        OR (
            load_mode IN ('incremental', 'refresh')
            AND base_release_id IS NOT NULL
        )
    );

-- A no-change refresh deliberately reuses the active publication payload but
-- still advances source_state.last_source_snapshot_at after the complete source
-- snapshot has been validated.  Expose that checked-through time as the public
-- data-as-of value; otherwise the dashboard would misleadingly remain stuck at
-- the original release timestamp after every successful no-change refresh.
CREATE OR REPLACE VIEW serve.public_release WITH (security_barrier = true) AS
SELECT
    p.release_id,
    r.activated_at AS published_at,
    s.last_source_snapshot_at AS source_data_as_of,
    p.publication_policy_version,
    p.dataset_version,
    p.verification_available,
    p.individual_records_available,
    p.record_verification_available,
    p.place_available,
    p.abundance_available,
    p.record_type_available,
    p.public_source_label,
    p.sensitive_record_action
FROM publication.public_release AS p
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

-- Keep the internal PostgreSQL monitoring contract honest about no-change
-- refreshes.  Append the field so existing consumers retain their column
-- order; the view's existing brerc_monitor grant is preserved by OR REPLACE.
CREATE OR REPLACE VIEW serve.etl_job_status WITH (security_barrier = true) AS
SELECT
    job_id,
    source_id,
    attempt,
    load_mode,
    status,
    started_at,
    heartbeat_at,
    finished_at,
    failure_code,
    source_rows_seen,
    candidate_rows,
    rows_withheld,
    created_at,
    reused_active_release
FROM loader_control.etl_job;

-- These values are immutable approval evidence, not operational defaults.  A
-- refresh must bind every threshold; other modes must bind none of them.
ALTER TABLE loader_control.release_manifest
    ADD COLUMN refresh_min_source_rows bigint,
    ADD COLUMN refresh_max_source_rows bigint,
    ADD COLUMN refresh_max_source_row_drop_bps integer,
    ADD COLUMN refresh_max_source_row_growth_bps integer,
    ADD COLUMN refresh_max_publication_basis_drop_bps integer,
    ADD COLUMN refresh_max_species_drop_bps integer,
    ADD COLUMN refresh_max_cell_drop_bps integer,
    ADD COLUMN refresh_max_species_year_drop_bps integer,
    ADD CONSTRAINT release_manifest_refresh_thresholds CHECK (
        (
            refresh_min_source_rows IS NULL
            AND refresh_max_source_rows IS NULL
            AND refresh_max_source_row_drop_bps IS NULL
            AND refresh_max_source_row_growth_bps IS NULL
            AND refresh_max_publication_basis_drop_bps IS NULL
            AND refresh_max_species_drop_bps IS NULL
            AND refresh_max_cell_drop_bps IS NULL
            AND refresh_max_species_year_drop_bps IS NULL
        )
        OR (
            refresh_min_source_rows IS NOT NULL
            AND refresh_max_source_rows IS NOT NULL
            AND refresh_max_source_row_drop_bps IS NOT NULL
            AND refresh_max_source_row_growth_bps IS NOT NULL
            AND refresh_max_publication_basis_drop_bps IS NOT NULL
            AND refresh_max_species_drop_bps IS NOT NULL
            AND refresh_max_cell_drop_bps IS NOT NULL
            AND refresh_max_species_year_drop_bps IS NOT NULL
            AND refresh_min_source_rows BETWEEN 1 AND 1000000000
            AND refresh_max_source_rows BETWEEN refresh_min_source_rows AND 1000000000
            AND refresh_max_source_row_drop_bps BETWEEN 0 AND 10000
            AND refresh_max_source_row_growth_bps BETWEEN 0 AND 1000000000
            AND refresh_max_publication_basis_drop_bps BETWEEN 0 AND 10000
            AND refresh_max_species_drop_bps BETWEEN 0 AND 10000
            AND refresh_max_cell_drop_bps BETWEEN 0 AND 10000
            AND refresh_max_species_year_drop_bps BETWEEN 0 AND 10000
        )
    );

-- Cross-table mode rules cannot be expressed as a CHECK constraint.  Enforce
-- them at the only immutable manifest insertion point as well as at activation.
CREATE FUNCTION loader_control.enforce_refresh_manifest_mode()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $enforce_refresh_manifest_mode$
DECLARE
    candidate_load_mode text;
BEGIN
    SELECT r.load_mode
    INTO candidate_load_mode
    FROM loader_control.release AS r
    WHERE r.release_id = NEW.release_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'release manifest has no candidate lifecycle';
    END IF;

    IF candidate_load_mode = 'refresh' THEN
        IF NEW.lower_modified_date IS NOT NULL
            OR NEW.lower_modified_key_token IS NOT NULL
            OR NEW.upper_modified_date IS NOT NULL
            OR NEW.upper_modified_key_token IS NOT NULL
            OR NEW.refresh_min_source_rows IS NULL
            OR NEW.refresh_max_source_rows IS NULL
            OR NEW.refresh_max_source_row_drop_bps IS NULL
            OR NEW.refresh_max_source_row_growth_bps IS NULL
            OR NEW.refresh_max_publication_basis_drop_bps IS NULL
            OR NEW.refresh_max_species_drop_bps IS NULL
            OR NEW.refresh_max_cell_drop_bps IS NULL
            OR NEW.refresh_max_species_year_drop_bps IS NULL
        THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'refresh manifest must bind all refresh thresholds and no watermarks';
        END IF;
    ELSIF NEW.refresh_min_source_rows IS NOT NULL
        OR NEW.refresh_max_source_rows IS NOT NULL
        OR NEW.refresh_max_source_row_drop_bps IS NOT NULL
        OR NEW.refresh_max_source_row_growth_bps IS NOT NULL
        OR NEW.refresh_max_publication_basis_drop_bps IS NOT NULL
        OR NEW.refresh_max_species_drop_bps IS NOT NULL
        OR NEW.refresh_max_cell_drop_bps IS NOT NULL
        OR NEW.refresh_max_species_year_drop_bps IS NOT NULL
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'non-refresh manifest must not bind refresh thresholds';
    END IF;

    RETURN NEW;
END
$enforce_refresh_manifest_mode$;

CREATE TRIGGER release_manifest_refresh_mode_guard
BEFORE INSERT ON loader_control.release_manifest
FOR EACH ROW EXECUTE FUNCTION loader_control.enforce_refresh_manifest_mode();

-- Compare stored publication and reconciliation payloads rather than trusting
-- only a caller-supplied digest.  Snapshot timestamps and refresh limits are
-- intentionally excluded: they are evidence about this run, not public data.
CREATE FUNCTION loader_control.release_payload_is_identical(
    left_release_id uuid,
    right_release_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $release_payload_is_identical$
    SELECT
        EXISTS (
            SELECT 1
            FROM loader_control.release_manifest AS l
            JOIN loader_control.release_manifest AS r
              ON r.release_id = right_release_id
            WHERE l.release_id = left_release_id
              AND ROW(
                  l.source_contract_version,
                  l.source_contract_sha256,
                  l.observed_view_definition_sha256,
                  l.observed_view_identity_sha256,
                  l.projection_version,
                  l.projection_sha256,
                  l.publication_policy_version,
                  l.publication_policy_sha256,
                  l.policy_approval_sha256,
                  l.sensitive_record_action,
                  l.suppression_mode,
                  l.min_records_per_cell,
                  l.etl_version,
                  l.compatibility_sha256,
                  l.species_dictionary_sha256,
                  l.species_dictionary_artifact_sha256,
                  l.sensitivity_snapshot_sha256,
                  l.source_row_count,
                  l.source_inventory_count,
                  l.delta_row_count,
                  l.eligible_pre_suppression_count,
                  l.transform_withheld_count,
                  l.suppression_withheld_count,
                  l.published_basis_count,
                  l.species_count,
                  l.cell_count,
                  l.species_year_count,
                  l.public_record_count,
                  l.source_result_sha256,
                  l.candidate_sha256,
                  l.database_sha256
              ) IS NOT DISTINCT FROM ROW(
                  r.source_contract_version,
                  r.source_contract_sha256,
                  r.observed_view_definition_sha256,
                  r.observed_view_identity_sha256,
                  r.projection_version,
                  r.projection_sha256,
                  r.publication_policy_version,
                  r.publication_policy_sha256,
                  r.policy_approval_sha256,
                  r.sensitive_record_action,
                  r.suppression_mode,
                  r.min_records_per_cell,
                  r.etl_version,
                  r.compatibility_sha256,
                  r.species_dictionary_sha256,
                  r.species_dictionary_artifact_sha256,
                  r.sensitivity_snapshot_sha256,
                  r.source_row_count,
                  r.source_inventory_count,
                  r.delta_row_count,
                  r.eligible_pre_suppression_count,
                  r.transform_withheld_count,
                  r.suppression_withheld_count,
                  r.published_basis_count,
                  r.species_count,
                  r.cell_count,
                  r.species_year_count,
                  r.public_record_count,
                  r.source_result_sha256,
                  r.candidate_sha256,
                  r.database_sha256
              )
        )
        AND NOT EXISTS (
            (
                SELECT source_key_token, input_fingerprint, disposition, withheld_reason,
                    species_id, scientific_name, common_name, record_grid_ref,
                    record_precision_metres, cell_id, cell_precision_metres,
                    min_easting, min_northing, max_easting, max_northing,
                    record_year, public_record_id, place, abundance, record_type,
                    verified_status, source_label
                FROM loader_control.source_disposition
                WHERE release_id = left_release_id
                EXCEPT
                SELECT source_key_token, input_fingerprint, disposition, withheld_reason,
                    species_id, scientific_name, common_name, record_grid_ref,
                    record_precision_metres, cell_id, cell_precision_metres,
                    min_easting, min_northing, max_easting, max_northing,
                    record_year, public_record_id, place, abundance, record_type,
                    verified_status, source_label
                FROM loader_control.source_disposition
                WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT source_key_token, input_fingerprint, disposition, withheld_reason,
                    species_id, scientific_name, common_name, record_grid_ref,
                    record_precision_metres, cell_id, cell_precision_metres,
                    min_easting, min_northing, max_easting, max_northing,
                    record_year, public_record_id, place, abundance, record_type,
                    verified_status, source_label
                FROM loader_control.source_disposition
                WHERE release_id = right_release_id
                EXCEPT
                SELECT source_key_token, input_fingerprint, disposition, withheld_reason,
                    species_id, scientific_name, common_name, record_grid_ref,
                    record_precision_metres, cell_id, cell_precision_metres,
                    min_easting, min_northing, max_easting, max_northing,
                    record_year, public_record_id, place, abundance, record_type,
                    verified_status, source_label
                FROM loader_control.source_disposition
                WHERE release_id = left_release_id
            )
        )
        AND NOT EXISTS (
            (
                SELECT reason_code, row_count FROM loader_control.withheld_summary
                WHERE release_id = left_release_id
                EXCEPT
                SELECT reason_code, row_count FROM loader_control.withheld_summary
                WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT reason_code, row_count FROM loader_control.withheld_summary
                WHERE release_id = right_release_id
                EXCEPT
                SELECT reason_code, row_count FROM loader_control.withheld_summary
                WHERE release_id = left_release_id
            )
        )
        AND NOT EXISTS (
            (
                SELECT publication_policy_version, dataset_version,
                    sensitive_record_action, suppression_mode, min_records_per_cell,
                    verification_available, individual_records_available,
                    record_verification_available, place_available,
                    abundance_available, record_type_available, public_source_label
                FROM publication.public_release WHERE release_id = left_release_id
                EXCEPT
                SELECT publication_policy_version, dataset_version,
                    sensitive_record_action, suppression_mode, min_records_per_cell,
                    verification_available, individual_records_available,
                    record_verification_available, place_available,
                    abundance_available, record_type_available, public_source_label
                FROM publication.public_release WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT publication_policy_version, dataset_version,
                    sensitive_record_action, suppression_mode, min_records_per_cell,
                    verification_available, individual_records_available,
                    record_verification_available, place_available,
                    abundance_available, record_type_available, public_source_label
                FROM publication.public_release WHERE release_id = right_release_id
                EXCEPT
                SELECT publication_policy_version, dataset_version,
                    sensitive_record_action, suppression_mode, min_records_per_cell,
                    verification_available, individual_records_available,
                    record_verification_available, place_available,
                    abundance_available, record_type_available, public_source_label
                FROM publication.public_release WHERE release_id = left_release_id
            )
        )
        AND NOT EXISTS (
            (
                SELECT species_id, scientific_name, common_name, taxon_group,
                    total_records, first_year, last_year
                FROM publication.public_species WHERE release_id = left_release_id
                EXCEPT
                SELECT species_id, scientific_name, common_name, taxon_group,
                    total_records, first_year, last_year
                FROM publication.public_species WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT species_id, scientific_name, common_name, taxon_group,
                    total_records, first_year, last_year
                FROM publication.public_species WHERE release_id = right_release_id
                EXCEPT
                SELECT species_id, scientific_name, common_name, taxon_group,
                    total_records, first_year, last_year
                FROM publication.public_species WHERE release_id = left_release_id
            )
        )
        AND NOT EXISTS (
            (
                SELECT species_id, record_year, cell_id, precision_metres,
                    record_count, verified_count, public.ST_AsEWKB(geom)
                FROM publication.public_distribution_cell
                WHERE release_id = left_release_id
                EXCEPT
                SELECT species_id, record_year, cell_id, precision_metres,
                    record_count, verified_count, public.ST_AsEWKB(geom)
                FROM publication.public_distribution_cell
                WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT species_id, record_year, cell_id, precision_metres,
                    record_count, verified_count, public.ST_AsEWKB(geom)
                FROM publication.public_distribution_cell
                WHERE release_id = right_release_id
                EXCEPT
                SELECT species_id, record_year, cell_id, precision_metres,
                    record_count, verified_count, public.ST_AsEWKB(geom)
                FROM publication.public_distribution_cell
                WHERE release_id = left_release_id
            )
        )
        AND NOT EXISTS (
            (
                SELECT species_id, record_year, record_count, verified_count
                FROM publication.public_species_year WHERE release_id = left_release_id
                EXCEPT
                SELECT species_id, record_year, record_count, verified_count
                FROM publication.public_species_year WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT species_id, record_year, record_count, verified_count
                FROM publication.public_species_year WHERE release_id = right_release_id
                EXCEPT
                SELECT species_id, record_year, record_count, verified_count
                FROM publication.public_species_year WHERE release_id = left_release_id
            )
        )
        AND NOT EXISTS (
            (
                SELECT public_record_id, species_id, scientific_name, common_name,
                    grid_ref, precision_metres, place, record_year, abundance,
                    record_type, verified_status, source_label
                FROM publication.public_record WHERE release_id = left_release_id
                EXCEPT
                SELECT public_record_id, species_id, scientific_name, common_name,
                    grid_ref, precision_metres, place, record_year, abundance,
                    record_type, verified_status, source_label
                FROM publication.public_record WHERE release_id = right_release_id
            )
            UNION ALL
            (
                SELECT public_record_id, species_id, scientific_name, common_name,
                    grid_ref, precision_metres, place, record_year, abundance,
                    record_type, verified_status, source_label
                FROM publication.public_record WHERE release_id = right_release_id
                EXCEPT
                SELECT public_record_id, species_id, scientific_name, common_name,
                    grid_ref, precision_metres, place, record_year, abundance,
                    record_type, verified_status, source_label
                FROM publication.public_record WHERE release_id = left_release_id
            )
        );
$release_payload_is_identical$;

-- Sole loader-facing activation entry point.  The legacy function remains the
-- audited validator and switch implementation, but the loader can no longer
-- call it directly and therefore cannot bypass refresh-specific guarantees.
CREATE FUNCTION loader_control.activate_release_candidate(candidate_release_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $activate_release_candidate$
DECLARE
    candidate_source_id text;
    candidate_job_id uuid;
    candidate_base_release_id uuid;
    candidate_load_mode text;
    candidate_status text;
    candidate_job_status text;
    current_active_release_id uuid;
    current_source_snapshot_at timestamp with time zone;
    manifest loader_control.release_manifest%ROWTYPE;
    base_manifest loader_control.release_manifest%ROWTYPE;
    active_manifest loader_control.release_manifest%ROWTYPE;
    inventory_count bigint;
    delta_count bigint;
    disposition_count bigint;
    changed_rows bigint;
    identical_to_active boolean := false;
BEGIN
    SELECT
        r.source_id,
        r.job_id,
        r.base_release_id,
        r.load_mode,
        r.status,
        j.status
    INTO
        candidate_source_id,
        candidate_job_id,
        candidate_base_release_id,
        candidate_load_mode,
        candidate_status,
        candidate_job_status
    FROM loader_control.release AS r
    JOIN loader_control.etl_job AS j
      ON j.job_id = r.job_id
     AND j.source_id = r.source_id
     AND j.load_mode = r.load_mode
     AND j.base_release_id IS NOT DISTINCT FROM r.base_release_id
    WHERE r.release_id = candidate_release_id
    FOR UPDATE OF r, j;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate release is absent';
    END IF;

    IF candidate_load_mode = 'incremental' THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'incremental activation remains blocked pending an approved source contract';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_locks AS held
        WHERE held.locktype = 'advisory'
          AND held.pid = pg_catalog.pg_backend_pid()
          AND held.mode = 'ExclusiveLock'
          AND held.granted
          AND held.objsubid = 1
          AND held.classid = (
              (pg_catalog.hashtextextended(candidate_source_id, 0) >> 32)
              & 4294967295
          )::oid
          AND held.objid = (
              pg_catalog.hashtextextended(candidate_source_id, 0)
              & 4294967295
          )::oid
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'source session advisory lock is not held by this worker';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(candidate_source_id, 0)
    );

    SELECT s.active_release_id, s.last_source_snapshot_at
    INTO current_active_release_id, current_source_snapshot_at
    FROM loader_control.source_state AS s
    WHERE s.source_id = candidate_source_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate source state is absent';
    END IF;

    IF candidate_status = 'active'
        AND current_active_release_id = candidate_release_id
    THEN
        RETURN candidate_release_id;
    END IF;

    IF candidate_status NOT IN ('candidate', 'validated')
        OR candidate_job_status <> 'activating'
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate lifecycle is not ready for activation';
    END IF;

    SELECT m.*
    INTO manifest
    FROM loader_control.release_manifest AS m
    WHERE m.release_id = candidate_release_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate manifest is absent';
    END IF;

    IF candidate_load_mode = 'initial' THEN
        IF manifest.refresh_min_source_rows IS NOT NULL
            OR manifest.refresh_max_source_rows IS NOT NULL
            OR manifest.refresh_max_source_row_drop_bps IS NOT NULL
            OR manifest.refresh_max_source_row_growth_bps IS NOT NULL
            OR manifest.refresh_max_publication_basis_drop_bps IS NOT NULL
            OR manifest.refresh_max_species_drop_bps IS NOT NULL
            OR manifest.refresh_max_cell_drop_bps IS NOT NULL
            OR manifest.refresh_max_species_year_drop_bps IS NOT NULL
        THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'initial candidate contains refresh-only threshold evidence';
        END IF;
        RETURN loader_control.activate_validated_release(candidate_release_id);
    ELSIF candidate_load_mode <> 'refresh' THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate load mode is outside the activation contract';
    END IF;

    IF candidate_base_release_id IS NULL
        OR manifest.lower_modified_date IS NOT NULL
        OR manifest.lower_modified_key_token IS NOT NULL
        OR manifest.upper_modified_date IS NOT NULL
        OR manifest.upper_modified_key_token IS NOT NULL
        OR manifest.refresh_min_source_rows IS NULL
        OR manifest.refresh_max_source_rows IS NULL
        OR manifest.refresh_max_source_row_drop_bps IS NULL
        OR manifest.refresh_max_source_row_growth_bps IS NULL
        OR manifest.refresh_max_publication_basis_drop_bps IS NULL
        OR manifest.refresh_max_species_drop_bps IS NULL
        OR manifest.refresh_max_cell_drop_bps IS NULL
        OR manifest.refresh_max_species_year_drop_bps IS NULL
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'refresh candidate lacks complete threshold evidence or carries a watermark';
    END IF;

    SELECT m.*
    INTO base_manifest
    FROM loader_control.release_manifest AS m
    JOIN loader_control.release AS r ON r.release_id = m.release_id
    WHERE m.release_id = candidate_base_release_id
      AND r.source_id = candidate_source_id
      AND r.status IN ('active', 'retired');
    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'refresh base release is absent or was never activated';
    END IF;

    IF current_active_release_id IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'refresh source no longer has an active release';
    END IF;

    SELECT m.*
    INTO active_manifest
    FROM loader_control.release_manifest AS m
    JOIN loader_control.release AS r ON r.release_id = m.release_id
    WHERE m.release_id = current_active_release_id
      AND r.source_id = candidate_source_id
      AND r.status = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'active release and source pointer are inconsistent';
    END IF;

    -- A refresh is always based on the source pointer locked above.  Unlike an
    -- acknowledgement retry of an already-activated candidate, a newly built
    -- stale candidate is never accepted merely because its payload happens to
    -- resemble the current active release.
    IF current_active_release_id IS DISTINCT FROM candidate_base_release_id THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'active release changed after the refresh candidate began';
    END IF;

    IF current_source_snapshot_at IS NULL
        OR manifest.source_snapshot_at <= base_manifest.source_snapshot_at
        OR manifest.source_snapshot_at <= active_manifest.source_snapshot_at
        OR manifest.source_snapshot_at <= current_source_snapshot_at
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'refresh source snapshot does not advance the activated evidence';
    END IF;

    SELECT count(*) INTO inventory_count
    FROM loader_stage.source_inventory
    WHERE job_id = candidate_job_id;
    SELECT count(*) INTO delta_count
    FROM loader_stage.disposition_delta
    WHERE job_id = candidate_job_id;
    SELECT count(*) INTO disposition_count
    FROM loader_control.source_disposition
    WHERE release_id = candidate_release_id;

    IF inventory_count <> manifest.source_row_count
        OR inventory_count <> manifest.source_inventory_count
        OR delta_count <> inventory_count
        OR delta_count <> manifest.delta_row_count
        OR disposition_count <> inventory_count
        OR EXISTS (
            SELECT 1 FROM loader_stage.source_inventory
            WHERE job_id = candidate_job_id
              AND observed_modified_date IS NOT NULL
        )
        OR EXISTS (
            SELECT 1 FROM loader_stage.disposition_delta
            WHERE job_id = candidate_job_id
              AND action = 'delete'
        )
        OR EXISTS (
            SELECT 1
            FROM (
                (
                    SELECT i.source_key_token, i.input_fingerprint
                    FROM loader_stage.source_inventory AS i
                    WHERE i.job_id = candidate_job_id
                    EXCEPT
                    SELECT d.source_key_token, d.input_fingerprint
                    FROM loader_control.source_disposition AS d
                    WHERE d.release_id = candidate_release_id
                )
                UNION ALL
                (
                    SELECT d.source_key_token, d.input_fingerprint
                    FROM loader_control.source_disposition AS d
                    WHERE d.release_id = candidate_release_id
                    EXCEPT
                    SELECT i.source_key_token, i.input_fingerprint
                    FROM loader_stage.source_inventory AS i
                    WHERE i.job_id = candidate_job_id
                )
            ) AS inventory_difference
        )
        OR EXISTS (
            SELECT 1
            FROM (
                (
                    SELECT i.source_key_token
                    FROM loader_stage.source_inventory AS i
                    WHERE i.job_id = candidate_job_id
                    EXCEPT
                    SELECT x.source_key_token
                    FROM loader_stage.disposition_delta AS x
                    WHERE x.job_id = candidate_job_id
                      AND x.action <> 'delete'
                )
                UNION ALL
                (
                    SELECT x.source_key_token
                    FROM loader_stage.disposition_delta AS x
                    WHERE x.job_id = candidate_job_id
                      AND x.action <> 'delete'
                    EXCEPT
                    SELECT i.source_key_token
                    FROM loader_stage.source_inventory AS i
                    WHERE i.job_id = candidate_job_id
                )
            ) AS delta_difference
        )
        OR EXISTS (
            SELECT 1
            FROM loader_stage.disposition_delta AS x
            JOIN loader_control.source_disposition AS d
              ON d.release_id = candidate_release_id
             AND d.source_key_token = x.source_key_token
            WHERE x.job_id = candidate_job_id
              AND (
                  x.action IS DISTINCT FROM CASE d.disposition
                      WHEN 'eligible' THEN 'upsert'
                      WHEN 'withheld' THEN 'withhold'
                      WHEN 'suppressed' THEN 'suppress'
                  END
                  OR ROW(
                      x.input_fingerprint, x.withheld_reason, x.species_id,
                      x.scientific_name, x.common_name, x.record_grid_ref,
                      x.record_precision_metres, x.cell_id, x.cell_precision_metres,
                      x.min_easting, x.min_northing, x.max_easting, x.max_northing,
                      x.record_year, x.public_record_id, x.place, x.abundance,
                      x.record_type, x.verified_status, x.source_label
                  ) IS DISTINCT FROM ROW(
                      d.input_fingerprint, d.withheld_reason, d.species_id,
                      d.scientific_name, d.common_name, d.record_grid_ref,
                      d.record_precision_metres, d.cell_id, d.cell_precision_metres,
                      d.min_easting, d.min_northing, d.max_easting, d.max_northing,
                      d.record_year, d.public_record_id, d.place, d.abundance,
                      d.record_type, d.verified_status, d.source_label
                  )
              )
        )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'refresh candidate is not one complete no-delete source snapshot';
    END IF;

    -- Compare with exact integer inequalities.  Casting before multiplication
    -- prevents bigint overflow and avoids percentage-rounding ambiguity.
    IF manifest.source_row_count NOT BETWEEN
            manifest.refresh_min_source_rows AND manifest.refresh_max_source_rows
        OR base_manifest.source_row_count < 1
        OR base_manifest.published_basis_count < 1
        OR base_manifest.species_count < 1
        OR base_manifest.cell_count < 1
        OR base_manifest.species_year_count < 1
        OR manifest.source_row_count::numeric * 10000
            < base_manifest.source_row_count::numeric
                * (10000 - manifest.refresh_max_source_row_drop_bps)
        OR manifest.source_row_count::numeric * 10000
            > base_manifest.source_row_count::numeric
                * (10000 + manifest.refresh_max_source_row_growth_bps)
        OR manifest.published_basis_count::numeric * 10000
            < base_manifest.published_basis_count::numeric
                * (10000 - manifest.refresh_max_publication_basis_drop_bps)
        OR manifest.species_count::numeric * 10000
            < base_manifest.species_count::numeric
                * (10000 - manifest.refresh_max_species_drop_bps)
        OR manifest.cell_count::numeric * 10000
            < base_manifest.cell_count::numeric
                * (10000 - manifest.refresh_max_cell_drop_bps)
        OR manifest.species_year_count::numeric * 10000
            < base_manifest.species_year_count::numeric
                * (10000 - manifest.refresh_max_species_year_drop_bps)
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'refresh candidate exceeds its immutable comparative thresholds';
    END IF;

    -- Avoid multi-million-row equality scans for an obviously changed release.
    -- Digests are only a prefilter; the exact stored-row comparison remains the
    -- authority before any active release is reused.
    IF manifest.candidate_sha256 = active_manifest.candidate_sha256
        AND manifest.database_sha256 = active_manifest.database_sha256
        AND manifest.source_result_sha256 = active_manifest.source_result_sha256
        AND manifest.source_contract_sha256 = active_manifest.source_contract_sha256
        AND manifest.observed_view_definition_sha256
            = active_manifest.observed_view_definition_sha256
        AND manifest.observed_view_identity_sha256
            = active_manifest.observed_view_identity_sha256
        AND manifest.projection_sha256 = active_manifest.projection_sha256
        AND manifest.publication_policy_sha256
            = active_manifest.publication_policy_sha256
        AND manifest.policy_approval_sha256 = active_manifest.policy_approval_sha256
        AND manifest.etl_version = active_manifest.etl_version
        AND manifest.compatibility_sha256 = active_manifest.compatibility_sha256
        AND manifest.species_dictionary_sha256
            = active_manifest.species_dictionary_sha256
        AND manifest.species_dictionary_artifact_sha256
            = active_manifest.species_dictionary_artifact_sha256
        AND manifest.sensitivity_snapshot_sha256
            = active_manifest.sensitivity_snapshot_sha256
    THEN
        identical_to_active := loader_control.release_payload_is_identical(
            current_active_release_id,
            candidate_release_id
        );
    END IF;

    IF identical_to_active THEN
        -- Run the audited v1 validation and switch in a subtransaction, then
        -- roll its changes back deliberately.  Only our fixed sentinel is
        -- caught; any real validation error still aborts activation.
        BEGIN
            PERFORM loader_control.activate_validated_release(candidate_release_id);
            RAISE EXCEPTION USING
                ERRCODE = 'BR001',
                MESSAGE = 'validated identical refresh sentinel';
        EXCEPTION
            WHEN SQLSTATE 'BR001' THEN
                NULL;
        END;

        UPDATE loader_control.release
        SET status = 'discarded',
            cleanup_pending = true
        WHERE release_id = candidate_release_id
          AND status IN ('candidate', 'validated');
        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION USING
                ERRCODE = '40001',
                MESSAGE = 'identical refresh candidate could not be discarded exactly once';
        END IF;

        UPDATE loader_control.etl_job
        SET status = 'succeeded',
            result_release_id = current_active_release_id,
            reused_active_release = true,
            source_rows_seen = manifest.source_row_count,
            candidate_rows = manifest.published_basis_count,
            rows_withheld = manifest.transform_withheld_count
                + manifest.suppression_withheld_count,
            finished_at = transaction_timestamp(),
            heartbeat_at = transaction_timestamp()
        WHERE job_id = candidate_job_id
          AND status = 'activating';
        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION USING
                ERRCODE = '40001',
                MESSAGE = 'identical refresh job could not reach success exactly once';
        END IF;

        UPDATE loader_control.source_state AS s
        SET last_successful_modified_date = NULL,
            last_successful_modified_key_token = NULL,
            last_source_snapshot_at = manifest.source_snapshot_at,
            last_source_row_count = manifest.source_row_count,
            last_full_reconciliation_at = transaction_timestamp(),
            compatibility_sha256 = manifest.compatibility_sha256,
            updated_at = transaction_timestamp()
        WHERE source_id = candidate_source_id
          AND s.active_release_id = current_active_release_id;
        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION USING
                ERRCODE = '40001',
                MESSAGE = 'identical refresh could not advance source evidence exactly once';
        END IF;

        INSERT INTO loader_control.notification_outbox (
            notification_id,
            job_id,
            release_id,
            event_type,
            destination_key
        ) VALUES (
            candidate_release_id,
            candidate_job_id,
            current_active_release_id,
            'etl_succeeded',
            'etl-operations'
        ) ON CONFLICT (release_id, event_type)
            WHERE event_type = 'etl_succeeded'
            DO NOTHING;

        RETURN current_active_release_id;
    END IF;

    RETURN loader_control.activate_validated_release(candidate_release_id);
END
$activate_release_candidate$;

REVOKE ALL ON FUNCTION loader_control.enforce_refresh_manifest_mode() FROM PUBLIC;
REVOKE ALL ON FUNCTION loader_control.release_payload_is_identical(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION loader_control.activate_release_candidate(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION loader_control.activate_validated_release(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION loader_control.activate_validated_release(uuid) FROM brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.activate_release_candidate(uuid) TO brerc_loader;

INSERT INTO loader_control.schema_migration (
    migration_version,
    migration_key,
    migration_name
) VALUES (
    3,
    '0003_full_snapshot_refresh',
    'Explicit atomic full-snapshot refresh with immutable comparative thresholds'
);

COMMIT;

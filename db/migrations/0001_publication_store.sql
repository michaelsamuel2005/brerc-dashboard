-- BRERC destination publication store -- migration 0001.
--
-- This database contains only generalised, publication-safe candidate state.
-- It must never receive source coordinates, comments, unapproved/raw place text, sensitivity
-- flags, source identifiers or credentials. The loader persists a separate,
-- domain-separated HMAC token when it needs to reconcile a source identity.
--
-- Apply with ON_ERROR_STOP enabled, after db/roles.sql. The whole migration is
-- transactional. A second invocation fails at the explicit version guard; it
-- never uses CREATE TABLE IF NOT EXISTS to reshape an existing installation.

BEGIN;

SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('brerc:destination-schema-migration', 0)
);

DO $loader_control_schema_trust$
DECLARE
    expected_owner oid;
    observed_owner oid;
BEGIN
    SELECT r.oid INTO expected_owner
    FROM pg_catalog.pg_roles AS r
    WHERE r.rolname = current_user;

    SELECT n.nspowner INTO observed_owner
    FROM pg_catalog.pg_namespace AS n
    WHERE n.nspname = 'loader_control';

    IF NOT FOUND THEN
        EXECUTE pg_catalog.format(
            'CREATE SCHEMA loader_control AUTHORIZATION %I',
            current_user
        );
    ELSIF observed_owner <> expected_owner THEN
        RAISE EXCEPTION
            'loader_control exists under an unexpected owner; refusing migration';
    ELSIF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS n
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(n.nspacl, pg_catalog.acldefault('n', n.nspowner))
        ) AS privilege
        WHERE n.nspname = 'loader_control'
          AND privilege.privilege_type = 'CREATE'
          AND privilege.grantee <> n.nspowner
    ) THEN
        RAISE EXCEPTION
            'loader_control grants CREATE to a non-owner; refusing migration';
    END IF;
END
$loader_control_schema_trust$;

DO $migration_guard$
BEGIN
    IF pg_catalog.to_regclass('loader_control.schema_migration') IS NULL THEN
        EXECUTE $ddl$
            CREATE TABLE loader_control.schema_migration (
                migration_version integer PRIMARY KEY,
                migration_key text NOT NULL UNIQUE,
                migration_name text NOT NULL,
                installed_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
                installed_by name NOT NULL DEFAULT current_user,
                CONSTRAINT schema_migration_positive_version CHECK (migration_version > 0),
                CONSTRAINT schema_migration_key_not_blank CHECK (btrim(migration_key) <> ''),
                CONSTRAINT schema_migration_name_not_blank CHECK (btrim(migration_name) <> '')
            )
        $ddl$;
    ELSIF EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 1
           OR migration_key = '0001_publication_store'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration 0001_publication_store is already applied; refusing to re-run';
    ELSIF EXISTS (SELECT 1 FROM loader_control.schema_migration) THEN
        RAISE EXCEPTION
            'BRERC migration history is non-empty but migration 0001 is absent; refusing out-of-order application';
    ELSE
        RAISE EXCEPTION
            'loader_control.schema_migration exists without history; refusing an unversioned installation';
    END IF;
END
$migration_guard$;

DO $required_roles$
DECLARE
    required_role text;
    role_row record;
BEGIN
    FOREACH required_role IN ARRAY ARRAY[
        'brerc_loader',
        'brerc_api',
        'brerc_martin',
        'brerc_monitor'
    ]
    LOOP
        SELECT
            oid,
            rolcanlogin,
            rolinherit,
            rolsuper,
            rolcreatedb,
            rolcreaterole,
            rolreplication,
            rolbypassrls
        INTO role_row
        FROM pg_catalog.pg_roles
        WHERE rolname = required_role;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'required NOLOGIN group role % is absent; run db/roles.sql first',
                required_role;
        END IF;
        IF role_row.rolcanlogin
            OR role_row.rolinherit
            OR role_row.rolsuper
            OR role_row.rolcreatedb
            OR role_row.rolcreaterole
            OR role_row.rolreplication
            OR role_row.rolbypassrls
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members
                WHERE member = role_row.oid
            )
        THEN
            RAISE EXCEPTION
                'required group role % has unsafe direct or inherited privileges',
                required_role;
        END IF;
    END LOOP;
END
$required_roles$;

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;

DO $postgis_location$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension AS e
        JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
        WHERE e.extname = 'postgis'
          AND n.nspname = 'public'
    ) THEN
        RAISE EXCEPTION
            'PostGIS must be installed in schema public for this reviewed migration';
    END IF;
END
$postgis_location$;

CREATE SCHEMA loader_stage;
CREATE SCHEMA publication;
CREATE SCHEMA serve;

COMMENT ON SCHEMA loader_control IS
    'Private loader state, release manifests and structurally safe operational audit data.';
COMMENT ON SCHEMA loader_stage IS
    'Private, job-scoped candidate state. Never granted to API, Martin or monitoring roles.';
COMMENT ON SCHEMA publication IS
    'Immutable, release-scoped public-safe data. Accessed publicly only through serve views.';
COMMENT ON SCHEMA serve IS
    'Read-only active-release views for FastAPI, Martin and safe ETL monitoring.';

-- The deployment UUID is generated once for this destination installation and
-- pinned independently in the protected loader configuration. It is a guard
-- against connecting to the wrong logical environment; it is not BRERC
-- approval or cryptographic host authentication. A restored clone must receive
-- a new controlled UUID before any loader credential is enabled.
CREATE TABLE loader_control.deployment_identity (
    singleton boolean PRIMARY KEY DEFAULT true,
    environment_id uuid NOT NULL UNIQUE DEFAULT pg_catalog.gen_random_uuid(),
    database_name name NOT NULL DEFAULT current_database(),
    created_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT deployment_identity_singleton CHECK (singleton),
    CONSTRAINT deployment_identity_uuid_not_nil CHECK (
        environment_id <> '00000000-0000-0000-0000-000000000000'::uuid
    )
);

INSERT INTO loader_control.deployment_identity DEFAULT VALUES;

COMMENT ON TABLE loader_control.deployment_identity IS
    'One installation-specific destination UUID pinned by protected loader configuration.';

-- The source-state row is the serialisation point for activation. A watermark
-- token is an HMAC of the canonical source key, never the source key itself.
CREATE TABLE loader_control.source_state (
    source_id text PRIMARY KEY,
    active_release_id uuid,
    last_successful_modified_date date,
    last_successful_modified_key_token bytea,
    last_source_snapshot_at timestamp with time zone,
    last_source_row_count bigint,
    last_full_reconciliation_at timestamp with time zone,
    compatibility_sha256 text,
    updated_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT source_state_id_not_blank CHECK (btrim(source_id) <> ''),
    CONSTRAINT source_state_watermark_pair CHECK (
        (last_successful_modified_date IS NULL)
        = (last_successful_modified_key_token IS NULL)
    ),
    CONSTRAINT source_state_watermark_token_length CHECK (
        last_successful_modified_key_token IS NULL
        OR octet_length(last_successful_modified_key_token) = 32
    ),
    CONSTRAINT source_state_count_nonnegative CHECK (
        last_source_row_count IS NULL OR last_source_row_count >= 0
    ),
    CONSTRAINT source_state_compatibility_digest CHECK (
        compatibility_sha256 IS NULL
        OR compatibility_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE loader_control.etl_job (
    job_id uuid PRIMARY KEY,
    source_id text NOT NULL REFERENCES loader_control.source_state(source_id),
    attempt integer NOT NULL DEFAULT 1,
    load_mode text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    base_release_id uuid,
    result_release_id uuid,
    reused_active_release boolean NOT NULL DEFAULT false,
    started_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    finished_at timestamp with time zone,
    failure_code text,
    source_rows_seen bigint,
    candidate_rows bigint,
    rows_withheld bigint,
    created_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT etl_job_source_job_unique UNIQUE (source_id, job_id),
    CONSTRAINT etl_job_result_unique UNIQUE (job_id, result_release_id),
    CONSTRAINT etl_job_attempt_positive CHECK (attempt > 0),
    CONSTRAINT etl_job_load_mode CHECK (load_mode IN ('initial', 'incremental')),
    CONSTRAINT etl_job_base_matches_mode CHECK (
        (load_mode = 'initial' AND base_release_id IS NULL)
        OR (load_mode = 'incremental' AND base_release_id IS NOT NULL)
    ),
    CONSTRAINT etl_job_status CHECK (
        status IN (
            'queued', 'preflight', 'extracting', 'transforming',
            'reconciling', 'validated', 'activating',
            'succeeded', 'failed', 'cancelled'
        )
    ),
    CONSTRAINT etl_job_failure_code CHECK (
        failure_code IS NULL OR failure_code IN (
            'LOADER_FAILED',
            'LOADER_CONFIGURATION_INVALID',
            'INCREMENTAL_SOURCE_CONTRACT_BLOCKED',
            'LOADER_COORDINATOR_UNAVAILABLE',
            'LOADER_EXECUTION_FAILED',
            'LOADER_POLICY_INVALID',
            'LOADER_RELEASE_BLOCKED',
            'LOADER_TARGET_CONNECTION_FAILED',
            'LOADER_TARGET_PROTOCOL_INVALID',
            'LOADER_ALREADY_RUNNING',
            'LOADER_CANDIDATE_INVALID',
            'LOADER_SOURCE_COUNT_REJECTED',
            'LOADER_CLEANUP_FAILED',
            'LOADER_CLEANUP_PENDING',
            'WORKER_LOST'
        )
    ),
    CONSTRAINT etl_job_counts_nonnegative CHECK (
        (source_rows_seen IS NULL OR source_rows_seen >= 0)
        AND (candidate_rows IS NULL OR candidate_rows >= 0)
        AND (rows_withheld IS NULL OR rows_withheld >= 0)
    ),
    CONSTRAINT etl_job_finished_state CHECK (
        (status IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)
    ),
    CONSTRAINT etl_job_failure_state CHECK (
        (status = 'failed' AND failure_code IS NOT NULL)
        OR (status <> 'failed' AND failure_code IS NULL)
    ),
    CONSTRAINT etl_job_success_result CHECK (
        (status = 'succeeded') = (result_release_id IS NOT NULL)
    ),
    CONSTRAINT etl_job_reuse_state CHECK (
        NOT reused_active_release OR status = 'succeeded'
    ),
    CONSTRAINT etl_job_time_order CHECK (
        (started_at IS NULL OR started_at >= created_at)
        AND (heartbeat_at IS NULL OR started_at IS NOT NULL)
        AND (finished_at IS NULL OR started_at IS NOT NULL)
        AND (finished_at IS NULL OR finished_at >= started_at)
    )
);

CREATE UNIQUE INDEX etl_job_one_open_per_source
    ON loader_control.etl_job (source_id)
    WHERE status IN (
        'queued', 'preflight', 'extracting', 'transforming',
        'reconciling', 'validated', 'activating'
    );
CREATE INDEX etl_job_status_created_idx
    ON loader_control.etl_job (status, created_at DESC);

-- The loader updates bounded progress while a job is open. Once a terminal
-- state is visible to monitoring, its status, counts and timestamps are an
-- immutable audit record. Lifecycle SECURITY DEFINER functions move an open
-- job into that terminal state but never need to alter it afterwards.
CREATE FUNCTION loader_control.guard_terminal_etl_job_update()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_terminal_etl_job_update$
BEGIN
    IF OLD.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'terminal ETL job audit rows are immutable';
    END IF;
    RETURN NEW;
END
$guard_terminal_etl_job_update$;

CREATE TRIGGER etl_job_terminal_update_guard
BEFORE UPDATE ON loader_control.etl_job
FOR EACH ROW EXECUTE FUNCTION loader_control.guard_terminal_etl_job_update();

CREATE TABLE loader_control.release (
    release_id uuid PRIMARY KEY,
    source_id text NOT NULL,
    job_id uuid NOT NULL,
    base_release_id uuid,
    load_mode text NOT NULL,
    status text NOT NULL DEFAULT 'candidate',
    cleanup_pending boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    validated_at timestamp with time zone,
    activated_at timestamp with time zone,
    retired_at timestamp with time zone,
    CONSTRAINT release_source_release_unique UNIQUE (source_id, release_id),
    CONSTRAINT release_job_unique UNIQUE (job_id),
    CONSTRAINT release_job_source_fk FOREIGN KEY (source_id, job_id)
        REFERENCES loader_control.etl_job (source_id, job_id),
    CONSTRAINT release_load_mode CHECK (load_mode IN ('initial', 'incremental')),
    CONSTRAINT release_base_matches_mode CHECK (
        (load_mode = 'initial' AND base_release_id IS NULL)
        OR (load_mode = 'incremental' AND base_release_id IS NOT NULL)
    ),
    CONSTRAINT release_status CHECK (
        status IN ('candidate', 'validated', 'active', 'retired', 'failed', 'discarded')
    ),
    CONSTRAINT release_cleanup_pending_state CHECK (
        NOT cleanup_pending OR status IN ('failed', 'discarded')
    ),
    CONSTRAINT release_validated_time CHECK (
        validated_at IS NULL OR validated_at >= created_at
    ),
    CONSTRAINT release_activated_time CHECK (
        activated_at IS NULL
        OR (validated_at IS NOT NULL AND activated_at >= validated_at)
    ),
    CONSTRAINT release_retired_time CHECK (
        retired_at IS NULL
        OR (activated_at IS NOT NULL AND retired_at >= activated_at)
    ),
    CONSTRAINT release_active_has_activation CHECK (
        (status IN ('active', 'retired')) = (activated_at IS NOT NULL)
    ),
    CONSTRAINT release_retired_has_retirement CHECK (
        (status = 'retired') = (retired_at IS NOT NULL)
    )
);

ALTER TABLE loader_control.release
    ADD CONSTRAINT release_base_same_source_fk
    FOREIGN KEY (source_id, base_release_id)
    REFERENCES loader_control.release (source_id, release_id);

ALTER TABLE loader_control.etl_job
    ADD CONSTRAINT etl_job_base_release_fk
    FOREIGN KEY (source_id, base_release_id)
    REFERENCES loader_control.release (source_id, release_id);

ALTER TABLE loader_control.etl_job
    ADD CONSTRAINT etl_job_result_release_fk
    FOREIGN KEY (source_id, result_release_id)
    REFERENCES loader_control.release (source_id, release_id);

ALTER TABLE loader_control.source_state
    ADD CONSTRAINT source_state_active_release_fk
    FOREIGN KEY (source_id, active_release_id)
    REFERENCES loader_control.release (source_id, release_id);

CREATE UNIQUE INDEX release_one_active_per_source
    ON loader_control.release (source_id)
    WHERE status = 'active';
CREATE INDEX release_source_created_idx
    ON loader_control.release (source_id, created_at DESC);

-- The immutable release manifest binds the source snapshot, approvals, code,
-- watermarks, counts and stored candidate digest. The loader has INSERT and
-- SELECT, but deliberately receives no UPDATE or DELETE privilege on it.
CREATE TABLE loader_control.release_manifest (
    release_id uuid PRIMARY KEY REFERENCES loader_control.release(release_id),
    source_snapshot_at timestamp with time zone NOT NULL,
    lower_modified_date date,
    lower_modified_key_token bytea,
    upper_modified_date date,
    upper_modified_key_token bytea,
    source_contract_version text NOT NULL,
    source_contract_sha256 text NOT NULL,
    observed_view_definition_sha256 text NOT NULL,
    observed_view_identity_sha256 text NOT NULL,
    projection_version text NOT NULL,
    projection_sha256 text NOT NULL,
    publication_policy_version text NOT NULL,
    publication_policy_sha256 text NOT NULL,
    policy_approval_sha256 text NOT NULL,
    suppression_mode text NOT NULL,
    min_records_per_cell integer NOT NULL,
    etl_version text NOT NULL,
    compatibility_sha256 text NOT NULL,
    species_dictionary_sha256 text NOT NULL,
    species_dictionary_artifact_sha256 text NOT NULL,
    sensitivity_snapshot_sha256 text NOT NULL,
    source_row_count bigint NOT NULL,
    source_inventory_count bigint NOT NULL,
    delta_row_count bigint NOT NULL,
    eligible_pre_suppression_count bigint NOT NULL,
    transform_withheld_count bigint NOT NULL,
    suppression_withheld_count bigint NOT NULL,
    published_basis_count bigint NOT NULL,
    species_count bigint NOT NULL,
    cell_count bigint NOT NULL,
    species_year_count bigint NOT NULL,
    public_record_count bigint NOT NULL,
    source_result_sha256 text NOT NULL,
    candidate_sha256 text NOT NULL,
    database_sha256 text NOT NULL,
    recorded_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT release_manifest_lower_watermark_pair CHECK (
        (lower_modified_date IS NULL) = (lower_modified_key_token IS NULL)
    ),
    CONSTRAINT release_manifest_upper_watermark_pair CHECK (
        (upper_modified_date IS NULL) = (upper_modified_key_token IS NULL)
    ),
    CONSTRAINT release_manifest_watermark_token_lengths CHECK (
        (lower_modified_key_token IS NULL OR octet_length(lower_modified_key_token) = 32)
        AND (upper_modified_key_token IS NULL OR octet_length(upper_modified_key_token) = 32)
    ),
    CONSTRAINT release_manifest_watermark_order CHECK (
        lower_modified_date IS NULL
        OR upper_modified_date IS NULL
        OR lower_modified_date <= upper_modified_date
    ),
    CONSTRAINT release_manifest_versions_not_blank CHECK (
        btrim(source_contract_version) <> ''
        AND btrim(projection_version) <> ''
        AND btrim(publication_policy_version) <> ''
        AND btrim(etl_version) <> ''
    ),
    CONSTRAINT release_manifest_suppression_policy CHECK (
        (suppression_mode = 'none' AND min_records_per_cell = 1)
        OR (
            suppression_mode = 'minimum-count'
            AND min_records_per_cell >= 2
        )
    ),
    CONSTRAINT release_manifest_digest_shapes CHECK (
        source_contract_sha256 ~ '^[0-9a-f]{64}$'
        AND observed_view_definition_sha256 ~ '^[0-9a-f]{64}$'
        AND observed_view_identity_sha256 ~ '^[0-9a-f]{64}$'
        AND projection_sha256 ~ '^[0-9a-f]{64}$'
        AND publication_policy_sha256 ~ '^[0-9a-f]{64}$'
        AND policy_approval_sha256 ~ '^[0-9a-f]{64}$'
        AND compatibility_sha256 ~ '^[0-9a-f]{64}$'
        AND species_dictionary_sha256 ~ '^[0-9a-f]{64}$'
        AND species_dictionary_artifact_sha256 ~ '^[0-9a-f]{64}$'
        AND sensitivity_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        AND source_result_sha256 ~ '^[0-9a-f]{64}$'
        AND candidate_sha256 ~ '^[0-9a-f]{64}$'
        AND database_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT release_manifest_counts_nonnegative CHECK (
        source_row_count >= 0
        AND source_inventory_count >= 0
        AND delta_row_count >= 0
        AND eligible_pre_suppression_count >= 0
        AND transform_withheld_count >= 0
        AND suppression_withheld_count >= 0
        AND published_basis_count >= 0
        AND species_count >= 0
        AND cell_count >= 0
        AND species_year_count >= 0
        AND public_record_count >= 0
    ),
    CONSTRAINT release_manifest_source_reconciles CHECK (
        source_inventory_count = source_row_count
        AND source_row_count = eligible_pre_suppression_count + transform_withheld_count
    ),
    CONSTRAINT release_manifest_publication_reconciles CHECK (
        eligible_pre_suppression_count
        = published_basis_count + suppression_withheld_count
    ),
    CONSTRAINT release_manifest_candidate_matches_database CHECK (
        candidate_sha256 = database_sha256
    )
);

CREATE TABLE loader_control.withheld_summary (
    release_id uuid NOT NULL REFERENCES loader_control.release(release_id),
    reason_code text NOT NULL,
    row_count bigint NOT NULL,
    PRIMARY KEY (release_id, reason_code),
    CONSTRAINT withheld_summary_reason CHECK (
        reason_code ~ '^[a-z][a-z0-9-]{1,63}$'
    ),
    CONSTRAINT withheld_summary_count_positive CHECK (row_count > 0)
);

CREATE TABLE loader_control.etl_job_event (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES loader_control.etl_job(job_id),
    stage text NOT NULL,
    event_code text NOT NULL,
    observed_count bigint,
    duration_ms bigint,
    retry_number integer,
    occurred_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT etl_job_event_stage CHECK (
        stage IN (
            'queued', 'preflight', 'extracting', 'transforming',
            'reconciling', 'validated', 'activating', 'terminal'
        )
    ),
    CONSTRAINT etl_job_event_code CHECK (
        event_code ~ '^[A-Z][A-Z0-9_]{2,63}$'
    ),
    CONSTRAINT etl_job_event_metrics_nonnegative CHECK (
        (observed_count IS NULL OR observed_count >= 0)
        AND (duration_ms IS NULL OR duration_ms >= 0)
        AND (retry_number IS NULL OR retry_number >= 0)
    )
);
CREATE INDEX etl_job_event_job_time_idx
    ON loader_control.etl_job_event (job_id, occurred_at, event_id);

-- Transactional outbox: activation/failure commits the notification request;
-- a separate delivery worker changes only delivery state. destination_key is a
-- configuration alias, not an email address or secret.
CREATE TABLE loader_control.notification_outbox (
    notification_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES loader_control.etl_job(job_id),
    release_id uuid,
    event_type text NOT NULL,
    destination_key text NOT NULL,
    failure_code text,
    status text NOT NULL DEFAULT 'pending',
    attempt_count integer NOT NULL DEFAULT 0,
    available_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    locked_at timestamp with time zone,
    delivered_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT notification_outbox_job_event_unique UNIQUE (job_id, event_type),
    CONSTRAINT notification_outbox_job_result_fk
        FOREIGN KEY (job_id, release_id)
        REFERENCES loader_control.etl_job (job_id, result_release_id),
    CONSTRAINT notification_outbox_event_type CHECK (
        event_type IN ('etl_succeeded', 'etl_failed')
    ),
    CONSTRAINT notification_outbox_destination CHECK (
        destination_key ~ '^[a-z][a-z0-9_-]{2,63}$'
    ),
    CONSTRAINT notification_outbox_failure_code CHECK (
        (event_type = 'etl_failed'
            AND failure_code IS NOT NULL
            AND release_id IS NULL
            AND failure_code IN (
                'LOADER_FAILED',
                'LOADER_CONFIGURATION_INVALID',
                'INCREMENTAL_SOURCE_CONTRACT_BLOCKED',
                'LOADER_COORDINATOR_UNAVAILABLE',
                'LOADER_EXECUTION_FAILED',
                'LOADER_POLICY_INVALID',
                'LOADER_RELEASE_BLOCKED',
                'LOADER_TARGET_CONNECTION_FAILED',
                'LOADER_TARGET_PROTOCOL_INVALID',
                'LOADER_ALREADY_RUNNING',
                'LOADER_CANDIDATE_INVALID',
                'LOADER_SOURCE_COUNT_REJECTED',
                'LOADER_CLEANUP_FAILED',
                'LOADER_CLEANUP_PENDING',
                'WORKER_LOST'
            ))
        OR (
            event_type = 'etl_succeeded'
            AND failure_code IS NULL
            AND release_id IS NOT NULL
        )
    ),
    CONSTRAINT notification_outbox_status CHECK (
        status IN ('pending', 'delivering', 'delivered', 'delivery_failed')
    ),
    CONSTRAINT notification_outbox_attempts_nonnegative CHECK (attempt_count >= 0),
    CONSTRAINT notification_outbox_delivery_state CHECK (
        (status = 'delivered') = (delivered_at IS NOT NULL)
    )
);
CREATE INDEX notification_outbox_delivery_idx
    ON loader_control.notification_outbox (status, available_at)
    WHERE status IN ('pending', 'delivery_failed');
CREATE UNIQUE INDEX notification_outbox_success_release_idx
    ON loader_control.notification_outbox (release_id, event_type)
    WHERE event_type = 'etl_succeeded';

-- One private, pseudonymous disposition per record and immutable release.
-- Candidate ledgers are completed before activation, so a failed activation
-- cannot partly mutate the active release's reconciliation state. Every
-- location here is already generalised. This table is never granted to API,
-- Martin or monitor roles.
CREATE TABLE loader_control.source_disposition (
    release_id uuid NOT NULL REFERENCES loader_control.release(release_id),
    source_key_token bytea NOT NULL,
    input_fingerprint bytea NOT NULL,
    disposition text NOT NULL,
    withheld_reason text,
    species_id text,
    scientific_name text,
    common_name text,
    record_grid_ref text,
    record_precision_metres integer,
    cell_id text,
    cell_precision_metres integer,
    min_easting integer,
    min_northing integer,
    max_easting integer,
    max_northing integer,
    record_year smallint,
    public_record_id text,
    place text,
    abundance text,
    record_type text,
    verified_status text,
    source_label text,
    recorded_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (release_id, source_key_token),
    CONSTRAINT source_disposition_token_length CHECK (octet_length(source_key_token) = 32),
    CONSTRAINT source_disposition_fingerprint_length CHECK (octet_length(input_fingerprint) = 32),
    CONSTRAINT source_disposition_kind CHECK (
        disposition IN ('eligible', 'withheld', 'suppressed')
    ),
    CONSTRAINT source_disposition_reason_shape CHECK (
        withheld_reason IS NULL OR withheld_reason ~ '^[a-z][a-z0-9-]{1,63}$'
    ),
    CONSTRAINT source_disposition_verified_status CHECK (
        verified_status IS NULL
        OR verified_status IN ('accepted', 'unconfirmed', 'rejected', 'unknown')
    ),
    CONSTRAINT source_disposition_safe_grid_refs CHECK (
        (record_grid_ref IS NULL OR record_grid_ref ~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$')
        AND (cell_id IS NULL OR cell_id ~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$')
    ),
    CONSTRAINT source_disposition_safe_resolutions CHECK (
        (record_precision_metres IS NULL OR record_precision_metres IN (100, 1000, 10000))
        AND (cell_precision_metres IS NULL OR cell_precision_metres IN (100, 1000, 10000))
    ),
    CONSTRAINT source_disposition_safe_bounds CHECK (
        (
            min_easting IS NULL
            AND min_northing IS NULL
            AND max_easting IS NULL
            AND max_northing IS NULL
        )
        OR
        (
            cell_precision_metres IS NOT NULL
            AND min_easting BETWEEN 0 AND 699999
            AND min_northing BETWEEN 0 AND 1299999
            AND max_easting BETWEEN 1 AND 700000
            AND max_northing BETWEEN 1 AND 1300000
            AND max_easting - min_easting = cell_precision_metres
            AND max_northing - min_northing = cell_precision_metres
            AND pg_catalog.mod(min_easting, cell_precision_metres) = 0
            AND pg_catalog.mod(min_northing, cell_precision_metres) = 0
        )
    ),
    CONSTRAINT source_disposition_public_id CHECK (
        public_record_id IS NULL OR public_record_id ~ '^[0-9a-f]{32}$'
    ),
    CONSTRAINT source_disposition_year CHECK (
        record_year IS NULL OR record_year BETWEEN 1500 AND 2200
    ),
    CONSTRAINT source_disposition_complete CHECK (
        (
            disposition = 'eligible'
            AND withheld_reason IS NULL
            AND species_id IS NOT NULL AND btrim(species_id) <> ''
            AND scientific_name IS NOT NULL AND btrim(scientific_name) <> ''
            AND record_grid_ref IS NOT NULL
            AND record_precision_metres IS NOT NULL
            AND cell_id IS NOT NULL
            AND cell_precision_metres IS NOT NULL
            AND min_easting IS NOT NULL
            AND min_northing IS NOT NULL
            AND max_easting IS NOT NULL
            AND max_northing IS NOT NULL
            AND cell_precision_metres >= record_precision_metres
            AND record_year IS NOT NULL
            AND public_record_id IS NOT NULL
        )
        OR
        (
            disposition = 'suppressed'
            AND withheld_reason = 'suppressed-sparse-cell'
            AND species_id IS NOT NULL AND btrim(species_id) <> ''
            AND scientific_name IS NULL
            AND common_name IS NULL
            AND record_grid_ref IS NULL
            AND record_precision_metres IS NULL
            AND cell_id IS NOT NULL
            AND cell_precision_metres IS NOT NULL
            AND min_easting IS NOT NULL
            AND min_northing IS NOT NULL
            AND max_easting IS NOT NULL
            AND max_northing IS NOT NULL
            AND record_year IS NOT NULL
            AND public_record_id IS NULL
            AND place IS NULL
            AND abundance IS NULL
            AND record_type IS NULL
            AND verified_status IS NULL
            AND source_label IS NULL
        )
        OR
        (
            disposition = 'withheld'
            AND withheld_reason IS NOT NULL
            AND withheld_reason <> 'suppressed-sparse-cell'
            AND species_id IS NULL
            AND scientific_name IS NULL
            AND common_name IS NULL
            AND record_grid_ref IS NULL
            AND record_precision_metres IS NULL
            AND cell_id IS NULL
            AND cell_precision_metres IS NULL
            AND min_easting IS NULL
            AND min_northing IS NULL
            AND max_easting IS NULL
            AND max_northing IS NULL
            AND record_year IS NULL
            AND public_record_id IS NULL
            AND place IS NULL
            AND abundance IS NULL
            AND record_type IS NULL
            AND verified_status IS NULL
            AND source_label IS NULL
        )
    )
);
CREATE INDEX source_disposition_cohort_idx
    ON loader_control.source_disposition (
        release_id, species_id, record_year, cell_id, cell_precision_metres
    )
    WHERE disposition IN ('eligible', 'suppressed');
CREATE UNIQUE INDEX source_disposition_public_record_idx
    ON loader_control.source_disposition (release_id, public_record_id)
    WHERE disposition = 'eligible';

-- Complete key inventory from one source snapshot. Every row carries a digest
-- of the canonical projected source values; key-only reconciliation is not
-- accepted by this publication protocol.
CREATE TABLE loader_stage.source_inventory (
    job_id uuid NOT NULL REFERENCES loader_control.etl_job(job_id) ON DELETE CASCADE,
    source_key_token bytea NOT NULL,
    input_fingerprint bytea NOT NULL,
    observed_modified_date date,
    PRIMARY KEY (job_id, source_key_token),
    CONSTRAINT source_inventory_token_length CHECK (octet_length(source_key_token) = 32),
    CONSTRAINT source_inventory_fingerprint_length CHECK (
        octet_length(input_fingerprint) = 32
    )
);
CREATE INDEX source_inventory_token_idx
    ON loader_stage.source_inventory (source_key_token);

-- Idempotent delta: a retry may write the same primary key only when the
-- loader first proves the stored fingerprint and values are identical.
CREATE TABLE loader_stage.disposition_delta (
    job_id uuid NOT NULL REFERENCES loader_control.etl_job(job_id) ON DELETE CASCADE,
    source_key_token bytea NOT NULL,
    action text NOT NULL,
    input_fingerprint bytea,
    withheld_reason text,
    species_id text,
    scientific_name text,
    common_name text,
    record_grid_ref text,
    record_precision_metres integer,
    cell_id text,
    cell_precision_metres integer,
    min_easting integer,
    min_northing integer,
    max_easting integer,
    max_northing integer,
    record_year smallint,
    public_record_id text,
    place text,
    abundance text,
    record_type text,
    verified_status text,
    source_label text,
    PRIMARY KEY (job_id, source_key_token),
    CONSTRAINT disposition_delta_token_length CHECK (octet_length(source_key_token) = 32),
    CONSTRAINT disposition_delta_action CHECK (
        action IN ('upsert', 'withhold', 'suppress', 'delete')
    ),
    CONSTRAINT disposition_delta_fingerprint_length CHECK (
        input_fingerprint IS NULL OR octet_length(input_fingerprint) = 32
    ),
    CONSTRAINT disposition_delta_reason_shape CHECK (
        withheld_reason IS NULL OR withheld_reason ~ '^[a-z][a-z0-9-]{1,63}$'
    ),
    CONSTRAINT disposition_delta_verified_status CHECK (
        verified_status IS NULL
        OR verified_status IN ('accepted', 'unconfirmed', 'rejected', 'unknown')
    ),
    CONSTRAINT disposition_delta_safe_grid_refs CHECK (
        (record_grid_ref IS NULL OR record_grid_ref ~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$')
        AND (cell_id IS NULL OR cell_id ~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$')
    ),
    CONSTRAINT disposition_delta_safe_resolutions CHECK (
        (record_precision_metres IS NULL OR record_precision_metres IN (100, 1000, 10000))
        AND (cell_precision_metres IS NULL OR cell_precision_metres IN (100, 1000, 10000))
    ),
    CONSTRAINT disposition_delta_safe_bounds CHECK (
        (
            min_easting IS NULL
            AND min_northing IS NULL
            AND max_easting IS NULL
            AND max_northing IS NULL
        )
        OR
        (
            cell_precision_metres IS NOT NULL
            AND min_easting BETWEEN 0 AND 699999
            AND min_northing BETWEEN 0 AND 1299999
            AND max_easting BETWEEN 1 AND 700000
            AND max_northing BETWEEN 1 AND 1300000
            AND max_easting - min_easting = cell_precision_metres
            AND max_northing - min_northing = cell_precision_metres
            AND pg_catalog.mod(min_easting, cell_precision_metres) = 0
            AND pg_catalog.mod(min_northing, cell_precision_metres) = 0
        )
    ),
    CONSTRAINT disposition_delta_public_id CHECK (
        public_record_id IS NULL OR public_record_id ~ '^[0-9a-f]{32}$'
    ),
    CONSTRAINT disposition_delta_year CHECK (
        record_year IS NULL OR record_year BETWEEN 1500 AND 2200
    ),
    CONSTRAINT disposition_delta_complete CHECK (
        (
            action = 'upsert'
            AND input_fingerprint IS NOT NULL
            AND withheld_reason IS NULL
            AND species_id IS NOT NULL AND btrim(species_id) <> ''
            AND scientific_name IS NOT NULL AND btrim(scientific_name) <> ''
            AND record_grid_ref IS NOT NULL
            AND record_precision_metres IS NOT NULL
            AND cell_id IS NOT NULL
            AND cell_precision_metres IS NOT NULL
            AND min_easting IS NOT NULL
            AND min_northing IS NOT NULL
            AND max_easting IS NOT NULL
            AND max_northing IS NOT NULL
            AND cell_precision_metres >= record_precision_metres
            AND record_year IS NOT NULL
            AND public_record_id IS NOT NULL
        )
        OR
        (
            action = 'suppress'
            AND input_fingerprint IS NOT NULL
            AND withheld_reason = 'suppressed-sparse-cell'
            AND species_id IS NOT NULL AND btrim(species_id) <> ''
            AND scientific_name IS NULL
            AND common_name IS NULL
            AND record_grid_ref IS NULL
            AND record_precision_metres IS NULL
            AND cell_id IS NOT NULL
            AND cell_precision_metres IS NOT NULL
            AND min_easting IS NOT NULL
            AND min_northing IS NOT NULL
            AND max_easting IS NOT NULL
            AND max_northing IS NOT NULL
            AND record_year IS NOT NULL
            AND public_record_id IS NULL
            AND place IS NULL
            AND abundance IS NULL
            AND record_type IS NULL
            AND verified_status IS NULL
            AND source_label IS NULL
        )
        OR
        (
            action = 'withhold'
            AND input_fingerprint IS NOT NULL
            AND withheld_reason IS NOT NULL
            AND withheld_reason <> 'suppressed-sparse-cell'
            AND species_id IS NULL
            AND scientific_name IS NULL
            AND common_name IS NULL
            AND record_grid_ref IS NULL
            AND record_precision_metres IS NULL
            AND cell_id IS NULL
            AND cell_precision_metres IS NULL
            AND min_easting IS NULL
            AND min_northing IS NULL
            AND max_easting IS NULL
            AND max_northing IS NULL
            AND record_year IS NULL
            AND public_record_id IS NULL
            AND place IS NULL
            AND abundance IS NULL
            AND record_type IS NULL
            AND verified_status IS NULL
            AND source_label IS NULL
        )
        OR
        (
            action = 'delete'
            AND input_fingerprint IS NULL
            AND withheld_reason IS NULL
            AND species_id IS NULL
            AND scientific_name IS NULL
            AND common_name IS NULL
            AND record_grid_ref IS NULL
            AND record_precision_metres IS NULL
            AND cell_id IS NULL
            AND cell_precision_metres IS NULL
            AND min_easting IS NULL
            AND min_northing IS NULL
            AND max_easting IS NULL
            AND max_northing IS NULL
            AND record_year IS NULL
            AND public_record_id IS NULL
            AND place IS NULL
            AND abundance IS NULL
            AND record_type IS NULL
            AND verified_status IS NULL
            AND source_label IS NULL
        )
    )
);
CREATE INDEX disposition_delta_action_idx
    ON loader_stage.disposition_delta (job_id, action);

CREATE TABLE loader_stage.reconciliation_result (
    job_id uuid NOT NULL REFERENCES loader_control.etl_job(job_id) ON DELETE CASCADE,
    check_code text NOT NULL,
    expected_count bigint NOT NULL,
    actual_count bigint NOT NULL,
    passed boolean NOT NULL,
    checked_at timestamp with time zone NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (job_id, check_code),
    CONSTRAINT reconciliation_result_code CHECK (
        check_code ~ '^[A-Z][A-Z0-9_]{2,63}$'
    ),
    CONSTRAINT reconciliation_result_counts_nonnegative CHECK (
        expected_count >= 0 AND actual_count >= 0
    ),
    CONSTRAINT reconciliation_result_truth CHECK (
        passed = (expected_count = actual_count)
    )
);

-- Release-scoped public-safe data. Candidate release rows are invisible until
-- source_state.active_release_id changes in the atomic activation transaction.
CREATE TABLE publication.public_release (
    release_id uuid PRIMARY KEY REFERENCES loader_control.release(release_id),
    source_data_as_of timestamp with time zone NOT NULL,
    publication_policy_version text NOT NULL,
    dataset_version text NOT NULL,
    suppression_mode text NOT NULL,
    min_records_per_cell integer NOT NULL,
    verification_available boolean NOT NULL,
    individual_records_available boolean NOT NULL,
    record_verification_available boolean NOT NULL,
    place_available boolean NOT NULL,
    abundance_available boolean NOT NULL,
    record_type_available boolean NOT NULL,
    public_source_label text NOT NULL,
    CONSTRAINT public_release_policy_not_blank CHECK (
        btrim(publication_policy_version) <> ''
    ),
    CONSTRAINT public_release_dataset_not_blank CHECK (btrim(dataset_version) <> ''),
    CONSTRAINT public_release_suppression_policy CHECK (
        (suppression_mode = 'none' AND min_records_per_cell = 1)
        OR (
            suppression_mode = 'minimum-count'
            AND min_records_per_cell >= 2
        )
    ),
    CONSTRAINT public_release_source_label_not_blank CHECK (btrim(public_source_label) <> ''),
    CONSTRAINT public_release_optional_rows_require_individual_records CHECK (
        individual_records_available
        OR NOT (
            record_verification_available
            OR place_available
            OR abundance_available
            OR record_type_available
        )
    ),
    CONSTRAINT public_release_row_verification_requires_aggregate_availability CHECK (
        NOT record_verification_available OR verification_available
    )
);

CREATE TABLE publication.public_species (
    release_id uuid NOT NULL REFERENCES publication.public_release(release_id),
    species_id text NOT NULL,
    scientific_name text NOT NULL,
    common_name text,
    taxon_group text,
    total_records bigint NOT NULL,
    first_year smallint NOT NULL,
    last_year smallint NOT NULL,
    PRIMARY KEY (release_id, species_id),
    CONSTRAINT public_species_id_not_blank CHECK (btrim(species_id) <> ''),
    CONSTRAINT public_species_scientific_name_not_blank CHECK (btrim(scientific_name) <> ''),
    -- The confirmed view contains taxa_nb, but the current reviewed safe
    -- projection/disposition does not. Fail closed until a later contract
    -- explicitly maps and approval-binds that field.
    CONSTRAINT public_species_taxon_group_deferred CHECK (taxon_group IS NULL),
    CONSTRAINT public_species_total_positive CHECK (total_records > 0),
    CONSTRAINT public_species_years CHECK (
        first_year BETWEEN 1500 AND 2200
        AND last_year BETWEEN 1500 AND 2200
        AND first_year <= last_year
    )
);
CREATE INDEX public_species_name_idx
    ON publication.public_species (release_id, scientific_name, species_id);
CREATE INDEX public_species_common_name_idx
    ON publication.public_species (release_id, common_name, species_id)
    WHERE common_name IS NOT NULL;

-- Deterministically convert a supported British National Grid cell reference
-- into its exact lower-left-aligned polygon. This gives the table CHECK a
-- database-level text-to-geometry parity gate; area and SRID alone would accept
-- a correctly sized square in the wrong place.
CREATE FUNCTION loader_control.bng_cell_polygon(
    grid_ref text,
    expected_precision integer
) RETURNS public.geometry
LANGUAGE plpgsql
IMMUTABLE
STRICT
PARALLEL SAFE
SET search_path = pg_catalog, public
AS $bng_cell_polygon$
DECLARE
    letters text;
    digits text;
    digit_pairs integer;
    actual_precision integer;
    first_letter integer;
    second_letter integer;
    easting_100km integer;
    northing_100km integer;
    x_min integer;
    y_min integer;
BEGIN
    IF grid_ref !~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$' THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'grid cell reference is outside the public contract';
    END IF;

    letters := pg_catalog.substr(grid_ref, 1, 2);
    digits := pg_catalog.substr(grid_ref, 3);
    digit_pairs := pg_catalog.length(digits) / 2;
    actual_precision := CASE digit_pairs
        WHEN 1 THEN 10000
        WHEN 2 THEN 1000
        WHEN 3 THEN 100
        ELSE NULL
    END;
    IF actual_precision IS DISTINCT FROM expected_precision THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'grid cell precision disagrees with its reference';
    END IF;

    first_letter := pg_catalog.ascii(pg_catalog.substr(letters, 1, 1))
        - pg_catalog.ascii('A');
    second_letter := pg_catalog.ascii(pg_catalog.substr(letters, 2, 1))
        - pg_catalog.ascii('A');
    IF first_letter > 7 THEN
        first_letter := first_letter - 1;
    END IF;
    IF second_letter > 7 THEN
        second_letter := second_letter - 1;
    END IF;

    easting_100km := pg_catalog.mod(first_letter - 2, 5) * 5
        + pg_catalog.mod(second_letter, 5);
    northing_100km := 19 - (first_letter / 5) * 5 - (second_letter / 5);
    IF easting_100km NOT BETWEEN 0 AND 6 OR northing_100km NOT BETWEEN 0 AND 12 THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'grid cell is outside the British National Grid extent';
    END IF;

    x_min := easting_100km * 100000
        + pg_catalog.substr(digits, 1, digit_pairs)::integer * actual_precision;
    y_min := northing_100km * 100000
        + pg_catalog.substr(digits, digit_pairs + 1, digit_pairs)::integer
            * actual_precision;

    RETURN public.ST_MakeEnvelope(
        x_min,
        y_min,
        x_min + actual_precision,
        y_min + actual_precision,
        27700
    );
END
$bng_cell_polygon$;

ALTER TABLE loader_control.source_disposition
    ADD CONSTRAINT source_disposition_cell_bounds_match_reference CHECK (
        cell_id IS NULL
        OR public.ST_Equals(
            loader_control.bng_cell_polygon(cell_id, cell_precision_metres),
            public.ST_MakeEnvelope(
                min_easting,
                min_northing,
                max_easting,
                max_northing,
                27700
            )
        )
    ),
    ADD CONSTRAINT source_disposition_record_inside_cell CHECK (
        disposition <> 'eligible'
        OR public.ST_CoveredBy(
            loader_control.bng_cell_polygon(record_grid_ref, record_precision_metres),
            loader_control.bng_cell_polygon(cell_id, cell_precision_metres)
        )
    );

ALTER TABLE loader_stage.disposition_delta
    ADD CONSTRAINT disposition_delta_cell_bounds_match_reference CHECK (
        cell_id IS NULL
        OR public.ST_Equals(
            loader_control.bng_cell_polygon(cell_id, cell_precision_metres),
            public.ST_MakeEnvelope(
                min_easting,
                min_northing,
                max_easting,
                max_northing,
                27700
            )
        )
    ),
    ADD CONSTRAINT disposition_delta_record_inside_cell CHECK (
        action <> 'upsert'
        OR public.ST_CoveredBy(
            loader_control.bng_cell_polygon(record_grid_ref, record_precision_metres),
            loader_control.bng_cell_polygon(cell_id, cell_precision_metres)
        )
    );

CREATE TABLE publication.public_distribution_cell (
    release_id uuid NOT NULL,
    species_id text NOT NULL,
    record_year smallint NOT NULL,
    cell_id text NOT NULL,
    precision_metres integer NOT NULL,
    record_count bigint NOT NULL,
    verified_count bigint,
    geom public.geometry(Polygon, 27700) NOT NULL,
    PRIMARY KEY (release_id, species_id, record_year, cell_id, precision_metres),
    CONSTRAINT public_distribution_cell_species_fk
        FOREIGN KEY (release_id, species_id)
        REFERENCES publication.public_species (release_id, species_id),
    CONSTRAINT public_distribution_cell_year CHECK (record_year BETWEEN 1500 AND 2200),
    CONSTRAINT public_distribution_cell_id CHECK (
        cell_id ~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$'
    ),
    CONSTRAINT public_distribution_cell_precision CHECK (
        precision_metres IN (100, 1000, 10000)
    ),
    CONSTRAINT public_distribution_cell_count CHECK (record_count > 0),
    CONSTRAINT public_distribution_cell_verified CHECK (
        verified_count IS NULL
        OR (verified_count >= 0 AND verified_count <= record_count)
    ),
    CONSTRAINT public_distribution_cell_geometry CHECK (
        public.ST_SRID(geom) = 27700
        AND public.ST_GeometryType(geom) = 'ST_Polygon'
        AND NOT public.ST_IsEmpty(geom)
        AND public.ST_IsValid(geom)
        AND abs(public.ST_Area(geom) - (precision_metres::double precision ^ 2)) < 0.01
        AND public.ST_Equals(
            geom,
            loader_control.bng_cell_polygon(cell_id, precision_metres)
        )
    )
);
CREATE INDEX public_distribution_cell_lookup_idx
    ON publication.public_distribution_cell (release_id, species_id, record_year);
CREATE INDEX public_distribution_cell_geom_idx
    ON publication.public_distribution_cell USING gist (geom);

CREATE TABLE publication.public_species_year (
    release_id uuid NOT NULL,
    species_id text NOT NULL,
    record_year smallint NOT NULL,
    record_count bigint NOT NULL,
    verified_count bigint,
    PRIMARY KEY (release_id, species_id, record_year),
    CONSTRAINT public_species_year_species_fk
        FOREIGN KEY (release_id, species_id)
        REFERENCES publication.public_species (release_id, species_id),
    CONSTRAINT public_species_year_year CHECK (record_year BETWEEN 1500 AND 2200),
    CONSTRAINT public_species_year_count CHECK (record_count > 0),
    CONSTRAINT public_species_year_verified CHECK (
        verified_count IS NULL
        OR (verified_count >= 0 AND verified_count <= record_count)
    )
);

-- This table remains empty while aggregate-only publication is approved. Its
-- columns exactly mirror the current public-record allow-list; there is no slot
-- for a source identifier, coordinates, comments or sensitivity markers.
CREATE TABLE publication.public_record (
    release_id uuid NOT NULL,
    public_record_id text NOT NULL,
    species_id text NOT NULL,
    scientific_name text NOT NULL,
    common_name text,
    grid_ref text NOT NULL,
    precision_metres integer NOT NULL,
    place text,
    record_year smallint NOT NULL,
    abundance text,
    record_type text,
    verified_status text,
    source_label text NOT NULL,
    PRIMARY KEY (release_id, public_record_id),
    CONSTRAINT public_record_species_fk
        FOREIGN KEY (release_id, species_id)
        REFERENCES publication.public_species (release_id, species_id),
    CONSTRAINT public_record_id_shape CHECK (public_record_id ~ '^[0-9a-f]{32}$'),
    CONSTRAINT public_record_scientific_name_not_blank CHECK (btrim(scientific_name) <> ''),
    CONSTRAINT public_record_grid_ref CHECK (
        grid_ref ~ '^[A-HJ-Z]{2}([0-9]{2}|[0-9]{4}|[0-9]{6})$'
    ),
    CONSTRAINT public_record_precision CHECK (precision_metres IN (100, 1000, 10000)),
    CONSTRAINT public_record_year CHECK (record_year BETWEEN 1500 AND 2200),
    CONSTRAINT public_record_verified_status CHECK (
        verified_status IS NULL
        OR verified_status IN ('accepted', 'unconfirmed', 'rejected', 'unknown')
    ),
    CONSTRAINT public_record_source_label_not_blank CHECK (btrim(source_label) <> '')
);
CREATE INDEX public_record_species_year_idx
    ON publication.public_record (release_id, species_id, record_year, public_record_id);

-- INSERT privilege is not authority to mutate an active release. Finalisation
-- first authorises exactly one candidate in this transaction. A statement-level
-- trigger revalidates candidate/job/lock once per INSERT, while a cheap RLS check
-- requires every inserted row to carry that authorised release ID. This avoids
-- both a per-row catalogue lookup and a five-million-row transition table.
CREATE FUNCTION loader_control.authorize_candidate_writes(candidate_release_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $authorize_candidate_writes$
DECLARE
    candidate_source_id text;
    candidate_release_status text;
    candidate_job_status text;
BEGIN
    SELECT r.source_id, r.status, j.status
    INTO candidate_source_id, candidate_release_status, candidate_job_status
    FROM loader_control.release AS r
    JOIN loader_control.etl_job AS j
      ON j.job_id = r.job_id
     AND j.source_id = r.source_id
    WHERE r.release_id = candidate_release_id;

    IF NOT FOUND
        OR candidate_release_status <> 'candidate'
        OR candidate_job_status <> 'reconciling'
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'durable release rows may be authorised only during candidate finalisation';
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
            MESSAGE = 'source session advisory lock is required for durable candidate inserts';
    END IF;

    PERFORM pg_catalog.set_config(
        'brerc.authorized_candidate_release',
        candidate_release_id::text,
        true
    );
    RETURN candidate_release_id;
END
$authorize_candidate_writes$;

CREATE FUNCTION loader_control.guard_candidate_release_insert()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_candidate_release_insert$
DECLARE
    configured_release_id text;
    candidate_release_id uuid;
    candidate_source_id text;
    candidate_release_status text;
    candidate_job_status text;
BEGIN
    configured_release_id := pg_catalog.current_setting(
        'brerc.authorized_candidate_release',
        true
    );
    IF configured_release_id IS NULL OR configured_release_id !~
        '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'durable candidate insert authority is absent';
    END IF;
    candidate_release_id := configured_release_id::uuid;

    SELECT r.source_id, r.status, j.status
    INTO candidate_source_id, candidate_release_status, candidate_job_status
    FROM loader_control.release AS r
    JOIN loader_control.etl_job AS j
      ON j.job_id = r.job_id
     AND j.source_id = r.source_id
    WHERE r.release_id = candidate_release_id;

    IF NOT FOUND
        OR candidate_release_status <> 'candidate'
        OR candidate_job_status <> 'reconciling'
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'durable release rows may be inserted only during candidate finalisation';
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
            MESSAGE = 'source session advisory lock is required for durable candidate inserts';
    END IF;

    RETURN NULL;
END
$guard_candidate_release_insert$;

CREATE TRIGGER release_manifest_candidate_insert
BEFORE INSERT ON loader_control.release_manifest
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER withheld_summary_candidate_insert
BEFORE INSERT ON loader_control.withheld_summary
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER source_disposition_candidate_insert
BEFORE INSERT ON loader_control.source_disposition
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER public_release_candidate_insert
BEFORE INSERT ON publication.public_release
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER public_species_candidate_insert
BEFORE INSERT ON publication.public_species
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER public_distribution_cell_candidate_insert
BEFORE INSERT ON publication.public_distribution_cell
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER public_species_year_candidate_insert
BEFORE INSERT ON publication.public_species_year
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();
CREATE TRIGGER public_record_candidate_insert
BEFORE INSERT ON publication.public_record
FOR EACH STATEMENT EXECUTE FUNCTION loader_control.guard_candidate_release_insert();

ALTER TABLE loader_control.release_manifest ENABLE ROW LEVEL SECURITY;
ALTER TABLE loader_control.withheld_summary ENABLE ROW LEVEL SECURITY;
ALTER TABLE loader_control.source_disposition ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication.public_release ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication.public_species ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication.public_distribution_cell ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication.public_species_year ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication.public_record ENABLE ROW LEVEL SECURITY;

CREATE POLICY release_manifest_read ON loader_control.release_manifest
FOR SELECT USING (true);
CREATE POLICY release_manifest_candidate_write ON loader_control.release_manifest
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY withheld_summary_read ON loader_control.withheld_summary
FOR SELECT USING (true);
CREATE POLICY withheld_summary_candidate_write ON loader_control.withheld_summary
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY source_disposition_read ON loader_control.source_disposition
FOR SELECT USING (true);
CREATE POLICY source_disposition_candidate_write ON loader_control.source_disposition
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY public_release_read ON publication.public_release
FOR SELECT USING (true);
CREATE POLICY public_release_candidate_write ON publication.public_release
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY public_species_read ON publication.public_species
FOR SELECT USING (true);
CREATE POLICY public_species_candidate_write ON publication.public_species
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY public_distribution_cell_read ON publication.public_distribution_cell
FOR SELECT USING (true);
CREATE POLICY public_distribution_cell_candidate_write ON publication.public_distribution_cell
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY public_species_year_read ON publication.public_species_year
FOR SELECT USING (true);
CREATE POLICY public_species_year_candidate_write ON publication.public_species_year
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);
CREATE POLICY public_record_read ON publication.public_record
FOR SELECT USING (true);
CREATE POLICY public_record_candidate_write ON publication.public_record
FOR INSERT WITH CHECK (
    release_id = pg_catalog.current_setting('brerc.authorized_candidate_release', true)::uuid
);

-- Sole publication activation authority. The loader cannot UPDATE release or
-- source_state directly. This routine locks the source, proves the candidate's
-- immutable ledger and public tables reconcile with the insert-only manifest,
-- then changes release status, pointer, watermark, job result and notification
-- in one transaction. Any exception rolls all of it back.
CREATE FUNCTION loader_control.activate_validated_release(candidate_release_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $activate_validated_release$
DECLARE
    candidate_source_id text;
    candidate_job_id uuid;
    candidate_base_release_id uuid;
    candidate_load_mode text;
    candidate_status text;
    candidate_job_status text;
    active_release_id uuid;
    manifest loader_control.release_manifest%ROWTYPE;
    capabilities publication.public_release%ROWTYPE;
    disposition_count bigint;
    inventory_count bigint;
    inventory_upper_date date;
    inventory_null_date_count bigint;
    inventory_dated_count bigint;
    delta_count bigint;
    eligible_count bigint;
    transform_withheld_count bigint;
    suppression_withheld_count bigint;
    species_count bigint;
    cell_count bigint;
    species_year_count bigint;
    public_record_count bigint;
    cell_total bigint;
    species_year_total bigint;
    species_total bigint;
    withheld_total bigint;
    required_checks integer;
    changed_rows bigint;
    reuse_active_release boolean;
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

    SELECT s.active_release_id
    INTO active_release_id
    FROM loader_control.source_state AS s
    WHERE s.source_id = candidate_source_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate source state is absent';
    END IF;

    -- A lost client acknowledgement may call the same activation again.
    IF candidate_status = 'active' AND active_release_id = candidate_release_id THEN
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
    SELECT p.*
    INTO capabilities
    FROM publication.public_release AS p
    WHERE p.release_id = candidate_release_id;
    IF NOT FOUND
        OR capabilities.source_data_as_of <> manifest.source_snapshot_at
        OR capabilities.publication_policy_version <> manifest.publication_policy_version
        OR capabilities.suppression_mode <> manifest.suppression_mode
        OR capabilities.min_records_per_cell <> manifest.min_records_per_cell
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate public release metadata is absent or inconsistent';
    END IF;

    -- Derive the source/disposition evidence from stored rows. The loader's
    -- reconciliation_result rows remain useful audit evidence but are never
    -- accepted as a substitute for these database-side proofs.
    SELECT
        count(*),
        max(observed_modified_date),
        count(*) FILTER (WHERE observed_modified_date IS NULL),
        count(*) FILTER (WHERE observed_modified_date IS NOT NULL)
    INTO
        inventory_count,
        inventory_upper_date,
        inventory_null_date_count,
        inventory_dated_count
    FROM loader_stage.source_inventory
    WHERE job_id = candidate_job_id;
    SELECT count(*) INTO delta_count
    FROM loader_stage.disposition_delta
    WHERE job_id = candidate_job_id;
    SELECT
        count(*),
        count(*) FILTER (WHERE d.disposition = 'eligible'),
        count(*) FILTER (WHERE d.disposition = 'withheld'),
        count(*) FILTER (WHERE d.disposition = 'suppressed')
    INTO
        disposition_count,
        eligible_count,
        transform_withheld_count,
        suppression_withheld_count
    FROM loader_control.source_disposition AS d
    WHERE d.release_id = candidate_release_id;

    IF inventory_count <> manifest.source_inventory_count
        OR inventory_count <> manifest.source_row_count
        OR delta_count <> manifest.delta_row_count
        OR disposition_count <> manifest.source_row_count
        OR eligible_count <> manifest.published_basis_count
        OR transform_withheld_count <> manifest.transform_withheld_count
        OR suppression_withheld_count <> manifest.suppression_withheld_count
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate source ledger counts do not reconcile with its manifest';
    END IF;

    IF inventory_upper_date IS DISTINCT FROM manifest.upper_modified_date
        OR (
            manifest.upper_modified_date IS NULL
            AND inventory_dated_count <> 0
        )
        OR (
            manifest.upper_modified_date IS NOT NULL
            AND (
                inventory_null_date_count <> 0
                OR NOT EXISTS (
                    SELECT 1
                    FROM loader_stage.source_inventory AS i
                    WHERE i.job_id = candidate_job_id
                      AND i.observed_modified_date = manifest.upper_modified_date
                      AND i.source_key_token = manifest.upper_modified_key_token
                )
                OR EXISTS (
                    SELECT 1
                    FROM loader_stage.source_inventory AS i
                    WHERE i.job_id = candidate_job_id
                      AND i.observed_modified_date = manifest.upper_modified_date
                      AND i.source_key_token > manifest.upper_modified_key_token
                )
            )
        )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate upper watermark differs from its complete source inventory';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            (
                SELECT i.source_key_token
                FROM loader_stage.source_inventory AS i
                WHERE i.job_id = candidate_job_id
                EXCEPT
                SELECT d.source_key_token
                FROM loader_control.source_disposition AS d
                WHERE d.release_id = candidate_release_id
            )
            UNION ALL
            (
                SELECT d.source_key_token
                FROM loader_control.source_disposition AS d
                WHERE d.release_id = candidate_release_id
                EXCEPT
                SELECT i.source_key_token
                FROM loader_stage.source_inventory AS i
                WHERE i.job_id = candidate_job_id
            )
        ) AS token_difference
    ) OR EXISTS (
        SELECT 1
        FROM loader_stage.source_inventory AS i
        JOIN loader_control.source_disposition AS d
          ON d.release_id = candidate_release_id
         AND d.source_key_token = i.source_key_token
        WHERE i.job_id = candidate_job_id
          AND i.input_fingerprint <> d.input_fingerprint
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate inventory and immutable disposition token sets differ';
    END IF;

    -- A delta row must describe the same final snapshot. A delete is valid only
    -- for a key present in the base release and absent from both new inventory
    -- and new disposition; every other action must match the final disposition.
    IF EXISTS (
        SELECT 1
        FROM loader_stage.disposition_delta AS x
        LEFT JOIN loader_stage.source_inventory AS i
          ON i.job_id = x.job_id
         AND i.source_key_token = x.source_key_token
        LEFT JOIN loader_control.source_disposition AS d
          ON d.release_id = candidate_release_id
         AND d.source_key_token = x.source_key_token
        LEFT JOIN loader_control.source_disposition AS b
          ON b.release_id = candidate_base_release_id
         AND b.source_key_token = x.source_key_token
        WHERE x.job_id = candidate_job_id
          AND (
              (
                  x.action = 'upsert'
                  AND (
                      i.source_key_token IS NULL
                      OR d.disposition IS DISTINCT FROM 'eligible'
                      OR x.input_fingerprint IS DISTINCT FROM i.input_fingerprint
                      OR x.input_fingerprint IS DISTINCT FROM d.input_fingerprint
                  )
              )
              OR (
                  x.action = 'withhold'
                  AND (
                      i.source_key_token IS NULL
                      OR d.disposition IS DISTINCT FROM 'withheld'
                      OR x.input_fingerprint IS DISTINCT FROM i.input_fingerprint
                      OR x.input_fingerprint IS DISTINCT FROM d.input_fingerprint
                      OR x.withheld_reason IS DISTINCT FROM d.withheld_reason
                  )
              )
              OR (
                  x.action = 'suppress'
                  AND (
                      i.source_key_token IS NULL
                      OR d.disposition IS DISTINCT FROM 'suppressed'
                      OR x.input_fingerprint IS DISTINCT FROM i.input_fingerprint
                      OR x.input_fingerprint IS DISTINCT FROM d.input_fingerprint
                      OR x.withheld_reason IS DISTINCT FROM d.withheld_reason
                  )
              )
              OR (
                  x.action = 'delete'
                  AND (
                      i.source_key_token IS NOT NULL
                      OR d.source_key_token IS NOT NULL
                      OR b.source_key_token IS NULL
                  )
              )
              OR (
                  x.action IN ('upsert', 'withhold', 'suppress')
                  AND ROW(
                      x.input_fingerprint,
                      x.withheld_reason,
                      x.species_id,
                      x.scientific_name,
                      x.common_name,
                      x.record_grid_ref,
                      x.record_precision_metres,
                      x.cell_id,
                      x.cell_precision_metres,
                      x.min_easting,
                      x.min_northing,
                      x.max_easting,
                      x.max_northing,
                      x.record_year,
                      x.public_record_id,
                      x.place,
                      x.abundance,
                      x.record_type,
                      x.verified_status,
                      x.source_label
                  ) IS DISTINCT FROM ROW(
                      d.input_fingerprint,
                      d.withheld_reason,
                      d.species_id,
                      d.scientific_name,
                      d.common_name,
                      d.record_grid_ref,
                      d.record_precision_metres,
                      d.cell_id,
                      d.cell_precision_metres,
                      d.min_easting,
                      d.min_northing,
                      d.max_easting,
                      d.max_northing,
                      d.record_year,
                      d.public_record_id,
                      d.place,
                      d.abundance,
                      d.record_type,
                      d.verified_status,
                      d.source_label
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate delta does not describe its complete final snapshot';
    END IF;

    -- An initial load describes every source key exactly once; it is not a
    -- sparse change set. This reverse proof catches an omitted transformation
    -- even when every delta row that is present is internally valid.
    IF candidate_load_mode = 'initial' AND (
        delta_count <> inventory_count
        OR EXISTS (
            SELECT 1
            FROM loader_stage.disposition_delta AS x
            WHERE x.job_id = candidate_job_id
              AND x.action = 'delete'
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
            ) AS initial_delta_difference
        )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'initial delta is not the complete source snapshot';
    END IF;

    -- Future incremental candidates are complete replacement ledgers. Their
    -- sparse delta must name exactly the keys whose final safe disposition is
    -- new, removed or changed relative to the active base. Incremental loading
    -- remains externally blocked, but the database must still reject a
    -- hand-built candidate that omits part of the change set.
    IF candidate_load_mode = 'incremental' AND EXISTS (
        WITH base_rows AS (
            SELECT *
            FROM loader_control.source_disposition
            WHERE release_id = candidate_base_release_id
        ), candidate_rows AS (
            SELECT *
            FROM loader_control.source_disposition
            WHERE release_id = candidate_release_id
        ), actual_change AS (
            SELECT COALESCE(b.source_key_token, d.source_key_token) AS source_key_token
            FROM base_rows AS b
            FULL JOIN candidate_rows AS d USING (source_key_token)
            WHERE b.source_key_token IS NULL
               OR d.source_key_token IS NULL
               OR ROW(
                    b.input_fingerprint,
                    b.disposition,
                    b.withheld_reason,
                    b.species_id,
                    b.scientific_name,
                    b.common_name,
                    b.record_grid_ref,
                    b.record_precision_metres,
                    b.cell_id,
                    b.cell_precision_metres,
                    b.min_easting,
                    b.min_northing,
                    b.max_easting,
                    b.max_northing,
                    b.record_year,
                    b.public_record_id,
                    b.place,
                    b.abundance,
                    b.record_type,
                    b.verified_status,
                    b.source_label
                  ) IS DISTINCT FROM ROW(
                    d.input_fingerprint,
                    d.disposition,
                    d.withheld_reason,
                    d.species_id,
                    d.scientific_name,
                    d.common_name,
                    d.record_grid_ref,
                    d.record_precision_metres,
                    d.cell_id,
                    d.cell_precision_metres,
                    d.min_easting,
                    d.min_northing,
                    d.max_easting,
                    d.max_northing,
                    d.record_year,
                    d.public_record_id,
                    d.place,
                    d.abundance,
                    d.record_type,
                    d.verified_status,
                    d.source_label
                  )
        ), delta_tokens AS (
            SELECT source_key_token
            FROM loader_stage.disposition_delta
            WHERE job_id = candidate_job_id
        )
        SELECT 1
        FROM (
            (
                SELECT source_key_token FROM actual_change
                EXCEPT
                SELECT source_key_token FROM delta_tokens
            )
            UNION ALL
            (
                SELECT source_key_token FROM delta_tokens
                EXCEPT
                SELECT source_key_token FROM actual_change
            )
        ) AS incremental_delta_difference
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'incremental delta differs from the complete base change set';
    END IF;

    IF EXISTS (
        WITH actual AS (
            SELECT d.withheld_reason AS reason_code, count(*) AS row_count
            FROM loader_control.source_disposition AS d
            WHERE d.release_id = candidate_release_id
              AND d.disposition IN ('withheld', 'suppressed')
            GROUP BY d.withheld_reason
        ), recorded AS (
            SELECT w.reason_code, w.row_count
            FROM loader_control.withheld_summary AS w
            WHERE w.release_id = candidate_release_id
        )
        SELECT 1
        FROM actual
        FULL JOIN recorded USING (reason_code)
        WHERE actual.row_count IS DISTINCT FROM recorded.row_count
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate withheld-reason summary differs from its immutable ledger';
    END IF;

    -- The approved threshold is persisted in both the immutable manifest and
    -- release metadata. Prove it over the complete final ledger, by the exact
    -- approved cohort (species, year, cell, precision).
    IF (
        manifest.suppression_mode = 'none'
        AND suppression_withheld_count <> 0
    ) OR EXISTS (
        SELECT 1
        FROM loader_control.source_disposition AS d
        WHERE d.release_id = candidate_release_id
          AND d.disposition = 'eligible'
        GROUP BY d.species_id, d.record_year, d.cell_id, d.cell_precision_metres
        HAVING count(*) < manifest.min_records_per_cell
    ) OR EXISTS (
        SELECT 1
        FROM loader_control.source_disposition AS d
        WHERE d.release_id = candidate_release_id
          AND d.disposition = 'suppressed'
        GROUP BY d.species_id, d.record_year, d.cell_id, d.cell_precision_metres
        HAVING count(*) >= manifest.min_records_per_cell
    ) OR EXISTS (
        SELECT 1
        FROM loader_control.source_disposition AS kept
        JOIN loader_control.source_disposition AS hidden
          ON hidden.release_id = kept.release_id
         AND hidden.disposition = 'suppressed'
         AND hidden.species_id = kept.species_id
         AND hidden.record_year = kept.record_year
         AND hidden.cell_id = kept.cell_id
         AND hidden.cell_precision_metres = kept.cell_precision_metres
        WHERE kept.release_id = candidate_release_id
          AND kept.disposition = 'eligible'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate violates its approval-bound suppression threshold';
    END IF;

    -- Recompute every aggregate from the immutable eligible ledger. Symmetric
    -- full joins catch missing/extra keys as well as count swaps whose grand
    -- total happens to remain unchanged.
    IF EXISTS (
        WITH actual AS (
            SELECT
                d.species_id,
                d.record_year,
                d.cell_id,
                d.cell_precision_metres AS precision_metres,
                count(*) AS record_count,
                count(*) FILTER (WHERE d.verified_status = 'accepted') AS verified_count
            FROM loader_control.source_disposition AS d
            WHERE d.release_id = candidate_release_id
              AND d.disposition = 'eligible'
            GROUP BY d.species_id, d.record_year, d.cell_id, d.cell_precision_metres
        ), recorded AS (
            SELECT
                p.species_id,
                p.record_year,
                p.cell_id,
                p.precision_metres,
                p.record_count,
                p.verified_count
            FROM publication.public_distribution_cell AS p
            WHERE p.release_id = candidate_release_id
        )
        SELECT 1
        FROM actual
        FULL JOIN recorded USING (species_id, record_year, cell_id, precision_metres)
        WHERE actual.record_count IS DISTINCT FROM recorded.record_count
           OR recorded.verified_count IS DISTINCT FROM CASE
                WHEN capabilities.verification_available THEN actual.verified_count
                ELSE NULL
              END
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate map cells differ from its immutable eligible ledger';
    END IF;

    IF EXISTS (
        WITH actual AS (
            SELECT
                d.species_id,
                d.record_year,
                count(*) AS record_count,
                count(*) FILTER (WHERE d.verified_status = 'accepted') AS verified_count
            FROM loader_control.source_disposition AS d
            WHERE d.release_id = candidate_release_id
              AND d.disposition = 'eligible'
            GROUP BY d.species_id, d.record_year
        ), recorded AS (
            SELECT
                p.species_id,
                p.record_year,
                p.record_count,
                p.verified_count
            FROM publication.public_species_year AS p
            WHERE p.release_id = candidate_release_id
        )
        SELECT 1
        FROM actual
        FULL JOIN recorded USING (species_id, record_year)
        WHERE actual.record_count IS DISTINCT FROM recorded.record_count
           OR recorded.verified_count IS DISTINCT FROM CASE
                WHEN capabilities.verification_available THEN actual.verified_count
                ELSE NULL
              END
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate year series differs from its immutable eligible ledger';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM loader_control.source_disposition AS d
        WHERE d.release_id = candidate_release_id
          AND d.disposition = 'eligible'
        GROUP BY d.species_id
        HAVING count(DISTINCT d.scientific_name) <> 1
            OR count(DISTINCT d.common_name) > 1
            OR (
                count(d.common_name) > 0
                AND count(d.common_name) < count(*)
            )
    ) OR EXISTS (
        WITH actual AS (
            SELECT
                d.species_id,
                min(d.scientific_name) AS scientific_name,
                min(d.common_name) AS common_name,
                count(*) AS total_records,
                min(d.record_year) AS first_year,
                max(d.record_year) AS last_year
            FROM loader_control.source_disposition AS d
            WHERE d.release_id = candidate_release_id
              AND d.disposition = 'eligible'
            GROUP BY d.species_id
        ), recorded AS (
            SELECT
                p.species_id,
                p.scientific_name,
                p.common_name,
                p.taxon_group,
                p.total_records,
                p.first_year,
                p.last_year
            FROM publication.public_species AS p
            WHERE p.release_id = candidate_release_id
        )
        SELECT 1
        FROM actual
        FULL JOIN recorded USING (species_id)
        WHERE actual.scientific_name IS DISTINCT FROM recorded.scientific_name
           OR actual.common_name IS DISTINCT FROM recorded.common_name
           OR recorded.taxon_group IS NOT NULL
           OR actual.total_records IS DISTINCT FROM recorded.total_records
           OR actual.first_year IS DISTINCT FROM recorded.first_year
           OR actual.last_year IS DISTINCT FROM recorded.last_year
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate species summaries differ from its immutable eligible ledger';
    END IF;

    SELECT count(*) INTO species_count
    FROM publication.public_species WHERE release_id = candidate_release_id;
    SELECT count(*), COALESCE(sum(record_count), 0)
    INTO cell_count, cell_total
    FROM publication.public_distribution_cell WHERE release_id = candidate_release_id;
    SELECT count(*), COALESCE(sum(record_count), 0)
    INTO species_year_count, species_year_total
    FROM publication.public_species_year WHERE release_id = candidate_release_id;
    SELECT COALESCE(sum(total_records), 0)
    INTO species_total
    FROM publication.public_species WHERE release_id = candidate_release_id;
    SELECT count(*) INTO public_record_count
    FROM publication.public_record WHERE release_id = candidate_release_id;
    SELECT COALESCE(sum(row_count), 0)
    INTO withheld_total
    FROM loader_control.withheld_summary WHERE release_id = candidate_release_id;

    IF manifest.published_basis_count < 1
        OR species_count < 1
        OR cell_count < 1
        OR species_year_count < 1
        OR species_count <> manifest.species_count
        OR cell_count <> manifest.cell_count
        OR species_year_count <> manifest.species_year_count
        OR public_record_count <> manifest.public_record_count
        OR cell_total <> manifest.published_basis_count
        OR species_year_total <> manifest.published_basis_count
        OR species_total <> manifest.published_basis_count
        OR withheld_total <> manifest.transform_withheld_count
            + manifest.suppression_withheld_count
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate database counts do not reconcile with its manifest';
    END IF;

    IF capabilities.individual_records_available AND EXISTS (
        WITH actual AS (
            SELECT
                d.public_record_id,
                d.species_id,
                d.scientific_name,
                d.common_name,
                d.record_grid_ref AS grid_ref,
                d.record_precision_metres AS precision_metres,
                CASE WHEN capabilities.place_available THEN d.place ELSE NULL END AS place,
                d.record_year,
                CASE WHEN capabilities.abundance_available THEN d.abundance ELSE NULL END
                    AS abundance,
                CASE WHEN capabilities.record_type_available THEN d.record_type ELSE NULL END
                    AS record_type,
                CASE
                    WHEN capabilities.record_verification_available THEN d.verified_status
                    ELSE NULL
                END AS verified_status,
                d.source_label
            FROM loader_control.source_disposition AS d
            WHERE d.release_id = candidate_release_id
              AND d.disposition = 'eligible'
        ), recorded AS (
            SELECT
                p.public_record_id,
                p.species_id,
                p.scientific_name,
                p.common_name,
                p.grid_ref,
                p.precision_metres,
                p.place,
                p.record_year,
                p.abundance,
                p.record_type,
                p.verified_status,
                p.source_label
            FROM publication.public_record AS p
            WHERE p.release_id = candidate_release_id
        )
        SELECT 1
        FROM actual
        FULL JOIN recorded USING (public_record_id)
        WHERE actual.species_id IS DISTINCT FROM recorded.species_id
           OR actual.scientific_name IS DISTINCT FROM recorded.scientific_name
           OR actual.common_name IS DISTINCT FROM recorded.common_name
           OR actual.grid_ref IS DISTINCT FROM recorded.grid_ref
           OR actual.precision_metres IS DISTINCT FROM recorded.precision_metres
           OR actual.place IS DISTINCT FROM recorded.place
           OR actual.record_year IS DISTINCT FROM recorded.record_year
           OR actual.abundance IS DISTINCT FROM recorded.abundance
           OR actual.record_type IS DISTINCT FROM recorded.record_type
           OR actual.verified_status IS DISTINCT FROM recorded.verified_status
           OR actual.source_label IS DISTINCT FROM recorded.source_label
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate public records differ from its immutable eligible ledger';
    END IF;

    IF (
        NOT capabilities.individual_records_available
        AND public_record_count <> 0
    ) OR (
        capabilities.individual_records_available
        AND public_record_count <> manifest.published_basis_count
    ) OR EXISTS (
        SELECT 1
        FROM loader_control.source_disposition AS d
        WHERE d.release_id = candidate_release_id
          AND d.disposition = 'eligible'
          AND d.source_label IS DISTINCT FROM capabilities.public_source_label
    ) OR (
        NOT capabilities.verification_available
        AND EXISTS (
            SELECT 1 FROM loader_control.source_disposition
            WHERE release_id = candidate_release_id
              AND disposition = 'eligible'
              AND verified_status IS NOT NULL
        )
    ) OR (
        NOT capabilities.place_available
        AND EXISTS (
            SELECT 1 FROM loader_control.source_disposition
            WHERE release_id = candidate_release_id
              AND disposition = 'eligible'
              AND place IS NOT NULL
        )
    ) OR (
        NOT capabilities.abundance_available
        AND EXISTS (
            SELECT 1 FROM loader_control.source_disposition
            WHERE release_id = candidate_release_id
              AND disposition = 'eligible'
              AND abundance IS NOT NULL
        )
    ) OR (
        NOT capabilities.record_type_available
        AND EXISTS (
            SELECT 1 FROM loader_control.source_disposition
            WHERE release_id = candidate_release_id
              AND disposition = 'eligible'
              AND record_type IS NOT NULL
        )
    ) OR (
        NOT capabilities.verification_available
        AND (
            EXISTS (
                SELECT 1 FROM publication.public_distribution_cell
                WHERE release_id = candidate_release_id AND verified_count IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM publication.public_species_year
                WHERE release_id = candidate_release_id AND verified_count IS NOT NULL
            )
        )
    ) OR (
        NOT capabilities.record_verification_available
        AND EXISTS (
            SELECT 1 FROM publication.public_record
            WHERE release_id = candidate_release_id AND verified_status IS NOT NULL
        )
    ) OR (
        NOT capabilities.place_available
        AND EXISTS (
            SELECT 1 FROM publication.public_record
            WHERE release_id = candidate_release_id AND place IS NOT NULL
        )
    ) OR (
        NOT capabilities.abundance_available
        AND EXISTS (
            SELECT 1 FROM publication.public_record
            WHERE release_id = candidate_release_id AND abundance IS NOT NULL
        )
    ) OR (
        NOT capabilities.record_type_available
        AND EXISTS (
            SELECT 1 FROM publication.public_record
            WHERE release_id = candidate_release_id AND record_type IS NOT NULL
        )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate data contradicts its publication capabilities';
    END IF;

    -- A whole-run retry can rebuild data already activated by an earlier run
    -- whose acknowledgement was lost. Prove the complete release identity,
    -- discard this never-active duplicate and report the existing active ID.
    IF active_release_id IS DISTINCT FROM candidate_base_release_id THEN
        IF active_release_id IS NOT NULL AND EXISTS (
            SELECT 1
            FROM loader_control.release_manifest AS active_manifest
            WHERE active_manifest.release_id = active_release_id
              AND active_manifest.candidate_sha256 = manifest.candidate_sha256
              AND active_manifest.source_result_sha256 = manifest.source_result_sha256
              AND active_manifest.source_contract_sha256 = manifest.source_contract_sha256
              AND active_manifest.observed_view_identity_sha256
                    = manifest.observed_view_identity_sha256
              AND active_manifest.publication_policy_sha256
                    = manifest.publication_policy_sha256
              AND active_manifest.projection_sha256 = manifest.projection_sha256
              AND active_manifest.etl_version = manifest.etl_version
              AND active_manifest.policy_approval_sha256 = manifest.policy_approval_sha256
              AND active_manifest.suppression_mode = manifest.suppression_mode
              AND active_manifest.min_records_per_cell = manifest.min_records_per_cell
              AND active_manifest.compatibility_sha256 = manifest.compatibility_sha256
              AND active_manifest.upper_modified_date
                    IS NOT DISTINCT FROM manifest.upper_modified_date
              AND active_manifest.upper_modified_key_token
                    IS NOT DISTINCT FROM manifest.upper_modified_key_token
              AND active_manifest.source_row_count = manifest.source_row_count
        ) THEN
            UPDATE loader_control.release
            SET status = 'discarded',
                cleanup_pending = true
            WHERE release_id = candidate_release_id
              AND status IN ('candidate', 'validated');
            GET DIAGNOSTICS changed_rows = ROW_COUNT;
            IF changed_rows <> 1 THEN
                RAISE EXCEPTION USING
                    ERRCODE = '40001',
                    MESSAGE = 'duplicate candidate could not be discarded exactly once';
            END IF;

            UPDATE loader_control.etl_job
            SET status = 'succeeded',
                result_release_id = active_release_id,
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
                    MESSAGE = 'duplicate activation job could not reach success exactly once';
            END IF;

            -- Attempt the transactional success event. The release-level unique
            -- index suppresses a second delivery for an already-active release.
            INSERT INTO loader_control.notification_outbox (
                notification_id,
                job_id,
                release_id,
                event_type,
                destination_key
            ) VALUES (
                candidate_release_id,
                candidate_job_id,
                active_release_id,
                'etl_succeeded',
                'etl-operations'
            ) ON CONFLICT (release_id, event_type)
                WHERE event_type = 'etl_succeeded'
                DO NOTHING;

            -- Do not put a multi-million-row purge inside the authoritative
            -- success transition. The durable flag makes cleanup resumable;
            -- the loader attempts it immediately and, after a crash/timeout,
            -- the next lock owner must finish it before starting another job.
            RETURN active_release_id;
        END IF;

        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'active release changed and candidate is not an identical retry';
    END IF;

    IF candidate_load_mode = 'initial' AND (
        candidate_base_release_id IS NOT NULL
        OR active_release_id IS NOT NULL
        OR manifest.lower_modified_date IS NOT NULL
        OR manifest.lower_modified_key_token IS NOT NULL
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'initial candidate is not the first complete source snapshot';
    END IF;

    IF candidate_load_mode = 'incremental' AND (
        candidate_base_release_id IS NULL
        OR manifest.lower_modified_date IS NULL
        OR manifest.upper_modified_date IS NULL
        OR NOT EXISTS (
            SELECT 1
            FROM loader_control.source_state AS s
            WHERE s.source_id = candidate_source_id
              AND s.active_release_id = candidate_base_release_id
              AND s.compatibility_sha256 = manifest.compatibility_sha256
              AND s.last_successful_modified_date = manifest.lower_modified_date
              AND s.last_successful_modified_key_token
                    = manifest.lower_modified_key_token
        )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'incremental candidate lacks a compatible complete watermark';
    END IF;

    SELECT count(DISTINCT rr.check_code)
    INTO required_checks
    FROM loader_stage.reconciliation_result AS rr
    WHERE rr.job_id = candidate_job_id
      AND rr.passed
      AND rr.check_code IN (
          'SOURCE_INVENTORY',
          'SOURCE_DISPOSITIONS',
          'PUBLIC_CELL_TOTAL',
          'PUBLIC_SPECIES_YEAR_TOTAL',
          'PUBLIC_SPECIES_TOTAL',
          'PRIVACY_ALLOWLIST',
          'DATABASE_DIGEST',
          'ACTIVATION_THRESHOLDS'
      );
    IF required_checks <> 8 OR EXISTS (
        SELECT 1
        FROM loader_stage.reconciliation_result AS rr
        WHERE rr.job_id = candidate_job_id AND NOT rr.passed
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'candidate reconciliation gates are incomplete or failed';
    END IF;

    IF active_release_id IS NOT NULL THEN
        UPDATE loader_control.release
        SET status = 'retired',
            retired_at = transaction_timestamp()
        WHERE release_id = active_release_id
          AND source_id = candidate_source_id
          AND status = 'active';
        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION USING
                ERRCODE = '40001',
                MESSAGE = 'active base release could not be retired exactly once';
        END IF;
    END IF;

    UPDATE loader_control.release
    SET status = 'active',
        validated_at = COALESCE(validated_at, transaction_timestamp()),
        activated_at = transaction_timestamp()
    WHERE release_id = candidate_release_id
      AND status IN ('candidate', 'validated');
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'candidate release could not be activated exactly once';
    END IF;

    UPDATE loader_control.source_state
    SET active_release_id = candidate_release_id,
        last_successful_modified_date = manifest.upper_modified_date,
        last_successful_modified_key_token = manifest.upper_modified_key_token,
        last_source_snapshot_at = manifest.source_snapshot_at,
        last_source_row_count = manifest.source_row_count,
        last_full_reconciliation_at = transaction_timestamp(),
        compatibility_sha256 = manifest.compatibility_sha256,
        updated_at = transaction_timestamp()
    WHERE source_id = candidate_source_id;
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'source pointer and watermark could not be updated exactly once';
    END IF;

    UPDATE loader_control.etl_job
    SET status = 'succeeded',
        result_release_id = candidate_release_id,
        reused_active_release = false,
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
            MESSAGE = 'activation job could not reach success exactly once';
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
        candidate_release_id,
        'etl_succeeded',
        'etl-operations'
    ) ON CONFLICT (release_id, event_type)
        WHERE event_type = 'etl_succeeded'
        DO NOTHING;

    DELETE FROM loader_stage.reconciliation_result
    WHERE job_id = candidate_job_id;
    DELETE FROM loader_stage.disposition_delta
    WHERE job_id = candidate_job_id;
    DELETE FROM loader_stage.source_inventory
    WHERE job_id = candidate_job_id;

    RETURN candidate_release_id;
END
$activate_validated_release$;

-- Narrow terminal failure transition. It accepts only a fixed machine code,
-- never an exception string or source value, and can touch only an inactive
-- candidate plus its own nonterminal job. The failure notification is written
-- in the same transaction.
CREATE FUNCTION loader_control.fail_candidate(
    candidate_release_id uuid,
    fixed_failure_code text
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_candidate$
DECLARE
    candidate_source_id text;
    candidate_job_id uuid;
    candidate_status text;
    candidate_job_status text;
    candidate_job_failure_code text;
    changed_rows bigint;
BEGIN
    IF fixed_failure_code IS NULL
        OR fixed_failure_code NOT IN (
            'LOADER_FAILED',
            'LOADER_CONFIGURATION_INVALID',
            'INCREMENTAL_SOURCE_CONTRACT_BLOCKED',
            'LOADER_COORDINATOR_UNAVAILABLE',
            'LOADER_EXECUTION_FAILED',
            'LOADER_POLICY_INVALID',
            'LOADER_RELEASE_BLOCKED',
            'LOADER_TARGET_CONNECTION_FAILED',
            'LOADER_TARGET_PROTOCOL_INVALID',
            'LOADER_ALREADY_RUNNING',
            'LOADER_CANDIDATE_INVALID',
            'LOADER_SOURCE_COUNT_REJECTED',
            'LOADER_CLEANUP_FAILED',
            'LOADER_CLEANUP_PENDING'
        )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'failure code is outside the fixed operational vocabulary';
    END IF;

    SELECT r.source_id, r.job_id, r.status, j.status, j.failure_code
    INTO
        candidate_source_id,
        candidate_job_id,
        candidate_status,
        candidate_job_status,
        candidate_job_failure_code
    FROM loader_control.release AS r
    JOIN loader_control.etl_job AS j
      ON j.job_id = r.job_id
     AND j.source_id = r.source_id
    WHERE r.release_id = candidate_release_id
    FOR UPDATE OF r, j;

    IF NOT FOUND THEN
        -- The caller may be unwinding a BEGIN transaction that never committed
        -- its preconstructed handle. Exact absence is already clean and is an
        -- idempotent success; orphaned committed jobs are handled by the
        -- source-lock recovery routine.
        RETURN candidate_release_id;
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

    IF candidate_status = 'failed'
        AND candidate_job_status = 'failed'
        AND candidate_job_failure_code = fixed_failure_code
    THEN
        -- Repair a missing failure event without changing a completed cleanup
        -- back to pending. The pending flag is cleared only by the atomic purge
        -- function below.
        INSERT INTO loader_control.notification_outbox (
            notification_id,
            job_id,
            release_id,
            event_type,
            destination_key,
            failure_code
        ) VALUES (
            candidate_release_id,
            candidate_job_id,
            NULL,
            'etl_failed',
            'etl-operations',
            fixed_failure_code
        ) ON CONFLICT (job_id, event_type) DO NOTHING;
        RETURN candidate_release_id;
    END IF;

    IF candidate_status NOT IN ('candidate', 'validated')
        OR candidate_job_status NOT IN (
            'queued', 'preflight', 'extracting', 'transforming',
            'reconciling', 'validated', 'activating'
        )
        OR EXISTS (
            SELECT 1
            FROM loader_control.source_state AS s
            WHERE s.active_release_id = candidate_release_id
        )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'only an inactive candidate with a nonterminal job may fail';
    END IF;

    UPDATE loader_control.release
    SET status = 'failed',
        cleanup_pending = true
    WHERE release_id = candidate_release_id
      AND status IN ('candidate', 'validated');
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'candidate release could not fail exactly once';
    END IF;

    UPDATE loader_control.etl_job
    SET status = 'failed',
        failure_code = fixed_failure_code,
        started_at = COALESCE(started_at, transaction_timestamp()),
        heartbeat_at = transaction_timestamp(),
        finished_at = transaction_timestamp()
    WHERE job_id = candidate_job_id
      AND status IN (
          'queued', 'preflight', 'extracting', 'transforming',
          'reconciling', 'validated', 'activating'
      );
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'candidate job could not fail exactly once';
    END IF;

    INSERT INTO loader_control.notification_outbox (
        notification_id,
        job_id,
        release_id,
        event_type,
        destination_key,
        failure_code
    ) VALUES (
        candidate_release_id,
        candidate_job_id,
        NULL,
        'etl_failed',
        'etl-operations',
        fixed_failure_code
    ) ON CONFLICT (job_id, event_type) DO NOTHING;

    RETURN candidate_release_id;
END
$fail_candidate$;

-- Recover the one open job left by a dead worker. The caller must already own
-- the same session advisory lock used by the target connector; obtaining that
-- lock proves no earlier worker session still owns the source. There is no
-- clock-based guess and no manual review path. It commits the failed state,
-- notification and durable cleanup obligation quickly; the lock owner performs
-- the potentially large purge separately before a new job may begin.
CREATE FUNCTION loader_control.recover_orphaned_job(orphan_source_id text)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $recover_orphaned_job$
DECLARE
    orphan_job_id uuid;
    orphan_release_id uuid;
    orphan_release_status text;
    changed_rows bigint;
BEGIN
    IF orphan_source_id IS NULL OR pg_catalog.btrim(orphan_source_id) = '' THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'orphan recovery requires a named source';
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
              (pg_catalog.hashtextextended(orphan_source_id, 0) >> 32)
              & 4294967295
          )::oid
          AND held.objid = (
              pg_catalog.hashtextextended(orphan_source_id, 0)
              & 4294967295
          )::oid
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'source session advisory lock is required for orphan recovery';
    END IF;

    SELECT j.job_id
    INTO orphan_job_id
    FROM loader_control.etl_job AS j
    WHERE j.source_id = orphan_source_id
      AND j.status IN (
          'queued', 'preflight', 'extracting', 'transforming',
          'reconciling', 'validated', 'activating'
      )
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    SELECT r.release_id, r.status
    INTO orphan_release_id, orphan_release_status
    FROM loader_control.release AS r
    WHERE r.job_id = orphan_job_id
    FOR UPDATE;

    IF FOUND AND (
        orphan_release_status IN ('active', 'retired')
        OR EXISTS (
            SELECT 1
            FROM loader_control.source_state AS s
            WHERE s.active_release_id = orphan_release_id
        )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'orphan recovery refuses an active or retired release';
    END IF;

    IF orphan_release_id IS NOT NULL THEN
        UPDATE loader_control.release
        SET status = 'failed',
            cleanup_pending = true
        WHERE release_id = orphan_release_id
          AND status IN ('candidate', 'validated');
    END IF;

    UPDATE loader_control.etl_job
    SET status = 'failed',
        failure_code = 'WORKER_LOST',
        started_at = COALESCE(started_at, transaction_timestamp()),
        heartbeat_at = transaction_timestamp(),
        finished_at = transaction_timestamp()
    WHERE job_id = orphan_job_id
      AND status IN (
          'queued', 'preflight', 'extracting', 'transforming',
          'reconciling', 'validated', 'activating'
      );
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'orphaned job could not fail exactly once';
    END IF;

    INSERT INTO loader_control.notification_outbox (
        notification_id,
        job_id,
        release_id,
        event_type,
        destination_key,
        failure_code
    ) VALUES (
        orphan_job_id,
        orphan_job_id,
        NULL,
        'etl_failed',
        'etl-operations',
        'WORKER_LOST'
    ) ON CONFLICT (job_id, event_type) DO NOTHING;

    RETURN 1;
END
$recover_orphaned_job$;

-- The loader cannot mutate or delete publication tables directly. It may only
-- discard a release already marked failed and proven not to be the active
-- pointer. Successful retired-release retention remains a DBA-controlled,
-- separately reviewed operation.
CREATE FUNCTION loader_control.discard_inactive_candidate(candidate_release_id uuid)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $discard_inactive_candidate$
DECLARE
    candidate_source_id text;
    candidate_status text;
    candidate_job_id uuid;
    removed_rows bigint := 0;
    statement_rows bigint;
BEGIN
    SELECT r.source_id, r.status, r.job_id
    INTO candidate_source_id, candidate_status, candidate_job_id
    FROM loader_control.release AS r
    WHERE r.release_id = candidate_release_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'candidate release does not exist';
    END IF;
    IF candidate_status NOT IN ('failed', 'discarded') OR EXISTS (
        SELECT 1
        FROM loader_control.source_state AS s
        WHERE s.active_release_id = candidate_release_id
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'only an inactive failed or discarded candidate may be removed';
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
            MESSAGE = 'source session advisory lock is required for candidate cleanup';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(candidate_source_id, 0)
    );

    DELETE FROM publication.public_record WHERE release_id = candidate_release_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM publication.public_distribution_cell WHERE release_id = candidate_release_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM publication.public_species_year WHERE release_id = candidate_release_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM publication.public_species WHERE release_id = candidate_release_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM publication.public_release WHERE release_id = candidate_release_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM loader_control.source_disposition WHERE release_id = candidate_release_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM loader_stage.reconciliation_result WHERE job_id = candidate_job_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM loader_stage.disposition_delta WHERE job_id = candidate_job_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;
    DELETE FROM loader_stage.source_inventory WHERE job_id = candidate_job_id;
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    removed_rows := removed_rows + statement_rows;

    UPDATE loader_control.release
    SET cleanup_pending = false
    WHERE release_id = candidate_release_id
      AND status IN ('failed', 'discarded');
    GET DIAGNOSTICS statement_rows = ROW_COUNT;
    IF statement_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '40001',
            MESSAGE = 'candidate cleanup state could not be cleared exactly once';
    END IF;

    RETURN removed_rows;
END
$discard_inactive_candidate$;

-- Public-serving views are security-barrier, owner-executed views. The serving
-- roles have no base-table privilege, and every view requires both the pointer
-- and release status to agree. An inconsistent activation therefore fails
-- closed with no rows rather than exposing a candidate.
CREATE VIEW serve.public_release WITH (security_barrier = true) AS
SELECT
    p.release_id,
    r.activated_at AS published_at,
    p.source_data_as_of,
    p.publication_policy_version,
    p.dataset_version,
    p.verification_available,
    p.individual_records_available,
    p.record_verification_available,
    p.place_available,
    p.abundance_available,
    p.record_type_available,
    p.public_source_label
FROM publication.public_release AS p
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

CREATE VIEW serve.public_species WITH (security_barrier = true) AS
SELECT p.*
FROM publication.public_species AS p
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

CREATE VIEW serve.public_distribution_cell WITH (security_barrier = true) AS
SELECT
    p.release_id,
    p.species_id,
    p.record_year,
    p.cell_id,
    p.precision_metres,
    p.record_count,
    CASE WHEN capabilities.verification_available THEN p.verified_count ELSE NULL END
        AS verified_count,
    p.geom
FROM publication.public_distribution_cell AS p
JOIN publication.public_release AS capabilities
    ON capabilities.release_id = p.release_id
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

CREATE VIEW serve.public_species_year WITH (security_barrier = true) AS
SELECT
    p.release_id,
    p.species_id,
    p.record_year,
    p.record_count,
    CASE WHEN capabilities.verification_available THEN p.verified_count ELSE NULL END
        AS verified_count
FROM publication.public_species_year AS p
JOIN publication.public_release AS capabilities
    ON capabilities.release_id = p.release_id
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

CREATE VIEW serve.public_record WITH (security_barrier = true) AS
SELECT
    p.release_id,
    p.public_record_id,
    p.species_id,
    p.scientific_name,
    p.common_name,
    p.grid_ref,
    p.precision_metres,
    CASE WHEN capabilities.place_available THEN p.place ELSE NULL END AS place,
    p.record_year,
    CASE WHEN capabilities.abundance_available THEN p.abundance ELSE NULL END AS abundance,
    CASE WHEN capabilities.record_type_available THEN p.record_type ELSE NULL END AS record_type,
    CASE WHEN capabilities.record_verification_available THEN p.verified_status ELSE NULL END
        AS verified_status,
    p.source_label
FROM publication.public_record AS p
JOIN publication.public_release AS capabilities
    ON capabilities.release_id = p.release_id
   AND capabilities.individual_records_available
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

-- Safe operational views for the internal ETL dashboard. They expose fixed
-- codes and counts, never HMAC tokens, database errors or source values.
CREATE VIEW serve.etl_job_status WITH (security_barrier = true) AS
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
    created_at
FROM loader_control.etl_job;

CREATE VIEW serve.etl_release_status WITH (security_barrier = true) AS
SELECT
    release_id,
    source_id,
    job_id,
    base_release_id,
    load_mode,
    status,
    cleanup_pending,
    created_at,
    validated_at,
    activated_at,
    retired_at
FROM loader_control.release;

CREATE VIEW serve.etl_notification_status WITH (security_barrier = true) AS
SELECT
    notification_id,
    job_id,
    event_type,
    status,
    attempt_count,
    available_at,
    delivered_at,
    created_at
FROM loader_control.notification_outbox;

-- Remove implicit access first. Grant only the minimum role-specific surface.
REVOKE ALL ON SCHEMA loader_control, loader_stage, publication, serve FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA loader_control, loader_stage, publication, serve FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA loader_control, loader_stage, publication, serve FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA loader_control, loader_stage, publication, serve FROM PUBLIC;

GRANT USAGE ON SCHEMA loader_control, loader_stage, publication TO brerc_loader;
GRANT SELECT ON loader_control.schema_migration TO brerc_loader;
GRANT SELECT ON loader_control.deployment_identity TO brerc_loader;
GRANT SELECT ON loader_control.source_state TO brerc_loader;
GRANT INSERT (source_id) ON loader_control.source_state TO brerc_loader;
GRANT SELECT ON loader_control.etl_job TO brerc_loader;
GRANT INSERT (
    job_id, source_id, attempt, load_mode, base_release_id, started_at, heartbeat_at
) ON loader_control.etl_job TO brerc_loader;
GRANT UPDATE (
    status, started_at, heartbeat_at, source_rows_seen, candidate_rows, rows_withheld
) ON loader_control.etl_job TO brerc_loader;
GRANT SELECT ON loader_control.release TO brerc_loader;
GRANT INSERT (
    release_id, source_id, job_id, base_release_id, load_mode
) ON loader_control.release TO brerc_loader;
GRANT SELECT, INSERT ON loader_control.release_manifest TO brerc_loader;
GRANT SELECT, INSERT ON loader_control.withheld_summary TO brerc_loader;
GRANT SELECT ON loader_control.etl_job_event TO brerc_loader;
GRANT SELECT ON loader_control.notification_outbox TO brerc_loader;
GRANT SELECT, INSERT ON loader_control.source_disposition TO brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.bng_cell_polygon(text, integer) TO brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.authorize_candidate_writes(uuid) TO brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.activate_validated_release(uuid) TO brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.fail_candidate(uuid, text) TO brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.recover_orphaned_job(text) TO brerc_loader;
GRANT EXECUTE ON FUNCTION loader_control.discard_inactive_candidate(uuid) TO brerc_loader;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA loader_control TO brerc_loader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA loader_stage TO brerc_loader;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA publication TO brerc_loader;

GRANT USAGE ON SCHEMA serve TO brerc_api;
GRANT SELECT ON
    serve.public_release,
    serve.public_species,
    serve.public_distribution_cell,
    serve.public_species_year,
    serve.public_record
TO brerc_api;

GRANT USAGE ON SCHEMA serve TO brerc_martin;
GRANT SELECT ON serve.public_release, serve.public_distribution_cell TO brerc_martin;

GRANT USAGE ON SCHEMA serve TO brerc_monitor;
GRANT SELECT ON
    serve.etl_job_status,
    serve.etl_release_status,
    serve.etl_notification_status
TO brerc_monitor;

-- Make future additions fail closed by default. Each later migration must make
-- its grants explicit after applying its own version guard.
ALTER DEFAULT PRIVILEGES IN SCHEMA loader_control REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA loader_stage REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA publication REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA serve REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA loader_control REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA loader_stage REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA publication REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA serve REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA loader_control REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA loader_stage REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA publication REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA serve REVOKE ALL ON FUNCTIONS FROM PUBLIC;

INSERT INTO loader_control.schema_migration (
    migration_version,
    migration_key,
    migration_name
) VALUES (
    1,
    '0001_publication_store',
    'Release-scoped BRERC publication store and atomic active-release views'
);

COMMIT;

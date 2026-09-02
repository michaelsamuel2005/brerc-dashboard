-- BRERC destination publication store -- migration 0002.
--
-- Installs a least-privilege, at-least-once notification-delivery protocol on
-- the transactional outbox created by migration 0001.  Delivery destinations
-- remain configuration aliases; this database never stores addresses, webhook
-- URLs, credentials, provider responses, exception text or message bodies.
--
-- Apply with ON_ERROR_STOP enabled, after db/notifier_roles.sql.  The worker
-- must commit a claim before making an external request.  notification_id is
-- the stable provider idempotency key for the unavoidable crash window between
-- provider acceptance and database acknowledgement.

BEGIN;

SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('brerc:destination-schema-migration', 0)
);

DO $migration_guard$
DECLARE
    history_count integer;
BEGIN
    IF pg_catalog.to_regclass('loader_control.schema_migration') IS NULL THEN
        RAISE EXCEPTION
            'BRERC migration 0002 requires migration 0001; migration history is absent';
    END IF;

    SELECT pg_catalog.count(*)::integer
    INTO history_count
    FROM loader_control.schema_migration;

    IF history_count <> 1 OR NOT EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 1
          AND migration_key = '0001_publication_store'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration 0002 requires exact migration history 0001_publication_store';
    END IF;
END
$migration_guard$;

DO $schema_owner_guard$
DECLARE
    expected_owner oid;
BEGIN
    SELECT oid
    INTO STRICT expected_owner
    FROM pg_catalog.pg_roles
    WHERE rolname = current_user;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace
        WHERE nspname = 'loader_control'
          AND nspowner = expected_owner
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace
        WHERE nspname = 'serve'
          AND nspowner = expected_owner
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'loader_control'
          AND c.relname = 'notification_outbox'
          AND c.relkind = 'r'
          AND c.relowner = expected_owner
    ) THEN
        RAISE EXCEPTION
            'migration owner does not own the reviewed notification schemas and outbox';
    END IF;
END
$schema_owner_guard$;

DO $required_roles$
DECLARE
    required_role text;
    role_row record;
BEGIN
    FOREACH required_role IN ARRAY ARRAY[
        'brerc_notifier',
        'brerc_notifier_operator'
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
                'required NOLOGIN group role % is absent; run db/notifier_roles.sql first',
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
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_db_role_setting
                WHERE setrole = role_row.oid
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_shdepend
                WHERE refclassid =
                    'pg_catalog.pg_authid'::pg_catalog.regclass
                  AND refobjid = role_row.oid
                  AND deptype IN ('o', 'a')
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_database
                WHERE datdba = role_row.oid
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_default_acl
                WHERE defaclrole = role_row.oid
            )
            OR EXISTS (
                SELECT 1
                FROM (
                    SELECT a.grantee
                    FROM pg_catalog.pg_database AS d
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            d.datacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_namespace AS n
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            n.nspacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_class AS c
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            c.relacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_attribute AS attribute
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            attribute.attacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_proc AS p
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            p.proacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_type AS t
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            t.typacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_language AS language
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            language.lanacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_largeobject_metadata AS large_object
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            large_object.lomacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_foreign_data_wrapper AS wrapper
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            wrapper.fdwacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_foreign_server AS server
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            server.srvacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_tablespace AS tablespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            tablespace.spcacl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_parameter_acl AS parameter_acl
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        pg_catalog.coalesce(
                            parameter_acl.paracl,
                            '{}'::pg_catalog.aclitem[]
                        )
                    ) AS a
                    UNION ALL
                    SELECT a.grantee
                    FROM pg_catalog.pg_default_acl AS default_acl
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        default_acl.defaclacl
                    ) AS a
                ) AS direct_acl
                WHERE direct_acl.grantee = role_row.oid
            )
        THEN
            RAISE EXCEPTION
                'required group role % is not a pristine NOLOGIN capability role',
                required_role;
        END IF;
    END LOOP;
END
$required_roles$;

-- Migration 0001 grants nobody delivery-state UPDATE.  Refuse to invent lease
-- or audit evidence if a database owner has nevertheless changed a row by hand.
DO $legacy_state_guard$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM loader_control.notification_outbox
        WHERE status <> 'pending'
           OR attempt_count <> 0
           OR locked_at IS NOT NULL
           OR delivered_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION
            'notification outbox contains unreviewed legacy delivery state; reconcile it before migration';
    END IF;
END
$legacy_state_guard$;

ALTER TABLE loader_control.notification_outbox
    DROP CONSTRAINT notification_outbox_status,
    DROP CONSTRAINT notification_outbox_attempts_nonnegative,
    DROP CONSTRAINT notification_outbox_delivery_state;

ALTER TABLE loader_control.notification_outbox
    ADD COLUMN delivery_cycle integer NOT NULL DEFAULT 1,
    ADD COLUMN total_attempt_count bigint NOT NULL DEFAULT 0,
    ADD COLUMN max_attempts smallint NOT NULL DEFAULT 8,
    ADD COLUMN claim_token uuid,
    ADD COLUMN lease_expires_at timestamp with time zone,
    ADD COLUMN dead_lettered_at timestamp with time zone,
    ADD COLUMN last_delivery_failure_code text,
    ADD CONSTRAINT notification_outbox_status CHECK (
        status IN ('pending', 'delivering', 'delivery_failed', 'delivered', 'dead_letter')
    ),
    ADD CONSTRAINT notification_outbox_attempt_counts CHECK (
        delivery_cycle > 0
        AND attempt_count >= 0
        AND total_attempt_count >= attempt_count
        AND max_attempts BETWEEN 1 AND 32
        AND attempt_count <= max_attempts
    ),
    ADD CONSTRAINT notification_outbox_delivery_failure_code CHECK (
        last_delivery_failure_code IS NULL
        OR last_delivery_failure_code IN (
            'DELIVERY_TIMEOUT',
            'DELIVERY_CONNECTION_FAILED',
            'DELIVERY_RATE_LIMITED',
            'DELIVERY_PROVIDER_UNAVAILABLE',
            'DELIVERY_AUTHENTICATION_FAILED',
            'DELIVERY_DESTINATION_INVALID',
            'DELIVERY_PAYLOAD_REJECTED',
            'DELIVERY_CONFIGURATION_INVALID',
            'DELIVERY_LEASE_EXPIRED'
        )
    ),
    ADD CONSTRAINT notification_outbox_lease_order CHECK (
        lease_expires_at IS NULL
        OR (locked_at IS NOT NULL AND lease_expires_at > locked_at)
    ),
    ADD CONSTRAINT notification_outbox_claim_token_not_nil CHECK (
        claim_token IS NULL
        OR claim_token <> '00000000-0000-0000-0000-000000000000'::uuid
    ),
    ADD CONSTRAINT notification_outbox_delivery_state CHECK (
        (
            status = 'pending'
            AND attempt_count = 0
            AND locked_at IS NULL
            AND claim_token IS NULL
            AND lease_expires_at IS NULL
            AND delivered_at IS NULL
            AND dead_lettered_at IS NULL
            AND last_delivery_failure_code IS NULL
        ) OR (
            status = 'delivering'
            AND attempt_count BETWEEN 1 AND max_attempts
            AND locked_at IS NOT NULL
            AND claim_token IS NOT NULL
            AND lease_expires_at IS NOT NULL
            AND delivered_at IS NULL
            AND dead_lettered_at IS NULL
        ) OR (
            status = 'delivery_failed'
            AND attempt_count BETWEEN 1 AND max_attempts - 1
            AND locked_at IS NOT NULL
            AND claim_token IS NOT NULL
            AND lease_expires_at IS NULL
            AND delivered_at IS NULL
            AND dead_lettered_at IS NULL
            AND last_delivery_failure_code IS NOT NULL
        ) OR (
            status = 'delivered'
            AND attempt_count BETWEEN 1 AND max_attempts
            AND locked_at IS NOT NULL
            AND claim_token IS NOT NULL
            AND lease_expires_at IS NULL
            AND delivered_at IS NOT NULL
            AND dead_lettered_at IS NULL
        ) OR (
            status = 'dead_letter'
            AND attempt_count BETWEEN 1 AND max_attempts
            AND locked_at IS NOT NULL
            AND claim_token IS NOT NULL
            AND lease_expires_at IS NULL
            AND delivered_at IS NULL
            AND dead_lettered_at IS NOT NULL
            AND last_delivery_failure_code IS NOT NULL
        )
    );

DROP INDEX loader_control.notification_outbox_delivery_idx;
CREATE INDEX notification_outbox_ready_idx
    ON loader_control.notification_outbox (available_at, created_at, notification_id)
    WHERE status IN ('pending', 'delivery_failed');
CREATE INDEX notification_outbox_expired_lease_idx
    ON loader_control.notification_outbox (lease_expires_at, notification_id)
    WHERE status = 'delivering';
CREATE INDEX notification_outbox_dead_letter_idx
    ON loader_control.notification_outbox (dead_lettered_at DESC, notification_id)
    WHERE status = 'dead_letter';

-- Immutable, typed delivery audit.  No exception text, provider response or
-- message content can enter this table.  Only SECURITY DEFINER functions write
-- it; neither the worker nor the operator receives table privileges.
CREATE TABLE loader_control.notification_delivery_event (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id uuid NOT NULL
        REFERENCES loader_control.notification_outbox(notification_id),
    delivery_cycle integer NOT NULL,
    cycle_attempt integer NOT NULL,
    total_attempt_count bigint NOT NULL,
    event_code text NOT NULL,
    delivery_failure_code text,
    operator_reason_code text,
    duration_ms bigint,
    occurred_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT notification_delivery_event_cycle CHECK (
        delivery_cycle > 0
        AND cycle_attempt >= 0
        AND total_attempt_count >= cycle_attempt
    ),
    CONSTRAINT notification_delivery_event_code CHECK (
        event_code IN (
            'CLAIMED',
            'LEASE_RENEWED',
            'LEASE_EXPIRED',
            'RETRY_SCHEDULED',
            'DELIVERED',
            'DEAD_LETTERED',
            'REDRIVEN'
        )
    ),
    CONSTRAINT notification_delivery_event_failure_code CHECK (
        delivery_failure_code IS NULL
        OR delivery_failure_code IN (
            'DELIVERY_TIMEOUT',
            'DELIVERY_CONNECTION_FAILED',
            'DELIVERY_RATE_LIMITED',
            'DELIVERY_PROVIDER_UNAVAILABLE',
            'DELIVERY_AUTHENTICATION_FAILED',
            'DELIVERY_DESTINATION_INVALID',
            'DELIVERY_PAYLOAD_REJECTED',
            'DELIVERY_CONFIGURATION_INVALID',
            'DELIVERY_LEASE_EXPIRED'
        )
    ),
    CONSTRAINT notification_delivery_event_reason_code CHECK (
        operator_reason_code IS NULL
        OR operator_reason_code IN (
            'DESTINATION_REMEDIATED',
            'CREDENTIAL_ROTATED',
            'PROVIDER_RECOVERED',
            'MANUAL_REDRIVE_APPROVED'
        )
    ),
    CONSTRAINT notification_delivery_event_shape CHECK (
        (
            event_code = 'REDRIVEN'
            AND cycle_attempt = 0
            AND operator_reason_code IS NOT NULL
            AND delivery_failure_code IS NULL
        ) OR (
            event_code IN ('LEASE_EXPIRED', 'RETRY_SCHEDULED', 'DEAD_LETTERED')
            AND cycle_attempt > 0
            AND delivery_failure_code IS NOT NULL
            AND operator_reason_code IS NULL
        ) OR (
            event_code IN ('CLAIMED', 'LEASE_RENEWED', 'DELIVERED')
            AND cycle_attempt > 0
            AND delivery_failure_code IS NULL
            AND operator_reason_code IS NULL
        )
    ),
    CONSTRAINT notification_delivery_event_duration CHECK (
        duration_ms IS NULL OR duration_ms >= 0
    )
);
CREATE INDEX notification_delivery_event_notification_time_idx
    ON loader_control.notification_delivery_event
        (notification_id, occurred_at, event_id);
CREATE INDEX notification_delivery_event_code_time_idx
    ON loader_control.notification_delivery_event
        (event_code, occurred_at DESC, event_id DESC);

CREATE FUNCTION loader_control.claim_notifications(
    requested_limit integer,
    requested_lease_seconds integer
)
RETURNS TABLE (
    notification_id uuid,
    claim_token uuid,
    delivery_cycle integer,
    cycle_attempt integer,
    total_attempt_count bigint,
    job_id uuid,
    release_id uuid,
    event_type text,
    destination_key text,
    failure_code text,
    load_mode text,
    finished_at timestamp with time zone
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_notifications$
DECLARE
    exhausted record;
    candidate record;
    claim_time timestamp with time zone;
    generated_token uuid;
    elapsed_ms bigint;
BEGIN
    IF requested_limit IS NULL OR requested_limit NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification claim limit is outside the fixed safe range';
    END IF;
    IF requested_lease_seconds IS NULL OR requested_lease_seconds NOT BETWEEN 30 AND 900 THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification lease is outside the fixed safe range';
    END IF;

    -- An attempt whose lease expired at the per-cycle limit cannot be reclaimed.
    -- Move it to a durable dead letter before selecting new work.
    FOR exhausted IN
        SELECT
            o.notification_id,
            o.delivery_cycle,
            o.attempt_count,
            o.total_attempt_count,
            o.claim_token,
            o.locked_at
        FROM loader_control.notification_outbox AS o
        WHERE o.status = 'delivering'
          AND o.lease_expires_at <= pg_catalog.clock_timestamp()
          AND o.attempt_count >= o.max_attempts
        ORDER BY o.lease_expires_at, o.notification_id
        LIMIT requested_limit
        FOR UPDATE OF o SKIP LOCKED
    LOOP
        claim_time := pg_catalog.clock_timestamp();
        elapsed_ms := pg_catalog.greatest(
            0,
            (EXTRACT(EPOCH FROM (claim_time - exhausted.locked_at)) * 1000)::bigint
        );

        UPDATE loader_control.notification_outbox AS o
        SET status = 'dead_letter',
            lease_expires_at = NULL,
            dead_lettered_at = claim_time,
            last_delivery_failure_code = 'DELIVERY_LEASE_EXPIRED'
        WHERE o.notification_id = exhausted.notification_id;

        INSERT INTO loader_control.notification_delivery_event (
            notification_id,
            delivery_cycle,
            cycle_attempt,
            total_attempt_count,
            event_code,
            delivery_failure_code,
            duration_ms
        ) VALUES (
            exhausted.notification_id,
            exhausted.delivery_cycle,
            exhausted.attempt_count,
            exhausted.total_attempt_count,
            'DEAD_LETTERED',
            'DELIVERY_LEASE_EXPIRED',
            elapsed_ms
        );
    END LOOP;

    FOR candidate IN
        SELECT
            o.notification_id,
            o.status AS prior_status,
            o.delivery_cycle,
            o.attempt_count,
            o.total_attempt_count,
            o.job_id,
            o.release_id,
            o.event_type,
            o.destination_key,
            o.failure_code,
            o.created_at,
            o.locked_at,
            j.load_mode,
            j.finished_at
        FROM loader_control.notification_outbox AS o
        JOIN loader_control.etl_job AS j ON j.job_id = o.job_id
        WHERE (
            (
                o.status IN ('pending', 'delivery_failed')
                AND o.available_at <= pg_catalog.clock_timestamp()
            ) OR (
                o.status = 'delivering'
                AND o.lease_expires_at <= pg_catalog.clock_timestamp()
            )
        )
          AND o.attempt_count < o.max_attempts
          AND j.finished_at IS NOT NULL
          AND (
              (o.event_type = 'etl_succeeded' AND j.status = 'succeeded')
              OR (
                  o.event_type = 'etl_failed'
                  AND j.status = 'failed'
                  AND j.failure_code = o.failure_code
              )
          )
        ORDER BY
            CASE
                WHEN o.status = 'delivering' THEN o.lease_expires_at
                ELSE o.available_at
            END,
            o.created_at,
            o.notification_id
        LIMIT requested_limit
        FOR UPDATE OF o SKIP LOCKED
    LOOP
        claim_time := pg_catalog.clock_timestamp();

        IF candidate.prior_status = 'delivering' THEN
            elapsed_ms := pg_catalog.greatest(
                0,
                (EXTRACT(EPOCH FROM (claim_time - candidate.locked_at)) * 1000)::bigint
            );
            INSERT INTO loader_control.notification_delivery_event (
                notification_id,
                delivery_cycle,
                cycle_attempt,
                total_attempt_count,
                event_code,
                delivery_failure_code,
                duration_ms
            ) VALUES (
                candidate.notification_id,
                candidate.delivery_cycle,
                candidate.attempt_count,
                candidate.total_attempt_count,
                'LEASE_EXPIRED',
                'DELIVERY_LEASE_EXPIRED',
                elapsed_ms
            );
        END IF;

        generated_token := pg_catalog.gen_random_uuid();
        UPDATE loader_control.notification_outbox AS o
        SET status = 'delivering',
            attempt_count = candidate.attempt_count + 1,
            total_attempt_count = candidate.total_attempt_count + 1,
            locked_at = claim_time,
            claim_token = generated_token,
            lease_expires_at = claim_time
                + pg_catalog.make_interval(secs => requested_lease_seconds),
            delivered_at = NULL,
            dead_lettered_at = NULL
        WHERE o.notification_id = candidate.notification_id;

        INSERT INTO loader_control.notification_delivery_event (
            notification_id,
            delivery_cycle,
            cycle_attempt,
            total_attempt_count,
            event_code
        ) VALUES (
            candidate.notification_id,
            candidate.delivery_cycle,
            candidate.attempt_count + 1,
            candidate.total_attempt_count + 1,
            'CLAIMED'
        );

        notification_id := candidate.notification_id;
        claim_token := generated_token;
        delivery_cycle := candidate.delivery_cycle;
        cycle_attempt := candidate.attempt_count + 1;
        total_attempt_count := candidate.total_attempt_count + 1;
        job_id := candidate.job_id;
        release_id := candidate.release_id;
        event_type := candidate.event_type;
        destination_key := candidate.destination_key;
        failure_code := candidate.failure_code;
        load_mode := candidate.load_mode;
        finished_at := candidate.finished_at;
        RETURN NEXT;
    END LOOP;
END
$claim_notifications$;

CREATE FUNCTION loader_control.renew_notification_lease(
    requested_notification_id uuid,
    requested_claim_token uuid,
    requested_lease_seconds integer
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $renew_notification_lease$
DECLARE
    changed_rows integer;
BEGIN
    IF requested_notification_id IS NULL OR requested_claim_token IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification lease identity is required';
    END IF;
    IF requested_lease_seconds IS NULL OR requested_lease_seconds NOT BETWEEN 30 AND 900 THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification lease is outside the fixed safe range';
    END IF;

    UPDATE loader_control.notification_outbox AS o
    SET lease_expires_at = pg_catalog.clock_timestamp()
        + pg_catalog.make_interval(secs => requested_lease_seconds)
    WHERE o.notification_id = requested_notification_id
      AND o.status = 'delivering'
      AND o.claim_token = requested_claim_token
      AND o.lease_expires_at > pg_catalog.clock_timestamp();
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'notification lease cannot be renewed by this claim';
    END IF;

    INSERT INTO loader_control.notification_delivery_event (
        notification_id,
        delivery_cycle,
        cycle_attempt,
        total_attempt_count,
        event_code
    )
    SELECT
        o.notification_id,
        o.delivery_cycle,
        o.attempt_count,
        o.total_attempt_count,
        'LEASE_RENEWED'
    FROM loader_control.notification_outbox AS o
    WHERE o.notification_id = requested_notification_id;

    RETURN true;
END
$renew_notification_lease$;

CREATE FUNCTION loader_control.ack_notification(
    requested_notification_id uuid,
    requested_claim_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $ack_notification$
DECLARE
    delivery_row record;
    acknowledged_at timestamp with time zone;
    elapsed_ms bigint;
BEGIN
    IF requested_notification_id IS NULL OR requested_claim_token IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification acknowledgement identity is required';
    END IF;

    SELECT
        o.status,
        o.claim_token,
        o.delivery_cycle,
        o.attempt_count,
        o.total_attempt_count,
        o.locked_at,
        o.lease_expires_at
    INTO delivery_row
    FROM loader_control.notification_outbox AS o
    WHERE o.notification_id = requested_notification_id
    FOR UPDATE OF o;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'notification acknowledgement target is unavailable';
    END IF;
    IF delivery_row.status = 'delivered'
        AND delivery_row.claim_token = requested_claim_token
    THEN
        RETURN true;
    END IF;
    IF delivery_row.status <> 'delivering'
        OR delivery_row.claim_token <> requested_claim_token
        OR delivery_row.lease_expires_at IS NULL
        OR delivery_row.lease_expires_at <= pg_catalog.clock_timestamp()
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'notification cannot be acknowledged by this claim';
    END IF;

    acknowledged_at := pg_catalog.clock_timestamp();
    elapsed_ms := pg_catalog.greatest(
        0,
        (EXTRACT(EPOCH FROM (acknowledged_at - delivery_row.locked_at)) * 1000)::bigint
    );

    UPDATE loader_control.notification_outbox AS o
    SET status = 'delivered',
        lease_expires_at = NULL,
        delivered_at = acknowledged_at,
        dead_lettered_at = NULL
    WHERE o.notification_id = requested_notification_id;

    INSERT INTO loader_control.notification_delivery_event (
        notification_id,
        delivery_cycle,
        cycle_attempt,
        total_attempt_count,
        event_code,
        duration_ms
    ) VALUES (
        requested_notification_id,
        delivery_row.delivery_cycle,
        delivery_row.attempt_count,
        delivery_row.total_attempt_count,
        'DELIVERED',
        elapsed_ms
    );

    RETURN true;
END
$ack_notification$;

CREATE FUNCTION loader_control.fail_notification(
    requested_notification_id uuid,
    requested_claim_token uuid,
    fixed_delivery_failure_code text,
    requested_retry_after_seconds integer DEFAULT NULL
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_notification$
DECLARE
    delivery_row record;
    failure_at timestamp with time zone;
    retryable boolean;
    retry_delay_seconds integer;
    elapsed_ms bigint;
    result_status text;
BEGIN
    IF requested_notification_id IS NULL OR requested_claim_token IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification failure identity is required';
    END IF;
    IF fixed_delivery_failure_code NOT IN (
        'DELIVERY_TIMEOUT',
        'DELIVERY_CONNECTION_FAILED',
        'DELIVERY_RATE_LIMITED',
        'DELIVERY_PROVIDER_UNAVAILABLE',
        'DELIVERY_AUTHENTICATION_FAILED',
        'DELIVERY_DESTINATION_INVALID',
        'DELIVERY_PAYLOAD_REJECTED',
        'DELIVERY_CONFIGURATION_INVALID'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification failure code is outside the fixed operational vocabulary';
    END IF;
    IF requested_retry_after_seconds IS NOT NULL
        AND requested_retry_after_seconds NOT BETWEEN 30 AND 3600
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification retry delay is outside the fixed safe range';
    END IF;

    SELECT
        o.status,
        o.claim_token,
        o.delivery_cycle,
        o.attempt_count,
        o.total_attempt_count,
        o.max_attempts,
        o.locked_at,
        o.lease_expires_at,
        o.last_delivery_failure_code
    INTO delivery_row
    FROM loader_control.notification_outbox AS o
    WHERE o.notification_id = requested_notification_id
    FOR UPDATE OF o;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'notification failure target is unavailable';
    END IF;
    IF delivery_row.status IN ('delivery_failed', 'dead_letter')
        AND delivery_row.claim_token = requested_claim_token
        AND delivery_row.last_delivery_failure_code = fixed_delivery_failure_code
    THEN
        RETURN delivery_row.status;
    END IF;
    IF delivery_row.status <> 'delivering'
        OR delivery_row.claim_token <> requested_claim_token
        OR delivery_row.lease_expires_at IS NULL
        OR delivery_row.lease_expires_at <= pg_catalog.clock_timestamp()
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'notification failure cannot be recorded by this claim';
    END IF;

    retryable := fixed_delivery_failure_code IN (
        'DELIVERY_TIMEOUT',
        'DELIVERY_CONNECTION_FAILED',
        'DELIVERY_RATE_LIMITED',
        'DELIVERY_PROVIDER_UNAVAILABLE'
    );
    failure_at := pg_catalog.clock_timestamp();
    elapsed_ms := pg_catalog.greatest(
        0,
        (EXTRACT(EPOCH FROM (failure_at - delivery_row.locked_at)) * 1000)::bigint
    );

    IF retryable AND delivery_row.attempt_count < delivery_row.max_attempts THEN
        retry_delay_seconds := pg_catalog.coalesce(
            requested_retry_after_seconds,
            pg_catalog.least(
                3600,
                60 * pg_catalog.power(
                    2::numeric,
                    pg_catalog.least(delivery_row.attempt_count - 1, 6)
                )::integer
            )
        );
        result_status := 'delivery_failed';

        UPDATE loader_control.notification_outbox AS o
        SET status = result_status,
            available_at = failure_at
                + pg_catalog.make_interval(secs => retry_delay_seconds),
            lease_expires_at = NULL,
            delivered_at = NULL,
            dead_lettered_at = NULL,
            last_delivery_failure_code = fixed_delivery_failure_code
        WHERE o.notification_id = requested_notification_id;

        INSERT INTO loader_control.notification_delivery_event (
            notification_id,
            delivery_cycle,
            cycle_attempt,
            total_attempt_count,
            event_code,
            delivery_failure_code,
            duration_ms
        ) VALUES (
            requested_notification_id,
            delivery_row.delivery_cycle,
            delivery_row.attempt_count,
            delivery_row.total_attempt_count,
            'RETRY_SCHEDULED',
            fixed_delivery_failure_code,
            elapsed_ms
        );
    ELSE
        result_status := 'dead_letter';

        UPDATE loader_control.notification_outbox AS o
        SET status = result_status,
            lease_expires_at = NULL,
            delivered_at = NULL,
            dead_lettered_at = failure_at,
            last_delivery_failure_code = fixed_delivery_failure_code
        WHERE o.notification_id = requested_notification_id;

        INSERT INTO loader_control.notification_delivery_event (
            notification_id,
            delivery_cycle,
            cycle_attempt,
            total_attempt_count,
            event_code,
            delivery_failure_code,
            duration_ms
        ) VALUES (
            requested_notification_id,
            delivery_row.delivery_cycle,
            delivery_row.attempt_count,
            delivery_row.total_attempt_count,
            'DEAD_LETTERED',
            fixed_delivery_failure_code,
            elapsed_ms
        );
    END IF;

    RETURN result_status;
END
$fail_notification$;

-- Redrive is deliberately a separate human/operator capability.  It cannot
-- modify a live claim or delivered row, and it starts a new auditable cycle
-- without resetting the lifetime attempt total.
CREATE FUNCTION loader_control.requeue_dead_notification(
    requested_notification_id uuid,
    fixed_operator_reason_code text
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $requeue_dead_notification$
DECLARE
    delivery_row record;
    next_cycle integer;
BEGIN
    IF requested_notification_id IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'dead-letter notification identity is required';
    END IF;
    IF fixed_operator_reason_code NOT IN (
        'DESTINATION_REMEDIATED',
        'CREDENTIAL_ROTATED',
        'PROVIDER_RECOVERED',
        'MANUAL_REDRIVE_APPROVED'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'notification redrive reason is outside the fixed operational vocabulary';
    END IF;

    SELECT
        o.status,
        o.delivery_cycle,
        o.attempt_count,
        o.total_attempt_count
    INTO delivery_row
    FROM loader_control.notification_outbox AS o
    WHERE o.notification_id = requested_notification_id
    FOR UPDATE OF o;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'dead-letter notification is unavailable';
    END IF;

    -- Lost acknowledgement of the operator transaction is idempotent while the
    -- new cycle is still pristine.
    IF delivery_row.status = 'pending'
        AND delivery_row.attempt_count = 0
        AND delivery_row.total_attempt_count > 0
        AND EXISTS (
            SELECT 1
            FROM loader_control.notification_delivery_event AS e
            WHERE e.notification_id = requested_notification_id
              AND e.delivery_cycle = delivery_row.delivery_cycle
              AND e.event_code = 'REDRIVEN'
              AND e.operator_reason_code = fixed_operator_reason_code
        )
    THEN
        RETURN delivery_row.delivery_cycle;
    END IF;

    IF delivery_row.status <> 'dead_letter' THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'only a dead-letter notification can be redriven';
    END IF;

    next_cycle := delivery_row.delivery_cycle + 1;
    UPDATE loader_control.notification_outbox AS o
    SET status = 'pending',
        delivery_cycle = next_cycle,
        attempt_count = 0,
        available_at = pg_catalog.clock_timestamp(),
        locked_at = NULL,
        claim_token = NULL,
        lease_expires_at = NULL,
        delivered_at = NULL,
        dead_lettered_at = NULL,
        last_delivery_failure_code = NULL
    WHERE o.notification_id = requested_notification_id;

    INSERT INTO loader_control.notification_delivery_event (
        notification_id,
        delivery_cycle,
        cycle_attempt,
        total_attempt_count,
        event_code,
        operator_reason_code
    ) VALUES (
        requested_notification_id,
        next_cycle,
        0,
        delivery_row.total_attempt_count,
        'REDRIVEN',
        fixed_operator_reason_code
    );

    RETURN next_cycle;
END
$requeue_dead_notification$;

-- Preserve the original eight columns in order, then append only bounded,
-- non-secret operational state.  Claim tokens remain private to the delivery
-- functions; destination aliases remain absent from monitor-facing surfaces.
CREATE OR REPLACE VIEW serve.etl_notification_status
WITH (security_barrier = true) AS
SELECT
    notification_id,
    job_id,
    event_type,
    status,
    attempt_count,
    available_at,
    delivered_at,
    created_at,
    delivery_cycle,
    total_attempt_count,
    max_attempts,
    lease_expires_at,
    dead_lettered_at,
    last_delivery_failure_code
FROM loader_control.notification_outbox;

CREATE VIEW serve.etl_notification_delivery_event
WITH (security_barrier = true) AS
SELECT
    event_id,
    notification_id,
    delivery_cycle,
    cycle_attempt,
    total_attempt_count,
    event_code,
    delivery_failure_code,
    operator_reason_code,
    duration_ms,
    occurred_at
FROM loader_control.notification_delivery_event;

CREATE FUNCTION serve.notification_delivery_metrics()
RETURNS TABLE (
    event_type text,
    status text,
    notification_count bigint,
    total_attempt_count bigint,
    redrive_count bigint,
    oldest_created_at timestamp with time zone,
    oldest_ready_at timestamp with time zone,
    latest_delivered_at timestamp with time zone,
    latest_dead_lettered_at timestamp with time zone
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $notification_delivery_metrics$
    SELECT
        o.event_type,
        o.status,
        pg_catalog.count(*)::bigint AS notification_count,
        pg_catalog.sum(o.total_attempt_count)::bigint AS total_attempt_count,
        pg_catalog.sum(o.delivery_cycle - 1)::bigint AS redrive_count,
        pg_catalog.min(o.created_at) AS oldest_created_at,
        pg_catalog.min(o.available_at) FILTER (
            WHERE o.status IN ('pending', 'delivery_failed')
        ) AS oldest_ready_at,
        pg_catalog.max(o.delivered_at) AS latest_delivered_at,
        pg_catalog.max(o.dead_lettered_at) AS latest_dead_lettered_at
    FROM loader_control.notification_outbox AS o
    GROUP BY o.event_type, o.status
$notification_delivery_metrics$;

-- One fixed preflight surface lets the worker prove it reached the reviewed
-- migration through a dedicated TLS login without granting migration-table or
-- role-catalog access through application SQL.
CREATE FUNCTION serve.notification_worker_preflight()
RETURNS TABLE (
    database_name name,
    session_user_name name,
    server_version_num integer,
    ssl boolean,
    ssl_version text,
    migration_version integer,
    migration_key text,
    notifier_membership_only boolean
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $notification_worker_preflight$
    WITH application_schema(schema_name) AS (
        VALUES
            ('loader_control'::name),
            ('loader_stage'::name),
            ('publication'::name),
            ('serve'::name)
    ),
    expected_function(function_oid) AS (
        VALUES
            (
                pg_catalog.to_regprocedure(
                    'loader_control.claim_notifications(integer,integer)'
                )::oid
            ),
            (
                pg_catalog.to_regprocedure(
                    'loader_control.renew_notification_lease(uuid,uuid,integer)'
                )::oid
            ),
            (
                pg_catalog.to_regprocedure(
                    'loader_control.ack_notification(uuid,uuid)'
                )::oid
            ),
            (
                pg_catalog.to_regprocedure(
                    'loader_control.fail_notification(uuid,uuid,text,integer)'
                )::oid
            ),
            (
                pg_catalog.to_regprocedure(
                    'serve.notification_delivery_metrics()'
                )::oid
            ),
            (
                pg_catalog.to_regprocedure(
                    'serve.notification_worker_preflight()'
                )::oid
            )
    ),
    role_posture AS (
        SELECT
            login.oid AS login_oid,
            login.rolcanlogin AS login_can_login,
            login.rolinherit AS login_inherits,
            login.rolsuper AS login_super,
            login.rolcreatedb AS login_create_db,
            login.rolcreaterole AS login_create_role,
            login.rolreplication AS login_replication,
            login.rolbypassrls AS login_bypass_rls,
            notifier.oid AS notifier_oid,
            notifier.rolcanlogin AS notifier_can_login,
            notifier.rolinherit AS notifier_inherits,
            notifier.rolsuper AS notifier_super,
            notifier.rolcreatedb AS notifier_create_db,
            notifier.rolcreaterole AS notifier_create_role,
            notifier.rolreplication AS notifier_replication,
            notifier.rolbypassrls AS notifier_bypass_rls
        FROM pg_catalog.pg_roles AS login
        CROSS JOIN pg_catalog.pg_roles AS notifier
        WHERE login.rolname = session_user
          AND notifier.rolname = 'brerc_notifier'
    ),
    membership_posture AS (
        SELECT
            pg_catalog.count(*) FILTER (
                WHERE membership.member = role_posture.login_oid
            )::integer AS login_parent_count,
            pg_catalog.count(*) FILTER (
                WHERE membership.member = role_posture.login_oid
                  AND membership.roleid = role_posture.notifier_oid
            )::integer AS notifier_membership_count,
            pg_catalog.coalesce(
                pg_catalog.bool_and(
                    NOT membership.admin_option
                    AND membership.inherit_option
                    AND NOT membership.set_option
                ) FILTER (
                    WHERE membership.member = role_posture.login_oid
                      AND membership.roleid = role_posture.notifier_oid
                ),
                false
            ) AS notifier_membership_options_safe,
            pg_catalog.count(*) FILTER (
                WHERE membership.roleid = role_posture.notifier_oid
            )::integer AS notifier_child_count,
            pg_catalog.count(*) FILTER (
                WHERE membership.member = role_posture.notifier_oid
            )::integer AS notifier_parent_count
        FROM role_posture
        LEFT JOIN pg_catalog.pg_auth_members AS membership ON true
        GROUP BY role_posture.login_oid, role_posture.notifier_oid
    ),
    database_acl AS (
        SELECT
            database.datname AS database_name,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_database AS database
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                database.datacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
    ),
    schema_acl AS (
        SELECT
            namespace.oid AS object_oid,
            namespace.nspname AS schema_name,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                namespace.nspacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
    ),
    relation_acl AS (
        SELECT
            relation.oid AS object_oid,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                relation.relacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
    ),
    column_acl AS (
        SELECT
            attribute.attrelid AS object_oid,
            attribute.attnum,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_attribute AS attribute
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                attribute.attacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
    ),
    routine_acl AS (
        SELECT
            routine.oid AS object_oid,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_proc AS routine
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                routine.proacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
    ),
    type_acl AS (
        SELECT
            type.oid AS object_oid,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_type AS type
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                type.typacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
    ),
    miscellaneous_acl AS (
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_language AS language
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                language.lanacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
        UNION ALL
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_largeobject_metadata AS large_object
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                large_object.lomacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
        UNION ALL
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_foreign_data_wrapper AS wrapper
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                wrapper.fdwacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
        UNION ALL
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_foreign_server AS server
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                server.srvacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
        UNION ALL
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_tablespace AS tablespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                tablespace.spcacl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
        UNION ALL
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_parameter_acl AS parameter_acl
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            pg_catalog.coalesce(
                parameter_acl.paracl,
                '{}'::pg_catalog.aclitem[]
            )
        ) AS acl
        UNION ALL
        SELECT acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_default_acl AS default_acl
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            default_acl.defaclacl
        ) AS acl
    )
    SELECT
        pg_catalog.current_database() AS database_name,
        session_user AS session_user_name,
        pg_catalog.current_setting('server_version_num')::integer AS server_version_num,
        pg_catalog.coalesce(
            (
                SELECT s.ssl
                FROM pg_catalog.pg_stat_ssl AS s
                WHERE s.pid = pg_catalog.pg_backend_pid()
            ),
            false
        ) AS ssl,
        (
            SELECT s.version
            FROM pg_catalog.pg_stat_ssl AS s
            WHERE s.pid = pg_catalog.pg_backend_pid()
        ) AS ssl_version,
        m.migration_version,
        m.migration_key,
        (
            role_posture.login_can_login
            AND role_posture.login_inherits
            AND NOT role_posture.login_super
            AND NOT role_posture.login_create_db
            AND NOT role_posture.login_create_role
            AND NOT role_posture.login_replication
            AND NOT role_posture.login_bypass_rls
            AND NOT role_posture.notifier_can_login
            AND NOT role_posture.notifier_inherits
            AND NOT role_posture.notifier_super
            AND NOT role_posture.notifier_create_db
            AND NOT role_posture.notifier_create_role
            AND NOT role_posture.notifier_replication
            AND NOT role_posture.notifier_bypass_rls
            AND membership_posture.login_parent_count = 1
            AND membership_posture.notifier_membership_count = 1
            AND membership_posture.notifier_membership_options_safe
            AND membership_posture.notifier_child_count = 1
            AND membership_posture.notifier_parent_count = 0
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_db_role_setting AS role_setting
                WHERE role_setting.setrole IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_shdepend AS ownership
                WHERE ownership.refclassid =
                    'pg_catalog.pg_authid'::pg_catalog.regclass
                  AND ownership.refobjid IN (
                      role_posture.login_oid,
                      role_posture.notifier_oid
                  )
                  AND ownership.deptype = 'o'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_shdepend AS cross_database_acl
                WHERE cross_database_acl.refclassid =
                    'pg_catalog.pg_authid'::pg_catalog.regclass
                  AND cross_database_acl.refobjid IN (
                      role_posture.login_oid,
                      role_posture.notifier_oid
                  )
                  AND cross_database_acl.deptype = 'a'
                  AND cross_database_acl.dbid NOT IN (
                      0,
                      (
                          SELECT database.oid
                          FROM pg_catalog.pg_database AS database
                          WHERE database.datname =
                              pg_catalog.current_database()
                      )
                  )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_database AS database
                WHERE database.datdba IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_default_acl AS default_acl
                WHERE default_acl.defaclrole IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND (
                SELECT pg_catalog.count(*)
                FROM database_acl
                WHERE database_acl.grantee = role_posture.login_oid
            ) <= 1
            AND NOT EXISTS (
                SELECT 1
                FROM database_acl
                WHERE database_acl.grantee = role_posture.login_oid
                  AND (
                      database_acl.database_name <>
                          pg_catalog.current_database()
                      OR database_acl.privilege_type <> 'CONNECT'
                      OR database_acl.is_grantable
                  )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM database_acl
                WHERE database_acl.grantee = role_posture.notifier_oid
            )
            AND pg_catalog.has_database_privilege(
                role_posture.login_oid,
                pg_catalog.current_database(),
                'CONNECT'
            )
            AND NOT pg_catalog.has_database_privilege(
                role_posture.login_oid,
                pg_catalog.current_database(),
                'CREATE'
            )
            AND NOT pg_catalog.has_database_privilege(
                role_posture.login_oid,
                pg_catalog.current_database(),
                'TEMP'
            )
            AND NOT pg_catalog.has_database_privilege(
                role_posture.notifier_oid,
                pg_catalog.current_database(),
                'CREATE'
            )
            AND NOT pg_catalog.has_database_privilege(
                role_posture.notifier_oid,
                pg_catalog.current_database(),
                'TEMP'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_database AS other_database
                WHERE other_database.datallowconn
                  AND other_database.datname <>
                      pg_catalog.current_database()
                  AND (
                      pg_catalog.has_database_privilege(
                          role_posture.login_oid,
                          other_database.oid,
                          'CONNECT'
                      )
                      OR pg_catalog.has_database_privilege(
                          role_posture.notifier_oid,
                          other_database.oid,
                          'CONNECT'
                      )
                  )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM schema_acl
                WHERE schema_acl.grantee = role_posture.login_oid
            )
            AND (
                SELECT pg_catalog.count(*)
                FROM schema_acl
                WHERE schema_acl.grantee = role_posture.notifier_oid
            ) = 2
            AND NOT EXISTS (
                SELECT 1
                FROM schema_acl
                WHERE schema_acl.grantee = role_posture.notifier_oid
                  AND (
                      schema_acl.schema_name NOT IN ('loader_control', 'serve')
                      OR schema_acl.privilege_type <> 'USAGE'
                      OR schema_acl.is_grantable
                  )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM relation_acl
                WHERE relation_acl.grantee IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM column_acl
                WHERE column_acl.grantee IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM type_acl
                WHERE type_acl.grantee IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM routine_acl
                WHERE routine_acl.grantee = role_posture.login_oid
            )
            AND (
                SELECT pg_catalog.count(*)
                FROM routine_acl
                WHERE routine_acl.grantee = role_posture.notifier_oid
            ) = 6
            AND NOT EXISTS (
                SELECT 1
                FROM routine_acl
                WHERE routine_acl.grantee = role_posture.notifier_oid
                  AND (
                      routine_acl.privilege_type <> 'EXECUTE'
                      OR routine_acl.is_grantable
                      OR NOT EXISTS (
                          SELECT 1
                          FROM expected_function
                          WHERE expected_function.function_oid =
                              routine_acl.object_oid
                      )
                  )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM miscellaneous_acl
                WHERE miscellaneous_acl.grantee IN (
                    role_posture.login_oid,
                    role_posture.notifier_oid
                )
            )
            AND (
                SELECT pg_catalog.count(*)
                FROM application_schema
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.nspname = application_schema.schema_name
            ) = 4
            AND NOT EXISTS (
                SELECT 1
                FROM application_schema
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.nspname = application_schema.schema_name
                WHERE pg_catalog.has_schema_privilege(
                          role_posture.login_oid,
                          namespace.oid,
                          'CREATE'
                      )
                   OR pg_catalog.has_schema_privilege(
                          role_posture.notifier_oid,
                          namespace.oid,
                          'CREATE'
                      )
                   OR pg_catalog.has_schema_privilege(
                          role_posture.login_oid,
                          namespace.oid,
                          'USAGE'
                      ) IS DISTINCT FROM (
                          application_schema.schema_name IN (
                              'loader_control',
                              'serve'
                          )
                      )
                   OR pg_catalog.has_schema_privilege(
                          role_posture.notifier_oid,
                          namespace.oid,
                          'USAGE'
                      ) IS DISTINCT FROM (
                          application_schema.schema_name IN (
                              'loader_control',
                              'serve'
                          )
                      )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                JOIN application_schema
                    ON application_schema.schema_name = namespace.nspname
                WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND (
                      pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'SELECT'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'INSERT'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'UPDATE'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'TRUNCATE'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'REFERENCES'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.login_oid, relation.oid, 'TRIGGER'
                      )
                      OR pg_catalog.has_any_column_privilege(
                          role_posture.login_oid,
                          relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid, relation.oid, 'SELECT'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid, relation.oid, 'INSERT'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid, relation.oid, 'UPDATE'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid, relation.oid, 'DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid, relation.oid, 'TRUNCATE'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid,
                          relation.oid,
                          'REFERENCES'
                      )
                      OR pg_catalog.has_table_privilege(
                          role_posture.notifier_oid, relation.oid, 'TRIGGER'
                      )
                      OR pg_catalog.has_any_column_privilege(
                          role_posture.notifier_oid,
                          relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                  )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS sequence
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = sequence.relnamespace
                JOIN application_schema
                    ON application_schema.schema_name = namespace.nspname
                WHERE sequence.relkind = 'S'
                  AND (
                      pg_catalog.has_sequence_privilege(
                          role_posture.login_oid, sequence.oid, 'USAGE'
                      )
                      OR pg_catalog.has_sequence_privilege(
                          role_posture.login_oid, sequence.oid, 'SELECT'
                      )
                      OR pg_catalog.has_sequence_privilege(
                          role_posture.login_oid, sequence.oid, 'UPDATE'
                      )
                      OR pg_catalog.has_sequence_privilege(
                          role_posture.notifier_oid, sequence.oid, 'USAGE'
                      )
                      OR pg_catalog.has_sequence_privilege(
                          role_posture.notifier_oid, sequence.oid, 'SELECT'
                      )
                      OR pg_catalog.has_sequence_privilege(
                          role_posture.notifier_oid, sequence.oid, 'UPDATE'
                      )
                  )
            )
            AND (
                SELECT pg_catalog.count(*)
                FROM expected_function
                WHERE expected_function.function_oid IS NOT NULL
            ) = 6
            AND NOT EXISTS (
                SELECT 1
                FROM expected_function
                WHERE expected_function.function_oid IS NULL
                   OR NOT pg_catalog.has_function_privilege(
                       role_posture.login_oid,
                       expected_function.function_oid,
                       'EXECUTE'
                   )
                   OR NOT pg_catalog.has_function_privilege(
                       role_posture.notifier_oid,
                       expected_function.function_oid,
                       'EXECUTE'
                   )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = routine.pronamespace
                JOIN application_schema
                    ON application_schema.schema_name = namespace.nspname
                WHERE (
                        pg_catalog.has_function_privilege(
                            role_posture.login_oid,
                            routine.oid,
                            'EXECUTE'
                        )
                        OR pg_catalog.has_function_privilege(
                            role_posture.notifier_oid,
                            routine.oid,
                            'EXECUTE'
                        )
                    )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM expected_function
                      WHERE expected_function.function_oid = routine.oid
                  )
            )
        ) AS notifier_membership_only
    FROM loader_control.schema_migration AS m
    CROSS JOIN role_posture
    CROSS JOIN membership_posture
    WHERE m.migration_version = 2
      AND m.migration_key = '0002_notification_delivery'
$notification_worker_preflight$;

-- A function is executable by PUBLIC unless explicitly revoked.  Revoke every
-- new capability before granting only the reviewed worker/operator surfaces.
REVOKE ALL ON TABLE loader_control.notification_outbox,
    loader_control.notification_delivery_event,
    serve.etl_notification_status,
    serve.etl_notification_delivery_event
FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA loader_control FROM PUBLIC;

-- Migration 0001 gave brerc_loader table-level SELECT on the outbox.  Revoke
-- it before adding claim_token, otherwise PostgreSQL would automatically make
-- every active lease token readable by the loader.  The loader retains the
-- original observability fields plus non-secret bounded delivery state through
-- an explicit column grant, so future columns fail closed.
REVOKE SELECT ON TABLE loader_control.notification_outbox FROM brerc_loader;
GRANT SELECT (
    notification_id,
    job_id,
    release_id,
    event_type,
    destination_key,
    failure_code,
    status,
    attempt_count,
    available_at,
    locked_at,
    delivered_at,
    created_at,
    delivery_cycle,
    total_attempt_count,
    max_attempts,
    lease_expires_at,
    dead_lettered_at,
    last_delivery_failure_code
) ON loader_control.notification_outbox TO brerc_loader;

REVOKE ALL ON TABLE loader_control.notification_outbox,
    loader_control.notification_delivery_event
FROM brerc_notifier, brerc_notifier_operator;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA loader_control
FROM brerc_notifier, brerc_notifier_operator;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA loader_control
FROM brerc_notifier, brerc_notifier_operator;
REVOKE ALL ON FUNCTION loader_control.claim_notifications(integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION loader_control.renew_notification_lease(uuid, uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION loader_control.ack_notification(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION loader_control.fail_notification(uuid, uuid, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION loader_control.requeue_dead_notification(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serve.notification_delivery_metrics() FROM PUBLIC;
REVOKE ALL ON FUNCTION serve.notification_worker_preflight() FROM PUBLIC;

GRANT USAGE ON SCHEMA loader_control, serve TO brerc_notifier;
GRANT EXECUTE ON FUNCTION loader_control.claim_notifications(integer, integer)
TO brerc_notifier;
GRANT EXECUTE ON FUNCTION loader_control.renew_notification_lease(uuid, uuid, integer)
TO brerc_notifier;
GRANT EXECUTE ON FUNCTION loader_control.ack_notification(uuid, uuid)
TO brerc_notifier;
GRANT EXECUTE ON FUNCTION loader_control.fail_notification(uuid, uuid, text, integer)
TO brerc_notifier;
GRANT EXECUTE ON FUNCTION serve.notification_delivery_metrics()
TO brerc_notifier;
GRANT EXECUTE ON FUNCTION serve.notification_worker_preflight()
TO brerc_notifier;

GRANT USAGE ON SCHEMA loader_control, serve TO brerc_notifier_operator;
GRANT EXECUTE ON FUNCTION loader_control.requeue_dead_notification(uuid, text)
TO brerc_notifier_operator;
GRANT EXECUTE ON FUNCTION serve.notification_delivery_metrics()
TO brerc_notifier_operator;

GRANT SELECT ON serve.etl_notification_delivery_event TO brerc_monitor;
GRANT EXECUTE ON FUNCTION serve.notification_delivery_metrics() TO brerc_monitor;

INSERT INTO loader_control.schema_migration (
    migration_version,
    migration_key,
    migration_name
) VALUES (
    2,
    '0002_notification_delivery',
    'Leased notification delivery, bounded retry, dead letter and redrive audit'
);

COMMIT;

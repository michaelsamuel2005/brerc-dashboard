-- BRERC destination publication store -- migration 0002.
--
-- Makes the approval-bound sensitive-record action independently visible in
-- immutable release evidence and the reviewed serving capability view. Existing
-- pre-v2 development releases are truthfully labelled `generalise`, which was
-- the only sensitive-record behaviour supported by policy artifact v1.

BEGIN;

SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('brerc:destination-schema-migration', 0)
);

DO $migration_guard$
BEGIN
    IF pg_catalog.to_regclass('loader_control.schema_migration') IS NULL THEN
        RAISE EXCEPTION
            'BRERC migration 0001_publication_store is absent; refusing migration 0002';
    ELSIF EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 2
           OR migration_key = '0002_sensitive_record_action'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration 0002_sensitive_record_action is already applied; refusing to re-run';
    ELSIF (
        SELECT count(*)
        FROM loader_control.schema_migration
    ) <> 1 OR NOT EXISTS (
        SELECT 1
        FROM loader_control.schema_migration
        WHERE migration_version = 1
          AND migration_key = '0001_publication_store'
    ) THEN
        RAISE EXCEPTION
            'BRERC migration history is not exactly 0001; refusing out-of-order migration 0002';
    END IF;
END
$migration_guard$;

ALTER TABLE loader_control.release_manifest
    ADD COLUMN sensitive_record_action text NOT NULL DEFAULT 'generalise';
ALTER TABLE loader_control.release_manifest
    ALTER COLUMN sensitive_record_action DROP DEFAULT;
ALTER TABLE loader_control.release_manifest
    ADD CONSTRAINT release_manifest_sensitive_record_action CHECK (
        sensitive_record_action IN ('generalise', 'withhold')
    );

ALTER TABLE publication.public_release
    ADD COLUMN sensitive_record_action text NOT NULL DEFAULT 'generalise';
ALTER TABLE publication.public_release
    ALTER COLUMN sensitive_record_action DROP DEFAULT;
ALTER TABLE publication.public_release
    ADD CONSTRAINT public_release_sensitive_record_action CHECK (
        sensitive_record_action IN ('generalise', 'withhold')
    );

-- Both rows are written in one finalisation transaction. A deferred, symmetric
-- check lets either insert happen first while proving the committed values agree.
CREATE FUNCTION loader_control.enforce_sensitive_record_action_match()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $enforce_sensitive_record_action_match$
DECLARE
    manifest_action text;
    release_action text;
BEGIN
    SELECT m.sensitive_record_action
    INTO manifest_action
    FROM loader_control.release_manifest AS m
    WHERE m.release_id = NEW.release_id;

    SELECT p.sensitive_record_action
    INTO release_action
    FROM publication.public_release AS p
    WHERE p.release_id = NEW.release_id;

    IF manifest_action IS NOT NULL
       AND release_action IS NOT NULL
       AND manifest_action <> release_action
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'release sensitive-record action differs from immutable manifest';
    END IF;
    RETURN NEW;
END
$enforce_sensitive_record_action_match$;

CREATE CONSTRAINT TRIGGER release_manifest_sensitive_record_action_match
AFTER INSERT OR UPDATE OF sensitive_record_action
ON loader_control.release_manifest
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION loader_control.enforce_sensitive_record_action_match();

CREATE CONSTRAINT TRIGGER public_release_sensitive_record_action_match
AFTER INSERT OR UPDATE OF sensitive_record_action
ON publication.public_release
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION loader_control.enforce_sensitive_record_action_match();

CREATE OR REPLACE VIEW serve.public_release WITH (security_barrier = true) AS
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
    p.public_source_label,
    p.sensitive_record_action
FROM publication.public_release AS p
JOIN loader_control.release AS r
    ON r.release_id = p.release_id
   AND r.status = 'active'
JOIN loader_control.source_state AS s
    ON s.source_id = r.source_id
   AND s.active_release_id = r.release_id;

REVOKE ALL ON FUNCTION loader_control.enforce_sensitive_record_action_match() FROM PUBLIC;

INSERT INTO loader_control.schema_migration (
    migration_version,
    migration_key,
    migration_name
) VALUES (
    2,
    '0002_sensitive_record_action',
    'Approval-bound sensitive-record action and serving evidence'
);

COMMIT;

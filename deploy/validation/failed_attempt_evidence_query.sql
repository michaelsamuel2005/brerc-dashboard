\set ON_ERROR_STOP on

-- Bounded, privacy-safe evidence for a loader invocation that emitted no
-- successful terminal result document. Execute only through the approved
-- brerc_monitor service. The first statement fails closed unless the supplied
-- target, login, read-only state and sole inherited capability role match.
-- Operators must require zero or one returned job in the approved database
-- window; more than one is ambiguous and blocks any retry. The psql guard emits
-- one row (\gset) and ON_ERROR_STOP makes a wrong target/session, bad mode,
-- reversed/empty window or interval over four hours exit nonzero instead of
-- resembling a zero-job run.
SELECT 1 / CASE
    WHEN :'load_mode'::text IN ('initial', 'refresh')
     AND :'window_end'::timestamp with time zone
         > :'window_start'::timestamp with time zone
     AND :'window_end'::timestamp with time zone
         - :'window_start'::timestamp with time zone <= interval '4 hours'
     AND current_database()::text = :'expected_database'::text
     AND current_user::text = :'expected_role'::text
     AND session_user::text = :'expected_role'::text
     AND current_setting('transaction_read_only') = 'on'
     AND (SELECT NOT role.rolsuper
          FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = current_user)
     AND (SELECT role.rolcanlogin
          FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = current_user)
     AND (SELECT NOT role.rolcreatedb
          FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = current_user)
     AND (SELECT NOT role.rolcreaterole
          FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = current_user)
     AND (SELECT NOT role.rolreplication
          FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = current_user)
     AND (SELECT NOT role.rolbypassrls
          FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = current_user)
     AND ARRAY(
         SELECT role.rolname::text
         FROM pg_catalog.pg_roles AS role
         WHERE role.rolname <> current_user
           AND pg_catalog.pg_has_role(current_user, role.oid, 'USAGE')
         ORDER BY role.rolname
     ) = ARRAY['brerc_monitor']::text[]
     AND ARRAY(
         SELECT parent.rolname::text
         FROM pg_catalog.pg_auth_members AS membership
         JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
         JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid
         WHERE member.rolname = current_user
         ORDER BY parent.rolname
     ) = ARRAY['brerc_monitor']::text[]
     AND (
         SELECT pg_catalog.count(*) = 1
         FROM serve.etl_monitor_identity AS identity
         WHERE identity.environment_id = :'expected_environment_id'::uuid
           AND identity.database_name = current_database()
     )
    THEN 1
    ELSE 0
END AS evidence_parameters_valid \gset

WITH matching_job AS (
    SELECT job.*, release.release_id, release.status AS release_status,
           release.cleanup_pending
    FROM serve.etl_job_status AS job
    LEFT JOIN serve.etl_release_status AS release USING (job_id)
    WHERE job.source_id = 'dashboard.main_data_dash'
      AND job.load_mode = :'load_mode'::text
      AND job.created_at >= :'window_start'::timestamp with time zone
      AND job.created_at <= :'window_end'::timestamp with time zone
), aggregated AS (
    SELECT
        pg_catalog.count(*) AS job_count,
        COALESCE(
            pg_catalog.jsonb_agg(
                pg_catalog.jsonb_build_object(
                    'runId', job.job_id::text,
                    'status', job.status,
                    'failureCode', job.failure_code,
                    'startedAt', job.started_at,
                    'finishedAt', job.finished_at,
                    'sourceRows', job.source_rows_seen,
                    'candidateRows', job.candidate_rows,
                    'rowsWithheld', job.rows_withheld,
                    'releaseId', job.release_id::text,
                    'releaseStatus', job.release_status,
                    'cleanupPending', job.cleanup_pending
                ) ORDER BY job.created_at, job.job_id
            ),
            '[]'::jsonb
        ) AS jobs
    FROM matching_job AS job
)
SELECT pg_catalog.jsonb_build_object(
    'environmentId', identity.environment_id::text,
    'databaseName', current_database()::text,
    'loginRole', current_user::text,
    'sessionRole', session_user::text,
    'readOnly', current_setting('transaction_read_only'),
    'isSuperuser', role.rolsuper,
    'canLogin', role.rolcanlogin,
    'canCreateDb', role.rolcreatedb,
    'canCreateRole', role.rolcreaterole,
    'canReplicate', role.rolreplication,
    'canBypassRls', role.rolbypassrls,
    'effectiveRoles', ARRAY(
        SELECT candidate.rolname::text
        FROM pg_catalog.pg_roles AS candidate
        WHERE candidate.rolname <> current_user
          AND pg_catalog.pg_has_role(current_user, candidate.oid, 'USAGE')
        ORDER BY candidate.rolname
    ),
    'directRoles', ARRAY(
        SELECT parent.rolname::text
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid
        WHERE member.rolname = current_user
        ORDER BY parent.rolname
    ),
    'windowStart', :'window_start'::timestamp with time zone,
    'windowEnd', :'window_end'::timestamp with time zone,
    'loadMode', :'load_mode'::text,
    'jobCount', aggregated.job_count,
    'jobs', aggregated.jobs
)::text
FROM serve.etl_monitor_identity AS identity
CROSS JOIN aggregated
JOIN pg_catalog.pg_roles AS role ON role.rolname = current_user;

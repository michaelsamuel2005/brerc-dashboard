\set ON_ERROR_STOP on

-- Execute through the protected brerc_monitor service, one loader run UUID and
-- independently approved destination/session identity values:
--   psql ... --tuples-only --no-align --set=run_id='UUID' \
--     --set=expected_environment_id='UUID' --set=expected_database='NAME' \
--     --set=expected_role='LOGIN' \
--     --file=release_evidence_query.sql > database.json
-- The result contains identifiers, counts and digests, never source row values,
-- coordinates, credentials, connection details or exception text.
SELECT 1 / CASE
    WHEN current_database()::text = :'expected_database'::text
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
    'runId', evidence.run_id::text,
    'releaseId', evidence.release_id::text,
    'activeReleaseId', evidence.active_release_id::text,
    'datasetVersion', evidence.dataset_version,
    'sourceDataAsOf', evidence.source_data_as_of,
    'candidateSha256', evidence.candidate_sha256,
    'baseReleaseId', evidence.base_release_id::text,
    'reusedActiveRelease', evidence.reused_active_release,
    'sourceRows', evidence.source_rows,
    'publicRecords', evidence.public_records,
    'distributionCells', evidence.distribution_cells,
    'loadMode', evidence.load_mode,
    'status', evidence.status,
    'startedAt', evidence.started_at,
    'finishedAt', evidence.finished_at
)::text
FROM serve.etl_release_evidence AS evidence
JOIN serve.etl_monitor_identity AS identity ON true
JOIN pg_catalog.pg_roles AS role ON role.rolname = current_user
WHERE evidence.run_id = :'run_id'::uuid;

\set ON_ERROR_STOP on

-- Execute through the protected brerc_monitor service and one loader run UUID:
--   psql ... --tuples-only --no-align --set=run_id='UUID' \
--     --file=release_evidence_query.sql > database.json
-- The result contains identifiers, counts and digests, never source row values,
-- coordinates, credentials, connection details or exception text.
SELECT pg_catalog.jsonb_build_object(
    'runId', evidence.run_id::text,
    'releaseId', evidence.release_id::text,
    'activeReleaseId', evidence.active_release_id::text,
    'datasetVersion', evidence.dataset_version,
    'candidateSha256', evidence.candidate_sha256,
    'baseReleaseId', evidence.base_release_id::text,
    'reusedActiveRelease', evidence.reused_active_release,
    'sourceRows', evidence.source_rows,
    'publicRecords', evidence.public_records,
    'distributionCells', evidence.distribution_cells,
    'loadMode', evidence.load_mode,
    'status', evidence.status
)::text
FROM serve.etl_release_evidence AS evidence
WHERE evidence.run_id = :'run_id'::uuid;

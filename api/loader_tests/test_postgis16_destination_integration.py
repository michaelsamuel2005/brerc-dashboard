"""Real PostgreSQL 16/PostGIS destination tests using synthetic safe rows only.

CI provisions the reviewed roles and migration over TLS, then enables this
module with ``BRERC_LOADER_PG_INTEGRATION=1``.  These tests exercise the real
Psycopg target store and database-owned activation gates; they never contain or
connect to BRERC client data.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import unittest
from contextlib import suppress
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from brerc_loader import postgres as loader_coordinator
from brerc_loader.config import (
    LoaderConfig,
    LoaderRuntimeConfig,
    PublicationConfig,
    ReconciliationConfig,
    TargetConnectionConfig,
)
from brerc_loader.errors import (
    LoaderAlreadyRunning,
    LoaderCandidateInvalid,
    LoaderCleanupPending,
    LoaderError,
    LoaderTargetProtocolError,
)
from brerc_loader.postgres import (
    SOURCE_ID,
    _CandidateHandle,
    _PostgreSQLTargetStore,
)
from brerc_source.config import (
    BRERC_SOURCE_APPLICATION_NAME,
    ConnectionConfig,
    SourceConnectorConfig,
    SourceLocation,
)
from brerc_source.config import (
    RuntimeConfig as SourceRuntimeConfig,
)
from brerc_source.models import SafeSourceSnapshotEvidence
from brerc_source.postgres import (
    BEGIN_SQL as SOURCE_BEGIN_SQL,
)
from brerc_source.postgres import (
    CATALOG_CAPTURE_SQL as SOURCE_CATALOG_CAPTURE_SQL,
)
from brerc_source.postgres import (
    CATALOG_HEADER as SOURCE_CATALOG_HEADER,
)
from brerc_source.postgres import (
    FIXED_SESSION_SQL as SOURCE_FIXED_SESSION_SQL,
)
from brerc_source.postgres import (
    _capture_document as capture_source_document,
)
from connector_tests.test_postgres_connector import (
    PROJECTION,
    VIEW_COLUMNS,
    approved_contract,
    approved_policy,
)
from etl.contract import PublicRecord
from etl.source_contract import BRERC_MAIN_DATA_DASH
from etl.streaming import SafeDisposition
from etl.view_identity import ViewCaptureEvidence, ViewDefinitionApproval

ENABLED = os.environ.get("BRERC_LOADER_PG_INTEGRATION") == "1"
REPO_ROOT = Path(__file__).resolve().parents[2]

ROLE_LOGINS = {
    "loader": "brerc_release_loader_test",
    "api": "brerc_api_test",
    "martin": "brerc_martin_test",
    "monitor": "brerc_monitor_test",
}
ROLE_GROUPS = {
    "loader": "brerc_loader",
    "api": "brerc_api",
    "martin": "brerc_martin",
    "monitor": "brerc_monitor",
}


def _policy(
    *,
    threshold: int = 1,
    allowed_licence_values: frozenset[str] | None = None,
):
    policy = approved_policy()
    if threshold == 1 and allowed_licence_values is None:
        return policy
    policy = dataclasses.replace(
        policy,
        suppression_mode=("minimum-count" if threshold > 1 else policy.suppression_mode),
        min_records_per_cell=threshold,
        licensing_mode=(
            "all-publication-allow-list"
            if allowed_licence_values is not None
            else policy.licensing_mode
        ),
        allowed_licence_values=allowed_licence_values,
        approval_digest=None,
    )
    policy = dataclasses.replace(
        policy,
        approval_digest=policy._expected_approval_digest(),
    )
    policy.validate()
    policy.assert_approved()
    return policy


def _policy_artifact(policy: object) -> bytes:
    return json.dumps(
        policy.approval_artifact(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _loader_config(policy: object) -> LoaderConfig:
    runtime = LoaderRuntimeConfig(
        expected_target_database="brerc_ui_integration",
        expected_target_environment_id=UUID(os.environ["BRERC_TARGET_ENVIRONMENT_ID"]),
        expected_target_role=ROLE_LOGINS["loader"],
        batch_size=100,
        initial_min_source_rows=1,
        initial_max_source_rows=10_000,
        connect_timeout_seconds=5,
        lock_timeout_ms=2_000,
        statement_timeout_ms=60_000,
        total_timeout_seconds=300,
    )
    artifact = _policy_artifact(policy)
    public_secret = policy.public_id_salt
    if not isinstance(public_secret, str):
        raise AssertionError("synthetic policy lost its public-id key")
    service_file = os.environ["PGSERVICEFILE"]
    return LoaderConfig(
        version="brerc-loader-v1",
        source_config_path=Path("/synthetic/source.configuration.yaml"),
        publication=PublicationConfig(
            policy_path=Path("/synthetic/publication-policy.json"),
            expected_sha256=hashlib.sha256(artifact).hexdigest(),
            public_id_secret_env="SYNTHETIC_PUBLIC_ID_SECRET",  # noqa: S106 - env name
            _artifact=artifact,
            _public_id_secret=public_secret.encode("utf-8"),
        ),
        runtime=runtime,
        target_connection=TargetConnectionConfig(
            mode="service",
            sslmode="verify-full",
            connect_timeout_seconds=runtime.connect_timeout_seconds,
            _resolved_parameters=(
                ("service", os.environ["BRERC_TARGET_SERVICE"]),
                ("passfile", os.environ["BRERC_TARGET_PASSFILE"]),
                ("sslrootcert", os.environ["BRERC_TARGET_SSLROOTCERT"]),
                ("sslmode", "verify-full"),
                ("application_name", "brerc-dashboard-release-loader"),
                ("connect_timeout", runtime.connect_timeout_seconds),
            ),
            _service_file_path=service_file,
        ),
        reconciliation=ReconciliationConfig(
            secret_env="SYNTHETIC_RECONCILIATION_SECRET",  # noqa: S106 - env name
            _secret=b"synthetic-reconciliation-secret-32-bytes",
        ),
    )


def _disposition(
    number: int,
    *,
    species_id: str = "SYNTH-1",
    scientific_name: str = "Synthetic species alpha",
    common_name: str | None = "Synthetic alpha",
    year: int = 2024,
    cell_id: str = "ST5872",
    public_record_id: str | None = None,
) -> SafeDisposition:
    if cell_id == "ST5872":
        grid_ref = "ST587721"
        bounds = (358_000, 172_000, 359_000, 173_000)
    elif cell_id == "ST5972":
        grid_ref = "ST597221"
        bounds = (359_000, 172_000, 360_000, 173_000)
    else:
        raise AssertionError("synthetic fixture supports exactly two reviewed cells")
    record_id = (
        public_record_id or hashlib.sha256(f"synthetic-public:{number}".encode()).hexdigest()[:32]
    )
    return SafeDisposition(
        source_token=hashlib.sha256(f"synthetic-token:{number}".encode()).hexdigest(),
        source_fingerprint=hashlib.sha256(f"synthetic-fingerprint:{number}".encode()).hexdigest(),
        record=PublicRecord(
            record_id=record_id,
            species_id=species_id,
            scientific_name=scientific_name,
            common_name=common_name,
            grid_ref=grid_ref,
            precision_metres=100,
            place=None,
            year=year,
            abundance=None,
            record_type=None,
            verified="unknown",
            source="BRERC",
        ),
        withheld_reason=None,
        cell_id=cell_id,
        cell_precision_metres=1_000,
        min_easting=bounds[0],
        min_northing=bounds[1],
        max_easting=bounds[2],
        max_northing=bounds[3],
    )


def _withheld(number: int, *, reason: str = "licence-not-approved") -> SafeDisposition:
    return SafeDisposition(
        source_token=hashlib.sha256(f"synthetic-token:{number}".encode()).hexdigest(),
        source_fingerprint=hashlib.sha256(f"synthetic-fingerprint:{number}".encode()).hexdigest(),
        record=None,
        withheld_reason=reason,
        cell_id=None,
        cell_precision_metres=None,
        min_easting=None,
        min_northing=None,
        max_easting=None,
        max_northing=None,
    )


def _evidence(policy: object, rows: tuple[SafeDisposition, ...]) -> SafeSourceSnapshotEvidence:
    contract = approved_contract()
    approval = contract.view_approval
    if approval is None or policy.approval_digest is None:
        raise AssertionError("synthetic approval fixture is incomplete")
    withheld = sum(item.record is None for item in rows)
    return SafeSourceSnapshotEvidence(
        captured_at_utc="2026-08-14T12:00:00.000000Z",
        contract_version=contract.version,
        contract_sha256=contract.digest(),
        policy_version=policy.version,
        policy_approval_digest=policy.approval_digest,
        observed_definition_sha256=approval.definition_sha256,
        observed_identity_sha256=approval.identity_sha256,
        result_columns=PROJECTION,
        rows_seen=len(rows),
        records_eligible_before_suppression=len(rows) - withheld,
        withheld_by_reason=((("licence-not-approved", withheld),) if withheld else ()),
        sensitivity_buckets=(("no", len(rows)),),
    )


@unittest.skipUnless(ENABLED, "requires the synthetic PostgreSQL 16/PostGIS TLS service")
class TestPostGIS16DestinationIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg
        from psycopg import ClientCursor
        from psycopg.rows import dict_row

        cls.psycopg = psycopg
        cls.ClientCursor = ClientCursor
        cls.dict_row = dict_row
        cls.e2e_source_contract = cls._capture_e2e_source_contract()
        cls.e2e_source_config = cls._build_e2e_source_config(cls.e2e_source_contract)

    @classmethod
    def _source_parameters(cls, *, administrator: bool = False) -> dict[str, object]:
        parameters: dict[str, object] = {
            "host": os.environ["BRERC_LOADER_E2E_SOURCE_HOST"],
            "port": int(os.environ["BRERC_LOADER_E2E_SOURCE_PORT"]),
            "dbname": os.environ["BRERC_LOADER_E2E_SOURCE_DATABASE"],
            "sslrootcert": os.environ["BRERC_LOADER_E2E_SOURCE_SSLROOTCERT"],
            "sslmode": "verify-full",
            "application_name": (
                "synthetic-e2e-source-admin" if administrator else BRERC_SOURCE_APPLICATION_NAME
            ),
            "connect_timeout": 5,
        }
        if administrator:
            parameters.update(
                user="postgres",
                password=os.environ["BRERC_LOADER_E2E_SOURCE_ADMIN_SECRET"],
            )
        else:
            parameters.update(
                user=os.environ["BRERC_LOADER_E2E_SOURCE_USER"],
                passfile=os.environ["BRERC_LOADER_E2E_SOURCE_PASSFILE"],
            )
        return parameters

    @classmethod
    def _capture_e2e_source_contract(cls):
        connection = cls.psycopg.connect(
            autocommit=True,
            row_factory=cls.dict_row,
            **cls._source_parameters(),
        )
        cursor = connection.cursor()
        try:
            cursor.execute(SOURCE_BEGIN_SQL)
            for statement in SOURCE_FIXED_SESSION_SQL:
                cursor.execute(statement)
            cursor.execute('LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE')
            cursor.execute(
                SOURCE_CATALOG_CAPTURE_SQL,
                ("dashboard", "main_data_dash", "dashboard", "main_data_dash"),
            )
            self_header = tuple(item.name for item in cursor.description)
            if self_header != SOURCE_CATALOG_HEADER:
                raise AssertionError("synthetic source catalogue header drifted")
            row = cursor.fetchone()
            if row is None or cursor.fetchone() is not None:
                raise AssertionError("synthetic source catalogue capture was not singular")
            evidence = ViewCaptureEvidence.from_document(capture_source_document(row))
        finally:
            cursor.close()
            connection.rollback()
            connection.close()

        observation = evidence.observation
        if not 160000 <= observation.postgres_server_version_num < 170000:
            raise AssertionError("synthetic loader source is not PostgreSQL 16")
        version = "synthetic-loader-e2e-source-v1"
        approval = ViewDefinitionApproval(
            source_version=version,
            source_environment="synthetic-loader-e2e",
            client_reference_document_sha256=(
                BRERC_MAIN_DATA_DASH.client_reference_document_sha256
            ),
            schema=observation.schema,
            name=observation.name,
            relkind=observation.relkind,
            postgres_server_version_num=observation.postgres_server_version_num,
            owner=observation.owner,
            reloptions=observation.reloptions,
            columns_sha256=BRERC_MAIN_DATA_DASH.columns_sha256(),
            catalog_columns_sha256=evidence.catalog_columns_sha256,
            definition_sha256=observation.definition_sha256,
            capture_evidence_sha256=evidence.capture_sha256,
            approved_by="Synthetic CI source owner",
            approver_role="Synthetic integration test owner",
            approver_organisation="BRERC",
            captured_at_utc=evidence.captured_at_utc,
            approved_on=date.today().isoformat(),
            evidence_reference="SYNTHETIC-LOADER-E2E-CI-ONLY",
        )
        return dataclasses.replace(
            BRERC_MAIN_DATA_DASH,
            version=version,
            required_source_environment="synthetic-loader-e2e",
            view_approval=approval,
            release_blockers=(),
        )

    @classmethod
    def _build_e2e_source_config(cls, contract) -> SourceConnectorConfig:
        runtime = SourceRuntimeConfig(
            source_environment="synthetic-loader-e2e",
            expected_database=os.environ["BRERC_LOADER_E2E_SOURCE_DATABASE"],
            expected_role=os.environ["BRERC_LOADER_E2E_SOURCE_USER"],
            # Production deliberately enforces a minimum fetch window of 100.
            # The three-row fixture is nevertheless one bounded real stream;
            # unit tests separately prove rechunking and boundary invariance.
            batch_size=100,
            connect_timeout_seconds=5,
            lock_timeout_ms=2_000,
            statement_timeout_ms=60_000,
            idle_in_transaction_session_timeout_ms=10_000,
            total_timeout_seconds=300,
        )
        return SourceConnectorConfig(
            contract_version=contract.version,
            runtime=runtime,
            connection=ConnectionConfig(
                mode="direct",
                sslmode="verify-full",
                connect_timeout_seconds=runtime.connect_timeout_seconds,
                _resolved_parameters=tuple(cls._source_parameters().items()),
            ),
            source=SourceLocation(
                engine="postgresql",
                schema=contract.schema,
                object=contract.name,
                object_type=contract.object_type,
                strict_schema=True,
            ),
            source_columns=tuple(column.name for column in contract.columns),
            projection=PROJECTION,
            column_map=VIEW_COLUMNS,
        )

    def setUp(self) -> None:
        with self._admin_connection() as connection:
            connection.execute("TRUNCATE TABLE loader_control.source_state CASCADE")

    def _parameters(self, capability: str) -> dict[str, object]:
        return {
            "host": os.environ["BRERC_DESTINATION_HOST"],
            "port": int(os.environ["BRERC_DESTINATION_PORT"]),
            "dbname": os.environ["BRERC_DESTINATION_DATABASE"],
            "user": ROLE_LOGINS[capability],
            "passfile": os.environ["BRERC_TARGET_PASSFILE"],
            "sslrootcert": os.environ["BRERC_TARGET_SSLROOTCERT"],
            "sslmode": "verify-full",
            "application_name": f"synthetic-{capability}-integration",
        }

    def _connection(self, capability: str):
        return self.psycopg.connect(
            autocommit=True,
            row_factory=self.dict_row,
            **self._parameters(capability),
        )

    def _admin_connection(self, *, autocommit: bool = True):
        return self.psycopg.connect(
            autocommit=autocommit,
            row_factory=self.dict_row,
            host=os.environ["BRERC_DESTINATION_HOST"],
            port=int(os.environ["BRERC_DESTINATION_PORT"]),
            dbname=os.environ["BRERC_DESTINATION_DATABASE"],
            user="postgres",
            password=os.environ["BRERC_PG_ADMIN_SECRET"],
            sslrootcert=os.environ["BRERC_TARGET_SSLROOTCERT"],
            sslmode="verify-full",
            application_name="synthetic-destination-test-admin",
        )

    def _source_admin_connection(self):
        return self.psycopg.connect(
            autocommit=True,
            row_factory=self.dict_row,
            **self._source_parameters(administrator=True),
        )

    def _store(
        self,
        policy: object,
        *,
        config: LoaderConfig | None = None,
    ) -> _PostgreSQLTargetStore:
        store = _PostgreSQLTargetStore(config or _loader_config(policy))

        def close_safely() -> None:
            with suppress(Exception):
                store.close()

        self.addCleanup(close_safely)
        return store

    def _finalized(
        self,
        rows: tuple[SafeDisposition, ...],
        *,
        policy: object,
        batches: tuple[tuple[SafeDisposition, ...], ...] | None = None,
    ):
        store = self._store(policy)
        store.acquire(SOURCE_ID)
        handle = store.begin_initial(
            SOURCE_ID,
            _CandidateHandle(job_id=uuid4(), release_id=uuid4(), base_release_id=None),
        )
        for batch in batches or (rows,):
            store.stage_batch(handle, batch)
        contract = approved_contract()
        summary = store.finalize(
            handle,
            evidence=_evidence(policy, rows),
            policy=policy,
            source_contract=contract,
            projection=PROJECTION,
            policy_artifact_sha256=_loader_config(policy).publication.expected_sha256,
        )
        return store, handle, summary

    def _activate_rows(
        self,
        rows: tuple[SafeDisposition, ...],
        *,
        policy: object,
        batches: tuple[tuple[SafeDisposition, ...], ...] | None = None,
    ):
        store, handle, summary = self._finalized(
            rows,
            policy=policy,
            batches=batches,
        )
        activation = store.activate(handle, summary)
        return store, handle, summary, activation

    def _install_incremental_clone(
        self,
        *,
        store: _PostgreSQLTargetStore,
        base_release: UUID,
        upper_token: bytes,
    ) -> _CandidateHandle:
        """Install an otherwise-valid unchanged incremental candidate.

        Production incremental loading is intentionally blocked.  This helper
        exists only to attack the database function that must remain safe even
        if a later worker hand-builds a bad candidate. Durable rows are inserted
        through the lock-owning loader session while the job is reconciling, so
        this fixture obeys the same database invariant as normal finalisation.
        """
        candidate = _CandidateHandle(
            job_id=uuid4(),
            release_id=uuid4(),
            base_release_id=base_release,
        )
        lower_date = date(2026, 8, 13)
        upper_date = date(2026, 8, 14)
        with self._admin_connection() as admin:
            lower_token = admin.execute(
                """
                SELECT source_key_token
                FROM loader_control.source_disposition
                WHERE release_id = %s
                ORDER BY source_key_token DESC
                LIMIT 1
                """,
                (base_release,),
            ).fetchone()["source_key_token"]
            admin.execute(
                """
                UPDATE loader_control.source_state
                SET last_successful_modified_date = %s,
                    last_successful_modified_key_token = %s
                WHERE source_id = %s AND active_release_id = %s
                """,
                (lower_date, lower_token, SOURCE_ID, base_release),
            )
            # The context manager still owns and closes the administrative
            # connection. From here onward every insert deliberately uses the
            # concrete loader cursor that owns the source advisory lock.
            admin = store._cursor
            admin.execute(
                """
                INSERT INTO loader_control.etl_job (
                    job_id, source_id, load_mode, base_release_id,
                    started_at, heartbeat_at
                ) VALUES (%s, %s, 'incremental', %s,
                          transaction_timestamp(), transaction_timestamp())
                """,
                (candidate.job_id, SOURCE_ID, base_release),
            )
            admin.execute(
                """
                UPDATE loader_control.etl_job
                SET status = 'reconciling'
                WHERE job_id = %s AND status = 'queued'
                """,
                (candidate.job_id,),
            )
            admin.execute(
                """
                INSERT INTO loader_control.release (
                    release_id, source_id, job_id, base_release_id, load_mode, status
                ) VALUES (%s, %s, %s, %s, 'incremental', 'candidate')
                """,
                (candidate.release_id, SOURCE_ID, candidate.job_id, base_release),
            )
            # Candidate-write authority is deliberately transaction-local. The
            # helper therefore opens the same explicit transaction used for all
            # guarded durable inserts and proves the authoriser returned the
            # exact candidate before writing any payload.
            admin.execute("BEGIN")
            authorised = admin.execute(
                "SELECT loader_control.authorize_candidate_writes(%s) AS release_id",
                (candidate.release_id,),
            ).fetchone()
            if authorised != {"release_id": candidate.release_id}:
                raise AssertionError("candidate write authority returned the wrong release")
            admin.execute(
                """
                INSERT INTO loader_control.source_disposition (
                    release_id, source_key_token, input_fingerprint, disposition,
                    withheld_reason, species_id, scientific_name, common_name,
                    record_grid_ref, record_precision_metres, cell_id,
                    cell_precision_metres, min_easting, min_northing, max_easting,
                    max_northing, record_year, public_record_id, place, abundance,
                    record_type, verified_status, source_label
                )
                SELECT
                    %s, source_key_token, input_fingerprint, disposition,
                    withheld_reason, species_id, scientific_name, common_name,
                    record_grid_ref, record_precision_metres, cell_id,
                    cell_precision_metres, min_easting, min_northing, max_easting,
                    max_northing, record_year, public_record_id, place, abundance,
                    record_type, verified_status, source_label
                FROM loader_control.source_disposition
                WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO loader_stage.source_inventory (
                    job_id, source_key_token, input_fingerprint, observed_modified_date
                )
                SELECT %s, source_key_token, input_fingerprint, %s
                FROM loader_control.source_disposition
                WHERE release_id = %s
                """,
                (candidate.job_id, upper_date, candidate.release_id),
            )
            admin.execute(
                """
                INSERT INTO publication.public_release (
                    release_id, source_data_as_of, publication_policy_version,
                    dataset_version, suppression_mode, min_records_per_cell,
                    verification_available, individual_records_available,
                    record_verification_available, place_available, abundance_available,
                    record_type_available, public_source_label
                )
                SELECT
                    %s, source_data_as_of, publication_policy_version,
                    dataset_version, suppression_mode, min_records_per_cell,
                    verification_available, individual_records_available,
                    record_verification_available, place_available, abundance_available,
                    record_type_available, public_source_label
                FROM publication.public_release
                WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO publication.public_species (
                    release_id, species_id, scientific_name, common_name, taxon_group,
                    total_records, first_year, last_year
                )
                SELECT %s, species_id, scientific_name, common_name, taxon_group,
                       total_records, first_year, last_year
                FROM publication.public_species WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO publication.public_distribution_cell (
                    release_id, species_id, record_year, cell_id, precision_metres,
                    record_count, verified_count, geom
                )
                SELECT %s, species_id, record_year, cell_id, precision_metres,
                       record_count, verified_count, geom
                FROM publication.public_distribution_cell WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO publication.public_species_year (
                    release_id, species_id, record_year, record_count, verified_count
                )
                SELECT %s, species_id, record_year, record_count, verified_count
                FROM publication.public_species_year WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO publication.public_record (
                    release_id, public_record_id, species_id, scientific_name, common_name,
                    grid_ref, precision_metres, place, record_year, abundance, record_type,
                    verified_status, source_label
                )
                SELECT %s, public_record_id, species_id, scientific_name, common_name,
                       grid_ref, precision_metres, place, record_year, abundance, record_type,
                       verified_status, source_label
                FROM publication.public_record WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO loader_control.withheld_summary (
                    release_id, reason_code, row_count
                )
                SELECT %s, reason_code, row_count
                FROM loader_control.withheld_summary WHERE release_id = %s
                """,
                (candidate.release_id, base_release),
            )
            admin.execute(
                """
                INSERT INTO loader_control.release_manifest (
                    release_id, source_snapshot_at,
                    lower_modified_date, lower_modified_key_token,
                    upper_modified_date, upper_modified_key_token,
                    source_contract_version, source_contract_sha256,
                    observed_view_definition_sha256, observed_view_identity_sha256,
                    projection_version, projection_sha256,
                    publication_policy_version, publication_policy_sha256,
                    policy_approval_sha256, suppression_mode, min_records_per_cell,
                    etl_version, compatibility_sha256, species_dictionary_sha256,
                    sensitivity_snapshot_sha256, source_row_count,
                    source_inventory_count, delta_row_count,
                    eligible_pre_suppression_count, transform_withheld_count,
                    suppression_withheld_count, published_basis_count, species_count,
                    cell_count, species_year_count, public_record_count,
                    source_result_sha256, candidate_sha256, database_sha256
                )
                SELECT
                    %s, source_snapshot_at,
                    %s, %s, %s, %s,
                    source_contract_version, source_contract_sha256,
                    observed_view_definition_sha256, observed_view_identity_sha256,
                    projection_version, projection_sha256,
                    publication_policy_version, publication_policy_sha256,
                    policy_approval_sha256, suppression_mode, min_records_per_cell,
                    etl_version, compatibility_sha256, species_dictionary_sha256,
                    sensitivity_snapshot_sha256, source_row_count,
                    source_inventory_count, 0,
                    eligible_pre_suppression_count, transform_withheld_count,
                    suppression_withheld_count, published_basis_count, species_count,
                    cell_count, species_year_count, public_record_count,
                    source_result_sha256, candidate_sha256, database_sha256
                FROM loader_control.release_manifest
                WHERE release_id = %s
                """,
                (
                    candidate.release_id,
                    lower_date,
                    lower_token,
                    upper_date,
                    upper_token,
                    base_release,
                ),
            )
            admin.execute(
                """
                INSERT INTO loader_stage.reconciliation_result (
                    job_id, check_code, expected_count, actual_count, passed
                )
                SELECT %s, check_code, 0, 0, true
                FROM (VALUES
                    ('SOURCE_INVENTORY'),
                    ('SOURCE_DISPOSITIONS'),
                    ('PUBLIC_CELL_TOTAL'),
                    ('PUBLIC_SPECIES_YEAR_TOTAL'),
                    ('PUBLIC_SPECIES_TOTAL'),
                    ('PRIVACY_ALLOWLIST'),
                    ('DATABASE_DIGEST'),
                    ('ACTIVATION_THRESHOLDS')
                ) AS required(check_code)
                """,
                (candidate.job_id,),
            )
            admin.execute(
                """
                UPDATE loader_control.etl_job
                SET status = 'activating'
                WHERE job_id = %s AND status = 'reconciling'
                """,
                (candidate.job_id,),
            )
            admin.execute("COMMIT")
        return candidate

    def test_migration_postgis_tls_and_real_login_memberships(self) -> None:
        # Construct the concrete store through its hostile service profile.
        # Explicit mandatory TLS/application parameters must win over the
        # profile's sslmode=disable and misleading application name.
        service_store = self._store(_policy())
        service_session = service_store._cursor.execute(
            """
            SELECT current_user AS current_user_name,
                   current_setting('application_name') AS application_name,
                   ssl
            FROM pg_catalog.pg_stat_ssl
            WHERE pid = pg_catalog.pg_backend_pid()
            """
        ).fetchone()
        self.assertEqual(
            service_session,
            {
                "current_user_name": ROLE_LOGINS["loader"],
                "application_name": "brerc-dashboard-release-loader",
                "ssl": True,
            },
        )
        service_store.close()

        with self._connection("loader") as connection:
            row = connection.execute(
                """
                SELECT
                    current_user AS current_user_name,
                    session_user AS session_user_name,
                    ssl,
                    current_setting('application_name') AS application_name,
                    current_setting('server_version_num')::integer AS server_version_num,
                    public.postgis_lib_version() AS postgis_version
                FROM pg_catalog.pg_stat_ssl
                WHERE pid = pg_catalog.pg_backend_pid()
                """
            ).fetchone()
            self.assertEqual(row["current_user_name"], ROLE_LOGINS["loader"])
            self.assertEqual(row["session_user_name"], ROLE_LOGINS["loader"])
            self.assertTrue(row["ssl"])
            self.assertEqual(row["application_name"], "synthetic-loader-integration")
            self.assertGreaterEqual(row["server_version_num"], 160000)
            self.assertLess(row["server_version_num"], 170000)
            self.assertTrue(str(row["postgis_version"]).startswith("3.5."))
            migration = connection.execute(
                "SELECT migration_version, migration_key FROM loader_control.schema_migration"
            ).fetchone()
            self.assertEqual(
                migration,
                {"migration_version": 1, "migration_key": "0001_publication_store"},
            )

        with self._admin_connection() as connection:
            roles = connection.execute(
                """
                SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls
                FROM pg_catalog.pg_roles
                WHERE rolname = ANY(%s)
                ORDER BY rolname
                """,
                ([*ROLE_GROUPS.values(), *ROLE_LOGINS.values()],),
            ).fetchall()
            memberships = connection.execute(
                """
                SELECT member.rolname AS login_name, parent.rolname AS group_name
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
                JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid
                WHERE member.rolname = ANY(%s)
                ORDER BY member.rolname, parent.rolname
                """,
                ([*ROLE_LOGINS.values()],),
            ).fetchall()
        by_name = {row["rolname"]: row for row in roles}
        for group in ROLE_GROUPS.values():
            self.assertFalse(by_name[group]["rolcanlogin"])
            self.assertFalse(by_name[group]["rolinherit"])
            self.assertFalse(by_name[group]["rolsuper"])
            self.assertFalse(by_name[group]["rolcreatedb"])
            self.assertFalse(by_name[group]["rolcreaterole"])
            self.assertFalse(by_name[group]["rolreplication"])
            self.assertFalse(by_name[group]["rolbypassrls"])
        for login in ROLE_LOGINS.values():
            self.assertTrue(by_name[login]["rolcanlogin"])
            self.assertTrue(by_name[login]["rolinherit"])
            self.assertFalse(by_name[login]["rolsuper"])
            self.assertFalse(by_name[login]["rolcreatedb"])
            self.assertFalse(by_name[login]["rolcreaterole"])
            self.assertFalse(by_name[login]["rolreplication"])
            self.assertFalse(by_name[login]["rolbypassrls"])
        self.assertEqual(
            memberships,
            sorted(
                (
                    {"login_name": ROLE_LOGINS[capability], "group_name": group}
                    for capability, group in ROLE_GROUPS.items()
                ),
                key=lambda row: (row["login_name"], row["group_name"]),
            ),
        )

    def test_target_environment_identity_mismatch_fails_before_any_job(self) -> None:
        policy = _policy()
        correct = _loader_config(policy)
        wrong_environment = UUID("ffffffff-ffff-4fff-bfff-ffffffffffff")
        self.assertNotEqual(
            correct.runtime.expected_target_environment_id,
            wrong_environment,
        )
        mismatched = dataclasses.replace(
            correct,
            runtime=dataclasses.replace(
                correct.runtime,
                expected_target_environment_id=wrong_environment,
            ),
        )
        with self.assertRaises(LoaderTargetProtocolError) as rejected:
            _PostgreSQLTargetStore(mismatched)
        self.assertEqual(rejected.exception.code, "LOADER_TARGET_PROTOCOL_INVALID")
        rendered = f"{rejected.exception!s} {rejected.exception!r}"
        self.assertNotIn(str(wrong_environment), rendered)
        self.assertNotIn(os.environ["BRERC_DESTINATION_HOST"], rendered)
        with self._admin_connection() as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_control.etl_job) AS jobs,
                    (SELECT count(*) FROM loader_control.release) AS releases
                """
            ).fetchone()
        self.assertEqual(counts, {"jobs": 0, "releases": 0})

    def test_target_login_with_an_extra_direct_membership_fails_before_any_job(self) -> None:
        extra_role = "brerc_loader_extra_integration_test"
        with self._admin_connection() as administrator:
            exists = administrator.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s) AS exists",
                (extra_role,),
            ).fetchone()["exists"]
            if exists:
                administrator.execute(
                    "REVOKE brerc_loader_extra_integration_test FROM brerc_release_loader_test"
                )
                administrator.execute("DROP ROLE brerc_loader_extra_integration_test")
            administrator.execute(
                "CREATE ROLE brerc_loader_extra_integration_test "
                "NOLOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            administrator.execute(
                "GRANT brerc_loader_extra_integration_test TO brerc_release_loader_test"
            )
        try:
            with self.assertRaises(LoaderTargetProtocolError) as rejected:
                _PostgreSQLTargetStore(_loader_config(_policy()))
            self.assertEqual(rejected.exception.code, "LOADER_TARGET_PROTOCOL_INVALID")
            rendered = f"{rejected.exception!s} {rejected.exception!r}"
            self.assertNotIn(extra_role, rendered)
            self.assertNotIn(ROLE_LOGINS["loader"], rendered)
            with self._admin_connection() as administrator:
                counts = administrator.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM loader_control.etl_job) AS jobs,
                        (SELECT count(*) FROM loader_control.release) AS releases
                    """
                ).fetchone()
            self.assertEqual(counts, {"jobs": 0, "releases": 0})
        finally:
            with self._admin_connection() as administrator:
                administrator.execute(
                    "REVOKE brerc_loader_extra_integration_test FROM brerc_release_loader_test"
                )
                administrator.execute("DROP ROLE brerc_loader_extra_integration_test")

    def test_migration_refuses_a_second_application_without_changing_history(self) -> None:
        migration = (REPO_ROOT / "db/migrations/0001_publication_store.sql").read_text(
            encoding="utf-8"
        )
        connection = self._admin_connection()
        try:
            with self.assertRaises(self.psycopg.errors.RaiseException) as raised:
                # ClientCursor deliberately uses libpq's simple-query protocol,
                # the supported Psycopg path for a migration containing many
                # statements.  This must reach the migration's explicit guard,
                # not fail earlier as a multi-command prepared statement.
                self.ClientCursor(connection).execute(migration)
            # The script starts its own transaction; clear the expected aborted
            # transaction before closing so the test cannot pass via cleanup.
            connection.rollback()
        finally:
            connection.close()
        self.assertEqual(raised.exception.sqlstate, "P0001")
        self.assertIn(
            "migration 0001_publication_store is already applied",
            raised.exception.diag.message_primary,
        )
        with self._connection("loader") as connection:
            history = connection.execute(
                "SELECT migration_version, migration_key FROM loader_control.schema_migration"
            ).fetchall()
        self.assertEqual(
            history,
            [{"migration_version": 1, "migration_key": "0001_publication_store"}],
        )

    def test_postgis_grid_geometry_is_exact_and_wrong_precision_is_rejected(self) -> None:
        with self._connection("loader") as connection:
            row = connection.execute(
                """
                SELECT
                    public.ST_SRID(cell) AS srid,
                    public.ST_Area(cell) AS area,
                    public.ST_Equals(
                        cell,
                        public.ST_MakeEnvelope(358000, 172000, 359000, 173000, 27700)
                    ) AS exact_envelope
                FROM (
                    SELECT loader_control.bng_cell_polygon('ST5872', 1000) AS cell
                ) AS expected
                """
            ).fetchone()
            self.assertEqual(row, {"srid": 27700, "area": 1_000_000.0, "exact_envelope": True})
            with self.assertRaises(self.psycopg.errors.CheckViolation):
                connection.execute("SELECT loader_control.bng_cell_polygon('ST5872', 10000)")

    def test_roles_are_least_privileged_and_public_capabilities_are_separate(self) -> None:
        with self._connection("loader") as connection:
            for statement in (
                "UPDATE loader_control.source_state SET active_release_id = NULL",
                "UPDATE loader_control.release SET status = 'active'",
                "UPDATE loader_control.release SET cleanup_pending = false",
                "UPDATE loader_control.notification_outbox SET status = 'delivered'",
            ):
                with (
                    self.subTest(statement=statement),
                    self.assertRaises(self.psycopg.errors.InsufficientPrivilege),
                ):
                    connection.execute(statement)

        with self._connection("api") as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) AS n FROM serve.public_species").fetchone()[
                    "n"
                ],
                0,
            )
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT count(*) FROM publication.public_species")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT count(*) FROM serve.etl_job_status")

        with self._connection("martin") as connection:
            connection.execute("SELECT count(*) FROM serve.public_distribution_cell")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT count(*) FROM serve.public_species")

        with self._connection("monitor") as connection:
            connection.execute("SELECT count(*) FROM serve.etl_job_status")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT count(*) FROM serve.public_release")

    def test_real_source_connector_streams_into_one_atomic_public_release(self) -> None:
        """Exercise the concrete source, transform, destination and activation seam."""
        policy = _policy(allowed_licence_values=frozenset({"y"}))
        report = loader_coordinator._run_initial_with_inputs(
            _loader_config(policy),
            source_config=self.e2e_source_config,
            source_contract=self.e2e_source_contract,
            columns=VIEW_COLUMNS,
            policy=policy,
        )
        self.assertTrue(report.activated)
        self.assertEqual(report.source_rows, 3)
        self.assertEqual(report.public_records, 0)
        self.assertEqual(report.distribution_cells, 2)

        release_id = UUID(report.release_id)
        with self._connection("api") as connection:
            releases = connection.execute(
                "SELECT release_id, individual_records_available FROM serve.public_release"
            ).fetchall()
            species = connection.execute(
                "SELECT species_id, total_records FROM serve.public_species ORDER BY species_id"
            ).fetchall()
            cells = connection.execute(
                "SELECT species_id, cell_id, precision_metres, record_count, "
                "public.ST_SRID(geom) AS srid "
                "FROM serve.public_distribution_cell ORDER BY species_id"
            ).fetchall()
            public_record_count = connection.execute(
                "SELECT count(*) AS n FROM serve.public_record"
            ).fetchone()["n"]
        self.assertEqual(
            releases,
            [{"release_id": release_id, "individual_records_available": False}],
        )
        self.assertEqual(
            species,
            [
                {"species_id": "SYNTH-E2E-1", "total_records": 1},
                {"species_id": "SYNTH-E2E-2", "total_records": 1},
            ],
        )
        self.assertEqual(
            cells,
            [
                {
                    "species_id": "SYNTH-E2E-1",
                    "cell_id": "ST5872",
                    "precision_metres": 1_000,
                    "record_count": 1,
                    "srid": 27700,
                },
                {
                    "species_id": "SYNTH-E2E-2",
                    "cell_id": "ST5972",
                    "precision_metres": 1_000,
                    "record_count": 1,
                    "srid": 27700,
                },
            ],
        )
        self.assertEqual(public_record_count, 0)

        with self._connection("loader") as connection:
            ledger = connection.execute(
                """
                SELECT disposition, withheld_reason, species_id, record_grid_ref,
                       record_precision_metres, cell_id, place, abundance,
                       record_type, source_label
                FROM loader_control.source_disposition
                WHERE release_id = %s
                ORDER BY disposition, species_id NULLS LAST
                """,
                (release_id,),
            ).fetchall()
            withheld = connection.execute(
                "SELECT reason_code, row_count FROM loader_control.withheld_summary "
                "WHERE release_id = %s",
                (release_id,),
            ).fetchall()
            manifest = connection.execute(
                """
                SELECT source_row_count, source_inventory_count, delta_row_count,
                       eligible_pre_suppression_count, transform_withheld_count,
                       suppression_withheld_count, published_basis_count,
                       species_count, cell_count, species_year_count,
                       public_record_count
                FROM loader_control.release_manifest
                WHERE release_id = %s
                """,
                (release_id,),
            ).fetchone()
            lifecycle = connection.execute(
                """
                SELECT r.status AS release_status, r.cleanup_pending, j.status AS job_status,
                       (SELECT count(*) FROM loader_control.notification_outbox AS o
                        WHERE o.job_id = j.job_id AND o.event_type = 'etl_succeeded')
                           AS success_events,
                       (SELECT count(*) FROM loader_stage.source_inventory) AS inventory_rows,
                       (SELECT count(*) FROM loader_stage.disposition_delta) AS delta_rows,
                       (SELECT count(*) FROM loader_stage.reconciliation_result) AS check_rows
                FROM loader_control.release AS r
                JOIN loader_control.etl_job AS j ON j.job_id = r.job_id
                WHERE r.release_id = %s
                """,
                (release_id,),
            ).fetchone()
            forbidden_columns = connection.execute(
                """
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE table_schema IN ('publication', 'serve', 'loader_control')
                  AND column_name IN ('unique_no', 'easting', 'northing', 'comments', 'sensitive')
                ORDER BY table_schema, table_name, column_name
                """
            ).fetchall()

        self.assertEqual(
            ledger,
            [
                {
                    "disposition": "eligible",
                    "withheld_reason": None,
                    "species_id": "SYNTH-E2E-1",
                    "record_grid_ref": "ST5872",
                    "record_precision_metres": 1_000,
                    "cell_id": "ST5872",
                    "place": None,
                    "abundance": None,
                    "record_type": None,
                    "source_label": "BRERC",
                },
                {
                    "disposition": "eligible",
                    "withheld_reason": None,
                    "species_id": "SYNTH-E2E-2",
                    "record_grid_ref": "ST597221",
                    "record_precision_metres": 100,
                    "cell_id": "ST5972",
                    "place": None,
                    "abundance": None,
                    "record_type": None,
                    "source_label": "BRERC",
                },
                {
                    "disposition": "withheld",
                    "withheld_reason": "licence-not-permitted",
                    "species_id": None,
                    "record_grid_ref": None,
                    "record_precision_metres": None,
                    "cell_id": None,
                    "place": None,
                    "abundance": None,
                    "record_type": None,
                    "source_label": None,
                },
            ],
        )
        self.assertEqual(withheld, [{"reason_code": "licence-not-permitted", "row_count": 1}])
        self.assertEqual(
            manifest,
            {
                "source_row_count": 3,
                "source_inventory_count": 3,
                "delta_row_count": 3,
                "eligible_pre_suppression_count": 2,
                "transform_withheld_count": 1,
                "suppression_withheld_count": 0,
                "published_basis_count": 2,
                "species_count": 2,
                "cell_count": 2,
                "species_year_count": 2,
                "public_record_count": 0,
            },
        )
        self.assertEqual(
            lifecycle,
            {
                "release_status": "active",
                "cleanup_pending": False,
                "job_status": "succeeded",
                "success_events": 1,
                "inventory_rows": 0,
                "delta_rows": 0,
                "check_rows": 0,
            },
        )
        self.assertEqual(forbidden_columns, [])
        rendered = repr(ledger) + repr(species) + repr(cells)
        for private_value in (
            "ST587721",
            "358721.25",
            "172145.75",
            "PRIVATE-E2E-PLACE",
            "PRIVATE-E2E-COMMENT",
            "PRIVATE-E2E-RAW-SOURCE",
            "9001.00",
        ):
            self.assertNotIn(private_value, rendered)

    def test_real_source_failure_never_creates_a_visible_release(self) -> None:
        """A duplicate source identity fails terminally after candidate creation."""
        policy = _policy(allowed_licence_values=frozenset({"y"}))
        with self._source_admin_connection() as source_admin:
            changed = source_admin.execute(
                "UPDATE dashboard.synthetic_records SET unique_no = 9001.00 "
                "WHERE unique_no = 9002.00"
            ).rowcount
        self.assertEqual(changed, 1)
        try:
            with self.assertRaises(LoaderError) as rejected:
                loader_coordinator._run_initial_with_inputs(
                    _loader_config(policy),
                    source_config=self.e2e_source_config,
                    source_contract=self.e2e_source_contract,
                    columns=VIEW_COLUMNS,
                    policy=policy,
                )
        finally:
            with self._source_admin_connection() as source_admin:
                restored = source_admin.execute(
                    "UPDATE dashboard.synthetic_records SET unique_no = 9002.00 "
                    "WHERE scientific_name = 'Synthetic species ordinary'"
                ).rowcount
            self.assertEqual(restored, 1)
        self.assertEqual(rejected.exception.code, "LOADER_CANDIDATE_INVALID")
        rendered_failure = f"{rejected.exception!s} {rejected.exception!r}"
        for private_value in (
            "9001",
            "ST587721",
            "PRIVATE-E2E",
            os.environ["BRERC_LOADER_E2E_SOURCE_HOST"],
        ):
            self.assertNotIn(private_value, rendered_failure)

        with self._connection("api") as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) AS n FROM serve.public_release").fetchone()[
                    "n"
                ],
                0,
            )
        with self._connection("loader") as connection:
            lifecycle = connection.execute(
                """
                SELECT r.status AS release_status, r.cleanup_pending, j.status AS job_status,
                       j.failure_code,
                       (SELECT count(*) FROM loader_control.notification_outbox AS o
                        WHERE o.job_id = j.job_id AND o.event_type = 'etl_failed')
                           AS failure_events,
                       (SELECT count(*) FROM loader_control.source_disposition AS d
                        WHERE d.release_id = r.release_id) AS disposition_rows,
                       (SELECT count(*) FROM loader_stage.source_inventory AS i
                        WHERE i.job_id = j.job_id) AS inventory_rows,
                       (SELECT count(*) FROM loader_stage.disposition_delta AS d
                        WHERE d.job_id = j.job_id) AS delta_rows
                FROM loader_control.release AS r
                JOIN loader_control.etl_job AS j ON j.job_id = r.job_id
                """
            ).fetchall()
        self.assertEqual(
            lifecycle,
            [
                {
                    "release_status": "failed",
                    "cleanup_pending": False,
                    "job_status": "failed",
                    "failure_code": "LOADER_CANDIDATE_INVALID",
                    "failure_events": 1,
                    "disposition_rows": 0,
                    "inventory_rows": 0,
                    "delta_rows": 0,
                }
            ],
        )

    def test_loader_cannot_insert_into_any_durable_table_after_activation(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2), _withheld(3))
        store, handle, _summary, activation = self._activate_rows(rows, policy=policy)
        self.assertEqual(activation.release_id, handle.release_id)

        wrong_state = _CandidateHandle(
            job_id=uuid4(),
            release_id=uuid4(),
            base_release_id=handle.release_id,
        )
        with self._admin_connection() as admin:
            admin.execute(
                """
                INSERT INTO loader_control.etl_job (
                    job_id, source_id, load_mode, status, base_release_id,
                    started_at, heartbeat_at
                ) VALUES (%s, %s, 'incremental', 'reconciling', %s,
                          transaction_timestamp(), transaction_timestamp())
                """,
                (wrong_state.job_id, SOURCE_ID, handle.release_id),
            )
            admin.execute(
                """
                INSERT INTO loader_control.release (
                    release_id, source_id, job_id, base_release_id, load_mode, status
                ) VALUES (%s, %s, %s, %s, 'incremental', 'candidate')
                """,
                (
                    wrong_state.release_id,
                    SOURCE_ID,
                    wrong_state.job_id,
                    handle.release_id,
                ),
            )

        # The authoriser itself rejects an active release even on the session
        # that owns the correct source lock.
        with self.assertRaises(
            self.psycopg.errors.ObjectNotInPrerequisiteState
        ) as active_authority:
            store._cursor.execute(
                "SELECT loader_control.authorize_candidate_writes(%s)",
                (handle.release_id,),
            )
        self.assertEqual(active_authority.exception.sqlstate, "55000")
        self.assertEqual(
            active_authority.exception.diag.message_primary,
            "durable release rows may be authorised only during candidate finalisation",
        )

        # Candidate/reconciling is still insufficient on a second loader
        # connection: advisory-lock ownership is deliberately session-local.
        with (
            self._connection("loader") as second_loader,
            self.assertRaises(self.psycopg.errors.ObjectNotInPrerequisiteState) as missing_lock,
        ):
            second_loader.execute(
                "SELECT loader_control.authorize_candidate_writes(%s)",
                (wrong_state.release_id,),
            )
        self.assertEqual(missing_lock.exception.sqlstate, "55000")
        self.assertEqual(
            missing_lock.exception.diag.message_primary,
            "source session advisory lock is required for durable candidate inserts",
        )

        # Every row below is constraint-valid and uses a fresh key. The active
        # child rows prove post-activation immutability; public_release and
        # manifest use a fresh candidate because their active-release primary
        # keys are already occupied. No INSERT statement has obtained the
        # transaction-local authorisation token.
        statements = (
            (
                "withheld_summary",
                "INSERT INTO loader_control.withheld_summary "
                "(release_id, reason_code, row_count) "
                "VALUES (%s, 'cannot-generalise', 1)",
                (handle.release_id,),
            ),
            (
                "source_disposition",
                "INSERT INTO loader_control.source_disposition "
                "(release_id, source_key_token, input_fingerprint, disposition, "
                "withheld_reason) VALUES (%s, %s, %s, 'withheld', "
                "'invalid-grid-reference')",
                (
                    handle.release_id,
                    bytes.fromhex("12" * 32),
                    bytes.fromhex("34" * 32),
                ),
            ),
            (
                "public_species",
                "INSERT INTO publication.public_species "
                "(release_id, species_id, scientific_name, common_name, taxon_group, "
                "total_records, first_year, last_year) "
                "VALUES (%s, 'SYNTH-LATE', 'Synthetic species late', NULL, NULL, 1, "
                "2025, 2025)",
                (handle.release_id,),
            ),
            (
                "public_distribution_cell",
                "INSERT INTO publication.public_distribution_cell "
                "(release_id, species_id, record_year, cell_id, precision_metres, "
                "record_count, verified_count, geom) "
                "VALUES (%s, 'SYNTH-1', 2025, 'ST5972', 1000, 1, NULL, "
                "loader_control.bng_cell_polygon('ST5972', 1000))",
                (handle.release_id,),
            ),
            (
                "public_species_year",
                "INSERT INTO publication.public_species_year "
                "(release_id, species_id, record_year, record_count, verified_count) "
                "VALUES (%s, 'SYNTH-1', 2025, 1, NULL)",
                (handle.release_id,),
            ),
            (
                "public_record",
                "INSERT INTO publication.public_record "
                "(release_id, public_record_id, species_id, scientific_name, common_name, "
                "grid_ref, precision_metres, place, record_year, abundance, record_type, "
                "verified_status, source_label) "
                "VALUES (%s, %s, 'SYNTH-1', 'Synthetic species alpha', "
                "'Synthetic alpha', 'ST587721', 100, NULL, 2025, NULL, NULL, NULL, "
                "'BRERC')",
                (handle.release_id, "d" * 32),
            ),
            (
                "public_release",
                "INSERT INTO publication.public_release ("
                "release_id, source_data_as_of, publication_policy_version, "
                "dataset_version, suppression_mode, min_records_per_cell, "
                "verification_available, individual_records_available, "
                "record_verification_available, place_available, abundance_available, "
                "record_type_available, public_source_label) "
                "SELECT %s, source_data_as_of, publication_policy_version, "
                "dataset_version, suppression_mode, min_records_per_cell, "
                "verification_available, individual_records_available, "
                "record_verification_available, place_available, abundance_available, "
                "record_type_available, public_source_label "
                "FROM publication.public_release WHERE release_id = %s",
                (wrong_state.release_id, handle.release_id),
            ),
            (
                "release_manifest",
                "INSERT INTO loader_control.release_manifest ("
                "release_id, source_snapshot_at, lower_modified_date, "
                "lower_modified_key_token, upper_modified_date, upper_modified_key_token, "
                "source_contract_version, source_contract_sha256, "
                "observed_view_definition_sha256, observed_view_identity_sha256, "
                "projection_version, projection_sha256, publication_policy_version, "
                "publication_policy_sha256, policy_approval_sha256, suppression_mode, "
                "min_records_per_cell, etl_version, compatibility_sha256, "
                "species_dictionary_sha256, sensitivity_snapshot_sha256, source_row_count, "
                "source_inventory_count, delta_row_count, eligible_pre_suppression_count, "
                "transform_withheld_count, suppression_withheld_count, "
                "published_basis_count, species_count, cell_count, species_year_count, "
                "public_record_count, source_result_sha256, candidate_sha256, "
                "database_sha256) "
                "SELECT %s, source_snapshot_at, lower_modified_date, "
                "lower_modified_key_token, upper_modified_date, upper_modified_key_token, "
                "source_contract_version, source_contract_sha256, "
                "observed_view_definition_sha256, observed_view_identity_sha256, "
                "projection_version, projection_sha256, publication_policy_version, "
                "publication_policy_sha256, policy_approval_sha256, suppression_mode, "
                "min_records_per_cell, etl_version, compatibility_sha256, "
                "species_dictionary_sha256, sensitivity_snapshot_sha256, source_row_count, "
                "source_inventory_count, delta_row_count, eligible_pre_suppression_count, "
                "transform_withheld_count, suppression_withheld_count, "
                "published_basis_count, species_count, cell_count, species_year_count, "
                "public_record_count, source_result_sha256, candidate_sha256, "
                "database_sha256 FROM loader_control.release_manifest "
                "WHERE release_id = %s",
                (wrong_state.release_id, handle.release_id),
            ),
        )

        # Even a legitimate authorisation for another reconciling candidate
        # cannot be used to smuggle rows into the active release. The statement
        # trigger validates the authorised candidate once; RLS then pins every
        # row in the statement to that exact UUID. These six active tables have
        # fresh constraint-valid keys, so SQLSTATE 42501 is specifically the RLS
        # cross-release denial rather than a key/check failure.
        for table, statement, parameters in statements[:6]:
            store._cursor.execute("BEGIN")
            authorised = store._cursor.execute(
                "SELECT loader_control.authorize_candidate_writes(%s) AS release_id",
                (wrong_state.release_id,),
            ).fetchone()
            self.assertEqual(authorised, {"release_id": wrong_state.release_id})
            with (
                self.subTest(table=f"cross-release-{table}"),
                self.assertRaises(self.psycopg.errors.InsufficientPrivilege) as denied,
            ):
                store._cursor.execute(statement, parameters)
            self.assertEqual(denied.exception.sqlstate, "42501")
            store._cursor.execute("ROLLBACK")

        # Without authorisation, every guarded table fails at the fixed
        # statement-level gate before its row can reach constraints or RLS.
        for table, statement, parameters in statements:
            with (
                self.subTest(table=table),
                self.assertRaises(self.psycopg.errors.ObjectNotInPrerequisiteState) as rejected,
            ):
                store._cursor.execute(statement, parameters)
            self.assertEqual(rejected.exception.sqlstate, "55000")
            self.assertEqual(
                rejected.exception.diag.message_primary,
                "durable candidate insert authority is absent",
            )

        with self._connection("api") as connection:
            visible = connection.execute("SELECT release_id FROM serve.public_release").fetchall()
        self.assertEqual(visible, [{"release_id": handle.release_id}])

    def test_terminal_job_audit_is_immutable_and_reserved_events_cannot_be_forged(
        self,
    ) -> None:
        policy = _policy()
        store, handle, _summary, activation = self._activate_rows(
            (_disposition(1), _disposition(2)),
            policy=policy,
        )
        self.assertEqual(activation.release_id, handle.release_id)

        audit_query = """
            SELECT status, source_rows_seen, heartbeat_at,
                   (SELECT count(*) FROM loader_control.etl_job_event AS event
                    WHERE event.job_id = job.job_id) AS event_count
            FROM loader_control.etl_job AS job
            WHERE job_id = %s
        """
        before = store._cursor.execute(audit_query, (handle.job_id,)).fetchone()
        self.assertIsNotNone(before)
        self.assertEqual(before["status"], "succeeded")

        mutations = (
            "UPDATE loader_control.etl_job "
            "SET source_rows_seen = source_rows_seen + 1 WHERE job_id = %s",
            "UPDATE loader_control.etl_job "
            "SET heartbeat_at = heartbeat_at + interval '1 second' WHERE job_id = %s",
            "UPDATE loader_control.etl_job SET status = 'failed' WHERE job_id = %s",
        )
        for statement in mutations:
            with (
                self.subTest(statement=statement),
                self.assertRaises(self.psycopg.errors.ObjectNotInPrerequisiteState) as immutable,
            ):
                store._cursor.execute(statement, (handle.job_id,))
            self.assertEqual(immutable.exception.sqlstate, "55000")
            self.assertEqual(
                immutable.exception.diag.message_primary,
                "terminal ETL job audit rows are immutable",
            )

        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege) as reserved:
            store._cursor.execute(
                "INSERT INTO loader_control.etl_job_event "
                "(job_id, stage, event_code) VALUES (%s, 'terminal', 'SYNTHETIC_FORGERY')",
                (handle.job_id,),
            )
        self.assertEqual(reserved.exception.sqlstate, "42501")

        after = store._cursor.execute(audit_query, (handle.job_id,)).fetchone()
        self.assertEqual(after, before)

    def test_global_suppression_atomic_visibility_and_idempotent_activation(self) -> None:
        policy = _policy(threshold=2)
        rows = (
            _disposition(1),
            _disposition(2),
            _disposition(
                3,
                species_id="SYNTH-2",
                scientific_name="Synthetic species beta",
                common_name="Synthetic beta",
                cell_id="ST5972",
            ),
            _withheld(4),
        )
        store, handle, summary = self._finalized(
            rows,
            policy=policy,
            batches=((rows[0],), (rows[1],), (rows[2], rows[3])),
        )
        self.assertEqual(summary.source_rows, 4)
        self.assertEqual(summary.published_records, 0)
        self.assertEqual(summary.distribution_cells, 1)

        with self._connection("api") as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) AS n FROM serve.public_release").fetchone()[
                    "n"
                ],
                0,
                "a completely finalized candidate became visible before activation",
            )

        first = store.activate(handle, summary)
        second = store.activate(handle, summary)
        self.assertEqual(first.release_id, handle.release_id)
        self.assertEqual(second.release_id, handle.release_id)
        self.assertEqual(first.candidate_sha256, second.candidate_sha256)

        with self._connection("api") as connection:
            release_count = connection.execute(
                "SELECT count(*) AS n FROM serve.public_release"
            ).fetchone()["n"]
            species = connection.execute(
                """
                SELECT species_id, total_records, first_year, last_year, taxon_group
                FROM serve.public_species
                """
            ).fetchall()
            cells = connection.execute(
                """
                SELECT
                    species_id,
                    record_year,
                    cell_id,
                    precision_metres,
                    record_count,
                    verified_count,
                    public.ST_SRID(geom) AS srid,
                    public.ST_Equals(
                        geom,
                        public.ST_MakeEnvelope(358000, 172000, 359000, 173000, 27700)
                    ) AS exact_envelope
                FROM serve.public_distribution_cell
                """
            ).fetchall()
            year_rows = connection.execute(
                "SELECT species_id, record_year, record_count FROM serve.public_species_year"
            ).fetchall()
            public_records = connection.execute(
                "SELECT count(*) AS n FROM serve.public_record"
            ).fetchone()["n"]
        self.assertEqual(release_count, 1)
        self.assertEqual(
            species,
            [
                {
                    "species_id": "SYNTH-1",
                    "total_records": 2,
                    "first_year": 2024,
                    "last_year": 2024,
                    "taxon_group": None,
                }
            ],
        )
        self.assertEqual(
            cells,
            [
                {
                    "species_id": "SYNTH-1",
                    "record_year": 2024,
                    "cell_id": "ST5872",
                    "precision_metres": 1000,
                    "record_count": 2,
                    "verified_count": None,
                    "srid": 27700,
                    "exact_envelope": True,
                }
            ],
        )
        self.assertEqual(
            year_rows,
            [{"species_id": "SYNTH-1", "record_year": 2024, "record_count": 2}],
        )
        self.assertEqual(public_records, 0)

        with self._connection("loader") as connection:
            dispositions = connection.execute(
                """
                SELECT disposition, count(*) AS n
                FROM loader_control.source_disposition
                WHERE release_id = %s
                GROUP BY disposition
                ORDER BY disposition
                """,
                (handle.release_id,),
            ).fetchall()
            staged = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_stage.source_inventory) AS inventory,
                    (SELECT count(*) FROM loader_stage.disposition_delta) AS delta,
                    (SELECT count(*) FROM loader_stage.reconciliation_result) AS checks,
                    (SELECT count(*) FROM loader_control.notification_outbox
                     WHERE event_type = 'etl_succeeded') AS success_events
                """
            ).fetchone()
        self.assertEqual(
            dispositions,
            [
                {"disposition": "eligible", "n": 2},
                {"disposition": "suppressed", "n": 1},
                {"disposition": "withheld", "n": 1},
            ],
        )
        self.assertEqual(
            staged,
            {"inventory": 0, "delta": 0, "checks": 0, "success_events": 1},
        )

    def test_threshold_three_is_global_across_batches_and_exact_at_the_boundary(self) -> None:
        policy = _policy(threshold=3)
        rows = (
            _disposition(1),
            _disposition(2),
            _disposition(3),
            _disposition(
                4,
                species_id="SYNTH-2",
                scientific_name="Synthetic species beta",
                common_name="Synthetic beta",
                cell_id="ST5972",
            ),
            _disposition(
                5,
                species_id="SYNTH-2",
                scientific_name="Synthetic species beta",
                common_name="Synthetic beta",
                cell_id="ST5972",
            ),
        )
        _store, handle, summary, _activation = self._activate_rows(
            rows,
            policy=policy,
            batches=tuple((row,) for row in rows),
        )
        self.assertEqual(summary.distribution_cells, 1)
        with self._connection("loader") as connection:
            dispositions = connection.execute(
                """
                SELECT species_id, disposition, count(*) AS n
                FROM loader_control.source_disposition
                WHERE release_id = %s
                GROUP BY species_id, disposition
                ORDER BY species_id, disposition
                """,
                (handle.release_id,),
            ).fetchall()
        self.assertEqual(
            dispositions,
            [
                {"species_id": "SYNTH-1", "disposition": "eligible", "n": 3},
                {"species_id": "SYNTH-2", "disposition": "suppressed", "n": 2},
            ],
        )

    def test_identical_stale_candidate_reuses_active_then_discards_pending_payload(
        self,
    ) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2), _withheld(3))
        store, base_handle, _summary, activation = self._activate_rows(rows, policy=policy)
        base_release = activation.release_id
        with self._connection("loader") as connection:
            maximum_token = connection.execute(
                """
                SELECT source_key_token
                FROM loader_control.source_disposition
                WHERE release_id = %s
                ORDER BY source_key_token DESC
                LIMIT 1
                """,
                (base_release,),
            ).fetchone()["source_key_token"]

        active = self._install_incremental_clone(
            store=store,
            base_release=base_release,
            upper_token=maximum_token,
        )
        activated = store._cursor.execute(
            "SELECT loader_control.activate_validated_release(%s) AS release_id",
            (active.release_id,),
        ).fetchone()
        self.assertEqual(activated, {"release_id": active.release_id})

        # This candidate was constructed against the now-retired base, but has
        # exactly the same complete identity as the release activated above. It
        # represents a whole-run retry whose successful response was lost.
        stale_retry = self._install_incremental_clone(
            store=store,
            base_release=base_handle.release_id,
            upper_token=maximum_token,
        )
        reused = store._cursor.execute(
            "SELECT loader_control.activate_validated_release(%s) AS release_id",
            (stale_retry.release_id,),
        ).fetchone()
        self.assertEqual(reused, {"release_id": active.release_id})

        with self._connection("loader") as connection:
            lifecycle = connection.execute(
                """
                SELECT r.status AS release_status, j.status AS job_status,
                       j.result_release_id, j.reused_active_release,
                       r.cleanup_pending
                FROM loader_control.release AS r
                JOIN loader_control.etl_job AS j USING (job_id)
                WHERE r.release_id = %s
                """,
                (stale_retry.release_id,),
            ).fetchone()
            payload = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_species
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_distribution_cell
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_species_year
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_record
                       WHERE release_id = %s) AS n
                """,
                (stale_retry.release_id,) * 6,
            ).fetchone()["n"]
            retained_withheld_audit = connection.execute(
                """
                SELECT COALESCE(sum(row_count), 0) AS n
                FROM loader_control.withheld_summary
                WHERE release_id = %s
                """,
                (stale_retry.release_id,),
            ).fetchone()["n"]
            stage = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = %s)
                    + (SELECT count(*) FROM loader_stage.disposition_delta
                       WHERE job_id = %s)
                    + (SELECT count(*) FROM loader_stage.reconciliation_result
                       WHERE job_id = %s) AS n
                """,
                (stale_retry.job_id,) * 3,
            ).fetchone()["n"]
        self.assertEqual(
            lifecycle,
            {
                "release_status": "discarded",
                "job_status": "succeeded",
                "result_release_id": active.release_id,
                "reused_active_release": True,
                "cleanup_pending": True,
            },
        )
        self.assertGreater(payload, 0)
        self.assertEqual(retained_withheld_audit, 1)
        self.assertGreater(stage, 0)

        with self._connection("api") as connection:
            visible = connection.execute("SELECT release_id FROM serve.public_release").fetchall()
        self.assertEqual(visible, [{"release_id": active.release_id}])

        removed = store._cursor.execute(
            "SELECT loader_control.discard_inactive_candidate(%s) AS removed_rows",
            (stale_retry.release_id,),
        ).fetchone()["removed_rows"]
        self.assertGreater(removed, 0)
        second = store._cursor.execute(
            "SELECT loader_control.discard_inactive_candidate(%s) AS removed_rows",
            (stale_retry.release_id,),
        ).fetchone()["removed_rows"]
        self.assertEqual(second, 0)
        with self._connection("loader") as connection:
            cleaned = connection.execute(
                """
                SELECT r.cleanup_pending,
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = r.release_id)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = r.release_id) AS payload,
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.disposition_delta
                       WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.reconciliation_result
                       WHERE job_id = r.job_id) AS stage
                FROM loader_control.release AS r
                WHERE r.release_id = %s
                """,
                (stale_retry.release_id,),
            ).fetchone()
        self.assertEqual(cleaned, {"cleanup_pending": False, "payload": 0, "stage": 0})

    def test_duplicate_source_token_fails_closed_and_cleans_stage(self) -> None:
        policy = _policy()
        first = _disposition(1)
        store = self._store(policy)
        store.acquire(SOURCE_ID)
        handle = store.begin_initial(
            SOURCE_ID,
            _CandidateHandle(job_id=uuid4(), release_id=uuid4(), base_release_id=None),
        )
        store.stage_batch(handle, (first,))
        duplicate = dataclasses.replace(first, source_fingerprint="f" * 64)
        with self.assertRaises(LoaderCandidateInvalid):
            store.stage_batch(handle, (duplicate,))
        store.fail(handle, "LOADER_CANDIDATE_INVALID")
        store.fail(handle, "LOADER_CANDIDATE_INVALID")

        with self._connection("loader") as connection:
            failed = connection.execute(
                "SELECT status, cleanup_pending FROM loader_control.release WHERE release_id = %s",
                (handle.release_id,),
            ).fetchone()
            staged = connection.execute(
                "SELECT count(*) AS n FROM loader_stage.source_inventory"
            ).fetchone()["n"]
            failed_events = connection.execute(
                """
                SELECT count(*) AS n
                FROM loader_control.notification_outbox
                WHERE job_id = %s AND event_type = 'etl_failed'
                """,
                (handle.job_id,),
            ).fetchone()["n"]
            candidate_rows = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = %s) AS n
                """,
                (handle.release_id, handle.release_id),
            ).fetchone()["n"]
        self.assertEqual(failed, {"status": "failed", "cleanup_pending": False})
        self.assertEqual(staged, 0)
        self.assertEqual(failed_events, 1)
        self.assertEqual(candidate_rows, 0)

    def test_fail_candidate_commits_terminal_state_before_idempotent_discard(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2), _withheld(3))
        store, handle, _summary = self._finalized(rows, policy=policy)

        with self._connection("loader") as connection:
            before = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_species
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_distribution_cell
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_species_year
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_record
                       WHERE release_id = %s) AS n
                """,
                (handle.release_id,) * 6,
            ).fetchone()["n"]
        self.assertGreater(before, 0)

        # Call the database primitive directly, simulating a worker that dies
        # after the quick terminal commit but before its best-effort purge.
        first = store._cursor.execute(
            "SELECT loader_control.fail_candidate(%s, %s) AS release_id",
            (handle.release_id, "LOADER_CANDIDATE_INVALID"),
        ).fetchone()
        self.assertEqual(first, {"release_id": handle.release_id})

        with self._connection("loader") as connection:
            failed = connection.execute(
                """
                SELECT r.status AS release_status, j.status AS job_status,
                       j.failure_code, r.cleanup_pending
                FROM loader_control.release AS r
                JOIN loader_control.etl_job AS j USING (job_id)
                WHERE r.release_id = %s
                """,
                (handle.release_id,),
            ).fetchone()
            payload = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_species
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_distribution_cell
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_species_year
                       WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_record
                       WHERE release_id = %s) AS n
                """,
                (handle.release_id,) * 6,
            ).fetchone()["n"]
            stage = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = %s)
                    + (SELECT count(*) FROM loader_stage.disposition_delta
                       WHERE job_id = %s)
                    + (SELECT count(*) FROM loader_stage.reconciliation_result
                       WHERE job_id = %s) AS n
                """,
                (handle.job_id,) * 3,
            ).fetchone()["n"]
            failed_events = connection.execute(
                """
                SELECT count(*) AS n
                FROM loader_control.notification_outbox
                WHERE job_id = %s AND event_type = 'etl_failed'
                """,
                (handle.job_id,),
            ).fetchone()["n"]
        self.assertEqual(
            failed,
            {
                "release_status": "failed",
                "job_status": "failed",
                "failure_code": "LOADER_CANDIDATE_INVALID",
                "cleanup_pending": True,
            },
        )
        self.assertEqual(payload, before)
        self.assertGreater(stage, 0)
        self.assertEqual(failed_events, 1)
        with self._connection("monitor") as connection:
            monitored = connection.execute(
                """
                SELECT status, cleanup_pending
                FROM serve.etl_release_status
                WHERE release_id = %s
                """,
                (handle.release_id,),
            ).fetchone()
        self.assertEqual(monitored, {"status": "failed", "cleanup_pending": True})

        # The exact terminal retry repairs a missing transactional outbox row
        # without duplicating it and without attempting the bulk cleanup.
        with self._admin_connection() as connection:
            connection.execute(
                "DELETE FROM loader_control.notification_outbox "
                "WHERE job_id = %s AND event_type = 'etl_failed'",
                (handle.job_id,),
            )

        second = store._cursor.execute(
            "SELECT loader_control.fail_candidate(%s, %s) AS release_id",
            (handle.release_id, "LOADER_CANDIDATE_INVALID"),
        ).fetchone()
        self.assertEqual(second, {"release_id": handle.release_id})
        with self._connection("loader") as connection:
            retry_state = connection.execute(
                """
                SELECT
                    r.cleanup_pending,
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = r.release_id)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = r.release_id) AS payload,
                    (SELECT count(*) FROM loader_control.notification_outbox
                     WHERE job_id = r.job_id AND event_type = 'etl_failed') AS failed_events
                FROM loader_control.release AS r
                WHERE r.release_id = %s
                """,
                (handle.release_id,),
            ).fetchone()
        self.assertEqual(
            retry_state,
            {"cleanup_pending": True, "payload": len(rows) + 1, "failed_events": 1},
        )

        removed = store._cursor.execute(
            "SELECT loader_control.discard_inactive_candidate(%s) AS removed_rows",
            (handle.release_id,),
        ).fetchone()["removed_rows"]
        self.assertGreater(removed, 0)
        removed_again = store._cursor.execute(
            "SELECT loader_control.discard_inactive_candidate(%s) AS removed_rows",
            (handle.release_id,),
        ).fetchone()["removed_rows"]
        self.assertEqual(removed_again, 0)

        # A late repeat of fail_candidate must not turn cleanup_pending back on.
        third = store._cursor.execute(
            "SELECT loader_control.fail_candidate(%s, %s) AS release_id",
            (handle.release_id, "LOADER_CANDIDATE_INVALID"),
        ).fetchone()
        self.assertEqual(third, {"release_id": handle.release_id})
        with self._connection("loader") as connection:
            cleaned = connection.execute(
                """
                SELECT r.cleanup_pending,
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = r.release_id)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = r.release_id) AS payload,
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.disposition_delta
                       WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.reconciliation_result
                       WHERE job_id = r.job_id) AS stage,
                    (SELECT count(*) FROM loader_control.notification_outbox
                     WHERE job_id = r.job_id AND event_type = 'etl_failed') AS failed_events
                FROM loader_control.release AS r
                WHERE r.release_id = %s
                """,
                (handle.release_id,),
            ).fetchone()
        self.assertEqual(
            cleaned,
            {"cleanup_pending": False, "payload": 0, "stage": 0, "failed_events": 1},
        )

        with self._connection("api") as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) AS n FROM serve.public_release").fetchone()[
                    "n"
                ],
                0,
            )

    def test_acquire_scavenges_terminal_pending_payload_before_new_work(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2), _withheld(3))
        abandoned, handle, _summary = self._finalized(rows, policy=policy)
        abandoned._cursor.execute(
            "SELECT loader_control.fail_candidate(%s, %s)",
            (handle.release_id, "LOADER_CANDIDATE_INVALID"),
        ).fetchone()
        abandoned.close()  # crash before the best-effort discard

        with self._connection("loader") as connection:
            pending = connection.execute(
                """
                SELECT r.cleanup_pending,
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = r.release_id)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = r.release_id) AS payload
                FROM loader_control.release AS r
                WHERE r.release_id = %s
                """,
                (handle.release_id,),
            ).fetchone()
        self.assertTrue(pending["cleanup_pending"])
        self.assertGreater(pending["payload"], 0)

        recovery = self._store(policy)
        recovery.acquire(SOURCE_ID)
        with self._connection("loader") as connection:
            cleaned = connection.execute(
                """
                SELECT r.cleanup_pending,
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = r.release_id)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = r.release_id) AS payload,
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.disposition_delta
                       WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.reconciliation_result
                       WHERE job_id = r.job_id) AS stage,
                    (SELECT count(*) FROM loader_control.notification_outbox
                     WHERE job_id = r.job_id AND event_type = 'etl_failed') AS failed_events,
                    (SELECT count(*) FROM loader_control.etl_job
                     WHERE source_id = %s AND status NOT IN ('succeeded', 'failed')) AS open_jobs
                FROM loader_control.release AS r
                WHERE r.release_id = %s
                """,
                (SOURCE_ID, handle.release_id),
            ).fetchone()
        self.assertEqual(
            cleaned,
            {
                "cleanup_pending": False,
                "payload": 0,
                "stage": 0,
                "failed_events": 1,
                "open_jobs": 0,
            },
        )
        recovery.close()

    def test_cleanup_timeout_preserves_pending_and_blocks_new_work_without_hiding_active(
        self,
    ) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2), _withheld(3))
        owner, base_handle, _summary, activation = self._activate_rows(rows, policy=policy)
        base_release = activation.release_id
        with self._connection("loader") as connection:
            maximum_token = connection.execute(
                """
                SELECT source_key_token
                FROM loader_control.source_disposition
                WHERE release_id = %s
                ORDER BY source_key_token DESC
                LIMIT 1
                """,
                (base_release,),
            ).fetchone()["source_key_token"]
        active = self._install_incremental_clone(
            store=owner,
            base_release=base_release,
            upper_token=maximum_token,
        )
        owner._cursor.execute(
            "SELECT loader_control.activate_validated_release(%s)",
            (active.release_id,),
        ).fetchone()
        pending = self._install_incremental_clone(
            store=owner,
            base_release=base_handle.release_id,
            upper_token=maximum_token,
        )
        owner._cursor.execute(
            "SELECT loader_control.activate_validated_release(%s)",
            (pending.release_id,),
        ).fetchone()
        owner.close()

        # Hold a row lock that the atomic purge must acquire. A deliberately
        # short lock timeout makes the cleanup fail quickly and deterministically.
        blocker = self._admin_connection(autocommit=False)
        try:
            locked = blocker.execute(
                """
                SELECT release_id
                FROM publication.public_release
                WHERE release_id = %s
                FOR UPDATE
                """,
                (pending.release_id,),
            ).fetchone()
            self.assertEqual(locked, {"release_id": pending.release_id})

            short_config = _loader_config(policy)
            short_config = dataclasses.replace(
                short_config,
                runtime=dataclasses.replace(
                    short_config.runtime,
                    lock_timeout_ms=100,
                    statement_timeout_ms=1_000,
                ),
            )
            blocked = self._store(policy, config=short_config)
            with self.assertRaises(LoaderCleanupPending):
                blocked.acquire(SOURCE_ID)
            blocked.close()

            with self._connection("loader") as connection:
                debt = connection.execute(
                    """
                    SELECT r.cleanup_pending,
                        (SELECT count(*) FROM loader_control.source_disposition
                         WHERE release_id = r.release_id)
                        + (SELECT count(*) FROM publication.public_release
                           WHERE release_id = r.release_id) AS payload,
                        (SELECT count(*) FROM loader_control.etl_job
                         WHERE source_id = %s
                           AND status NOT IN ('succeeded', 'failed')) AS open_jobs
                    FROM loader_control.release AS r
                    WHERE r.release_id = %s
                    """,
                    (SOURCE_ID, pending.release_id),
                ).fetchone()
            self.assertTrue(debt["cleanup_pending"])
            self.assertGreater(debt["payload"], 0)
            self.assertEqual(debt["open_jobs"], 0)
            with self._connection("api") as connection:
                visible = connection.execute(
                    "SELECT release_id FROM serve.public_release"
                ).fetchall()
            self.assertEqual(visible, [{"release_id": active.release_id}])
        finally:
            blocker.rollback()
            blocker.close()

        recovery = self._store(policy)
        recovery.acquire(SOURCE_ID)
        recovery.close()
        with self._connection("loader") as connection:
            cleaned = connection.execute(
                """
                SELECT r.cleanup_pending,
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = r.release_id)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = r.release_id) AS payload,
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.disposition_delta
                       WHERE job_id = r.job_id)
                    + (SELECT count(*) FROM loader_stage.reconciliation_result
                       WHERE job_id = r.job_id) AS stage
                FROM loader_control.release AS r
                WHERE r.release_id = %s
                """,
                (pending.release_id,),
            ).fetchone()
        self.assertEqual(cleaned, {"cleanup_pending": False, "payload": 0, "stage": 0})
        with self._connection("api") as connection:
            visible = connection.execute("SELECT release_id FROM serve.public_release").fetchall()
        self.assertEqual(visible, [{"release_id": active.release_id}])

    def test_public_id_collision_is_rejected_during_finalization(self) -> None:
        policy = _policy()
        collision_id = "b" * 32
        rows = (
            _disposition(20, public_record_id=collision_id),
            _disposition(21, public_record_id=collision_id),
        )
        store = self._store(policy)
        store.acquire(SOURCE_ID)
        handle = store.begin_initial(
            SOURCE_ID,
            _CandidateHandle(job_id=uuid4(), release_id=uuid4(), base_release_id=None),
        )
        store.stage_batch(handle, rows)
        contract = approved_contract()
        with self.assertRaises(LoaderCandidateInvalid):
            store.finalize(
                handle,
                evidence=_evidence(policy, rows),
                policy=policy,
                source_contract=contract,
                projection=PROJECTION,
                policy_artifact_sha256=_loader_config(policy).publication.expected_sha256,
            )
        store.fail(handle, "LOADER_CANDIDATE_INVALID")
        with self._connection("api") as connection:
            visible = connection.execute(
                "SELECT count(*) AS n FROM serve.public_release"
            ).fetchone()["n"]
        self.assertEqual(visible, 0)

    def test_withheld_reason_evidence_must_match_database_counts_exactly(self) -> None:
        policy = _policy()
        cases = (
            (
                (
                    _disposition(30),
                    _withheld(31),
                    _withheld(32),
                    _withheld(33, reason="invalid-grid-reference"),
                ),
                (
                    ("invalid-grid-reference", 2),
                    ("licence-not-approved", 1),
                ),
            ),
            (
                (
                    _disposition(40),
                    _withheld(41),
                    _withheld(42, reason="invalid-grid-reference"),
                ),
                (
                    ("cannot-generalise", 1),
                    ("licence-not-approved", 1),
                ),
            ),
        )
        for rows, false_reason_counts in cases:
            with self.subTest(false_reason_counts=false_reason_counts):
                store = self._store(policy)
                store.acquire(SOURCE_ID)
                handle = store.begin_initial(
                    SOURCE_ID,
                    _CandidateHandle(
                        job_id=uuid4(),
                        release_id=uuid4(),
                        base_release_id=None,
                    ),
                )
                store.stage_batch(handle, rows)
                false_evidence = dataclasses.replace(
                    _evidence(policy, rows),
                    withheld_by_reason=false_reason_counts,
                )
                contract = approved_contract()
                with self.assertRaises(LoaderCandidateInvalid):
                    store.finalize(
                        handle,
                        evidence=false_evidence,
                        policy=policy,
                        source_contract=contract,
                        projection=PROJECTION,
                        policy_artifact_sha256=(_loader_config(policy).publication.expected_sha256),
                    )

                with self._connection("loader") as connection:
                    state = connection.execute(
                        "SELECT active_release_id FROM loader_control.source_state "
                        "WHERE source_id = %s",
                        (SOURCE_ID,),
                    ).fetchone()
                    release = connection.execute(
                        "SELECT status FROM loader_control.release WHERE release_id = %s",
                        (handle.release_id,),
                    ).fetchone()
                self.assertEqual(state, {"active_release_id": None})
                self.assertNotEqual(release, {"status": "active"})
                with self._connection("api") as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(*) AS n FROM serve.public_release"
                        ).fetchone()["n"],
                        0,
                    )

                store.fail(handle, "LOADER_CANDIDATE_INVALID")
                store.close()
                with self._admin_connection() as connection:
                    connection.execute("TRUNCATE TABLE loader_control.source_state CASCADE")

    def test_every_safe_delta_field_is_compared_to_the_immutable_ledger(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2), _withheld(3))
        mutations = (
            (
                "input_fingerprint",
                "UPDATE loader_stage.disposition_delta "
                "SET input_fingerprint = decode(repeat('ab', 32), 'hex') "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "species_id",
                "UPDATE loader_stage.disposition_delta SET species_id = 'SYNTH-X' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "scientific_name",
                "UPDATE loader_stage.disposition_delta "
                "SET scientific_name = 'Mutated synthetic species' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "common_name",
                "UPDATE loader_stage.disposition_delta SET common_name = 'Mutated common' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "record_grid_ref",
                "UPDATE loader_stage.disposition_delta SET record_grid_ref = 'ST587722' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "record_grid_ref_and_precision",
                "UPDATE loader_stage.disposition_delta "
                "SET record_grid_ref = 'ST5872', record_precision_metres = 1000 "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "cell_id_and_bounds",
                "UPDATE loader_stage.disposition_delta "
                "SET record_grid_ref = 'ST597221', cell_id = 'ST5972', "
                "min_easting = 359000, max_easting = 360000 "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "cell_precision_and_bounds",
                "UPDATE loader_stage.disposition_delta "
                "SET cell_id = 'ST57', cell_precision_metres = 10000, "
                "min_easting = 350000, min_northing = 170000, "
                "max_easting = 360000, max_northing = 180000 "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "record_year",
                "UPDATE loader_stage.disposition_delta SET record_year = 2023 "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "public_record_id",
                "UPDATE loader_stage.disposition_delta "
                "SET public_record_id = repeat('c', 32) "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "place",
                "UPDATE loader_stage.disposition_delta SET place = 'Synthetic locality' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "abundance",
                "UPDATE loader_stage.disposition_delta SET abundance = 'many' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "record_type",
                "UPDATE loader_stage.disposition_delta SET record_type = 'field record' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "verified_status",
                "UPDATE loader_stage.disposition_delta SET verified_status = 'accepted' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "source_label",
                "UPDATE loader_stage.disposition_delta SET source_label = 'SYNTHETIC' "
                "WHERE job_id = %s AND action = 'upsert'",
            ),
            (
                "withheld_reason",
                "UPDATE loader_stage.disposition_delta "
                "SET withheld_reason = 'invalid-grid-reference' "
                "WHERE job_id = %s AND action = 'withhold'",
            ),
        )

        control, _handle, _summary, activation = self._activate_rows(rows, policy=policy)
        self.assertEqual(activation.source_rows, len(rows))
        control.close()
        with self._admin_connection() as admin:
            admin.execute("TRUNCATE TABLE loader_control.source_state CASCADE")

        for label, statement in mutations:
            with self.subTest(field=label):
                store, handle, summary = self._finalized(rows, policy=policy)
                with self._admin_connection() as admin:
                    result = admin.execute(statement, (handle.job_id,))
                    self.assertGreater(result.rowcount, 0)
                with self.assertRaises(LoaderError):
                    store.activate(handle, summary)
                with self._connection("api") as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(*) AS n FROM serve.public_release"
                        ).fetchone()["n"],
                        0,
                    )
                store.fail(handle, "LOADER_CANDIDATE_INVALID")
                store.close()
                with self._admin_connection() as admin:
                    admin.execute("TRUNCATE TABLE loader_control.source_state CASCADE")

    def test_lifecycle_functions_require_the_source_session_lock_and_taxon_group_is_blocked(
        self,
    ) -> None:
        policy = _policy()
        rows = (_disposition(1),)
        store, handle, _summary = self._finalized(rows, policy=policy)

        with self._connection("loader") as unlocked:
            for query, parameters in (
                (
                    "SELECT loader_control.activate_validated_release(%s)",
                    (handle.release_id,),
                ),
                (
                    "SELECT loader_control.fail_candidate(%s, %s)",
                    (handle.release_id, "LOADER_CANDIDATE_INVALID"),
                ),
                (
                    "SELECT loader_control.recover_orphaned_job(%s)",
                    (SOURCE_ID,),
                ),
            ):
                with (
                    self.subTest(query=query),
                    self.assertRaises(self.psycopg.errors.ObjectNotInPrerequisiteState),
                ):
                    unlocked.execute(query, parameters)

            with self.assertRaises(self.psycopg.errors.CheckViolation):
                unlocked.execute(
                    """
                    INSERT INTO publication.public_species (
                        release_id, species_id, scientific_name, common_name,
                        taxon_group, total_records, first_year, last_year
                    ) VALUES (%s, 'SYNTH-GROUP', 'Synthetic grouped species', NULL,
                              'unapproved-group', 1, 2024, 2024)
                    """,
                    (handle.release_id,),
                )

        store.fail(handle, "LOADER_CANDIDATE_INVALID")

    def test_database_rejects_mixed_watermark_markers_and_omitted_initial_delta(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2))

        store, handle, summary = self._finalized(rows, policy=policy)
        with self._admin_connection() as admin:
            admin.execute(
                """
                UPDATE loader_stage.source_inventory
                SET observed_modified_date = DATE '2026-08-14'
                WHERE job_id = %s
                  AND source_key_token = (
                      SELECT source_key_token
                      FROM loader_stage.source_inventory
                      WHERE job_id = %s
                      ORDER BY source_key_token
                      LIMIT 1
                  )
                """,
                (handle.job_id, handle.job_id),
            )
        with self.assertRaises(LoaderError):
            store.activate(handle, summary)
        store.fail(handle, "LOADER_CANDIDATE_INVALID")

        with self._admin_connection() as admin:
            admin.execute("TRUNCATE TABLE loader_control.source_state CASCADE")
        store, handle, summary = self._finalized(rows, policy=policy)
        with self._admin_connection() as admin:
            admin.execute(
                """
                DELETE FROM loader_stage.disposition_delta
                WHERE job_id = %s
                  AND source_key_token = (
                      SELECT source_key_token
                      FROM loader_stage.disposition_delta
                      WHERE job_id = %s
                      ORDER BY source_key_token
                      LIMIT 1
                  )
                """,
                (handle.job_id, handle.job_id),
            )
            # Simulate a privileged corruption that also adjusts the simple
            # count.  Activation must still detect the missing key by set parity.
            admin.execute(
                """
                UPDATE loader_control.release_manifest
                SET delta_row_count = delta_row_count - 1
                WHERE release_id = %s
                """,
                (handle.release_id,),
            )
        with self.assertRaises(LoaderError):
            store.activate(handle, summary)
        store.fail(handle, "LOADER_CANDIDATE_INVALID")

        with self._connection("api") as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) AS n FROM serve.public_release").fetchone()[
                    "n"
                ],
                0,
            )

    def test_orphan_recovery_and_advisory_concurrency_are_automatic(self) -> None:
        policy = _policy()
        first = self._store(policy)
        first.acquire(SOURCE_ID)

        contender = self._store(policy)
        with self.assertRaises(LoaderAlreadyRunning):
            contender.acquire(SOURCE_ID)

        handle = first.begin_initial(
            SOURCE_ID,
            _CandidateHandle(job_id=uuid4(), release_id=uuid4(), base_release_id=None),
        )
        first.stage_batch(handle, (_disposition(1),))
        first.close()  # synthetic worker death: leaves a committed open job

        # Exercise the authoritative recovery transition separately from the
        # potentially large cleanup so a crash between them is observable.
        with self._connection("loader") as connection:
            locked = connection.execute(
                "SELECT pg_catalog.pg_try_advisory_lock("
                "pg_catalog.hashtextextended(%s, 0)) AS acquired",
                (SOURCE_ID,),
            ).fetchone()
            self.assertEqual(locked, {"acquired": True})
            recovered = connection.execute(
                "SELECT loader_control.recover_orphaned_job(%s) AS recovered",
                (SOURCE_ID,),
            ).fetchone()
            self.assertEqual(recovered, {"recovered": 1})
            pending = connection.execute(
                """
                SELECT r.status AS release_status, r.cleanup_pending,
                       j.status AS job_status, j.failure_code,
                    (SELECT count(*) FROM loader_stage.source_inventory
                     WHERE job_id = r.job_id) AS stage,
                    (SELECT count(*) FROM loader_control.notification_outbox
                     WHERE job_id = r.job_id AND event_type = 'etl_failed') AS failed_events
                FROM loader_control.release AS r
                JOIN loader_control.etl_job AS j USING (job_id)
                WHERE r.release_id = %s
                """,
                (handle.release_id,),
            ).fetchone()
            self.assertEqual(
                pending,
                {
                    "release_status": "failed",
                    "cleanup_pending": True,
                    "job_status": "failed",
                    "failure_code": "WORKER_LOST",
                    "stage": 1,
                    "failed_events": 1,
                },
            )
            repeated = connection.execute(
                "SELECT loader_control.recover_orphaned_job(%s) AS recovered",
                (SOURCE_ID,),
            ).fetchone()
            self.assertEqual(repeated, {"recovered": 0})
            removed = connection.execute(
                "SELECT loader_control.discard_inactive_candidate(%s) AS removed_rows",
                (handle.release_id,),
            ).fetchone()["removed_rows"]
            self.assertGreater(removed, 0)
            released = connection.execute(
                "SELECT pg_catalog.pg_advisory_unlock("
                "pg_catalog.hashtextextended(%s, 0)) AS released",
                (SOURCE_ID,),
            ).fetchone()
            self.assertEqual(released, {"released": True})

        second_recovery = self._store(policy)
        second_recovery.acquire(SOURCE_ID)
        second_recovery.close()
        with self._connection("loader") as connection:
            job = connection.execute(
                "SELECT status, failure_code FROM loader_control.etl_job WHERE job_id = %s",
                (handle.job_id,),
            ).fetchone()
            release = connection.execute(
                "SELECT status, cleanup_pending FROM loader_control.release WHERE release_id = %s",
                (handle.release_id,),
            ).fetchone()
            stage_count = connection.execute(
                "SELECT count(*) AS n FROM loader_stage.source_inventory"
            ).fetchone()["n"]
            failed_events = connection.execute(
                """
                SELECT count(*) AS n
                FROM loader_control.notification_outbox
                WHERE job_id = %s AND event_type = 'etl_failed'
                """,
                (handle.job_id,),
            ).fetchone()["n"]
        self.assertEqual(job, {"status": "failed", "failure_code": "WORKER_LOST"})
        self.assertEqual(release, {"status": "failed", "cleanup_pending": False})
        self.assertEqual(stage_count, 0)
        self.assertEqual(failed_events, 1)

    def test_corrupt_candidate_rolls_back_atomically_and_keeps_old_release_visible(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2))
        store, base_handle, _summary, activation = self._activate_rows(rows, policy=policy)
        base_release = activation.release_id
        with self._connection("loader") as connection:
            maximum_token = connection.execute(
                """
                SELECT source_key_token
                FROM loader_control.source_disposition
                WHERE release_id = %s
                ORDER BY source_key_token DESC
                LIMIT 1
                """,
                (base_release,),
            ).fetchone()["source_key_token"]
        candidate = self._install_incremental_clone(
            store=store,
            base_release=base_release,
            upper_token=maximum_token,
        )
        with self._admin_connection() as admin:
            admin.execute(
                """
                UPDATE publication.public_species
                SET total_records = total_records + 1
                WHERE release_id = %s
                """,
                (candidate.release_id,),
            )

        with self.assertRaises(self.psycopg.errors.CheckViolation):
            store._cursor.execute(
                "SELECT loader_control.activate_validated_release(%s)",
                (candidate.release_id,),
            )

        with self._connection("loader") as connection:
            state = connection.execute(
                """
                SELECT s.active_release_id, active.status AS active_status,
                       candidate.status AS candidate_status
                FROM loader_control.source_state AS s
                JOIN loader_control.release AS active
                  ON active.release_id = s.active_release_id
                JOIN loader_control.release AS candidate
                  ON candidate.release_id = %s
                WHERE s.source_id = %s
                """,
                (candidate.release_id, SOURCE_ID),
            ).fetchone()
        self.assertEqual(
            state,
            {
                "active_release_id": base_release,
                "active_status": "active",
                "candidate_status": "candidate",
            },
        )
        with self._connection("api") as connection:
            visible = connection.execute("SELECT release_id FROM serve.public_release").fetchall()
        self.assertEqual(visible, [{"release_id": base_handle.release_id}])

        store.fail(candidate, "LOADER_CANDIDATE_INVALID")
        with self._connection("loader") as connection:
            candidate_rows = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM loader_control.source_disposition
                     WHERE release_id = %s)
                    + (SELECT count(*) FROM publication.public_release
                       WHERE release_id = %s) AS n
                """,
                (candidate.release_id, candidate.release_id),
            ).fetchone()["n"]
        self.assertEqual(candidate_rows, 0)

    def test_nonmaximum_upper_token_is_rejected_for_a_dated_inventory(self) -> None:
        policy = _policy()
        rows = (_disposition(1), _disposition(2))
        store, base_handle, _summary, activation = self._activate_rows(rows, policy=policy)
        base_release = activation.release_id
        with self._connection("loader") as connection:
            tokens = [
                row["source_key_token"]
                for row in connection.execute(
                    """
                    SELECT source_key_token
                    FROM loader_control.source_disposition
                    WHERE release_id = %s
                    ORDER BY source_key_token
                    """,
                    (base_release,),
                ).fetchall()
            ]
        self.assertGreaterEqual(len(tokens), 2)
        nonmaximum_upper_token = tokens[0]
        self.assertLess(nonmaximum_upper_token, tokens[-1])
        candidate = self._install_incremental_clone(
            store=store,
            base_release=base_release,
            upper_token=nonmaximum_upper_token,
        )

        # The candidate otherwise has a complete, unchanged replacement ledger
        # and empty change set.  The only adversarial defect is choosing the
        # lower of two tokens on the maximum date as its watermark.
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            store._cursor.execute(
                "SELECT loader_control.activate_validated_release(%s)",
                (candidate.release_id,),
            )
        store.fail(candidate, "LOADER_CANDIDATE_INVALID")

        with self._connection("api") as connection:
            visible = connection.execute("SELECT release_id FROM serve.public_release").fetchall()
        self.assertEqual(visible, [{"release_id": base_handle.release_id}])

        # Mutation-proof control: rebuilding the same complete candidate with
        # the greatest token must activate.  Therefore the rejection above is
        # specifically the nonmaximum watermark, not a missing aggregate/check.
        maximum_candidate = self._install_incremental_clone(
            store=store,
            base_release=base_release,
            upper_token=tokens[-1],
        )
        result = store._cursor.execute(
            "SELECT loader_control.activate_validated_release(%s) AS release_id",
            (maximum_candidate.release_id,),
        ).fetchone()
        self.assertEqual(result, {"release_id": maximum_candidate.release_id})
        with self._connection("api") as connection:
            visible = connection.execute("SELECT release_id FROM serve.public_release").fetchall()
        self.assertEqual(visible, [{"release_id": maximum_candidate.release_id}])


if __name__ == "__main__":
    unittest.main(verbosity=1)

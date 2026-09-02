"""PostgreSQL release coordinator for bounded, atomic BRERC snapshot loads.

Raw source rows never enter this module. The trusted source connector yields
only HMAC-keyed :class:`etl.streaming.SafeDisposition` batches. They are staged
under an invisible candidate, suppressed and aggregated across the complete
snapshot in PostgreSQL, validated, and finally activated by the database's
sole SECURITY DEFINER activation routine.

The public entry point intentionally remains blocked by the current real BRERC
source contract. Private synthetic tests exercise the complete implementation
with a reviewed synthetic contract; this is not authority to publish live data.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Protocol
from uuid import UUID, uuid4

from brerc_source import SourceConnectorConfig, TrustedPostgreSQLSourceConnector
from brerc_source.config import SourceConfigError, load_source_config
from brerc_source.errors import TrustedSourceConnectorError
from brerc_source.models import SafeSourceSnapshotEvidence, cursor_column_names, mapping_row
from etl.pipeline import ColumnMap
from etl.policy import InvalidPolicy, PolicyNotApproved, PublicationPolicy
from etl.source_contract import (
    BRERC_MAIN_DATA_DASH,
    IncrementalLoadBlocked,
    SourceContract,
    SourceContractError,
)
from etl.source_contract import (
    LoadMode as SourceLoadMode,
)
from etl.species import SpeciesDictionary
from etl.streaming import SafeDisposition, validate_streaming_policy_inputs

from .config import LoaderConfig
from .digest import (
    DIGEST_PROFILE,
    PUBLIC_RELEASE_DIGEST_TABLES,
    SOURCE_RESULT_DIGEST_TABLES,
    DigestTable,
    ReleaseDigest,
)
from .errors import (
    IncrementalSourceContractBlocked,
    LoaderAlreadyRunning,
    LoaderCandidateInvalid,
    LoaderCleanupFailed,
    LoaderCleanupPending,
    LoaderConfigurationError,
    LoaderConnectionFailed,
    LoaderError,
    LoaderExecutionFailed,
    LoaderPolicyInvalid,
    LoaderReleaseBlocked,
    LoaderSourceCountRejected,
    LoaderTargetProtocolError,
)
from .models import LoaderRunReport, LoadMode, RunState
from .policy_artifact import parse_publication_policy_artifact
from .species_dictionary import parse_species_dictionary_artifact

LOADER_VERSION = "brerc-postgres-loader-v3"
PROJECTION_VERSION = "brerc-main-data-dash-safe-projection-v1"
SOURCE_RESULT_EVIDENCE_PROFILE = "brerc-source-result-evidence-v2"
SOURCE_ID = "dashboard.main_data_dash"
TARGET_BEGIN = "BEGIN"
TARGET_COMMIT = "COMMIT"
TARGET_ROLLBACK = "ROLLBACK"
TARGET_SESSION_SQL = """
SELECT
    current_database() AS database_name,
    current_user AS loader_role,
    pg_catalog.inet_server_addr() IS NOT NULL AS tcp_transport,
    COALESCE(
        (
            SELECT ssl
            FROM pg_catalog.pg_stat_ssl
            WHERE pid = pg_catalog.pg_backend_pid()
        ),
        false
    ) AS tls_active,
    current_setting('server_encoding') AS server_encoding,
    current_setting('server_version_num')::integer AS server_version_num,
    (
        SELECT extversion
        FROM pg_catalog.pg_extension
        WHERE extname = 'postgis'
    ) AS postgis_version,
    deployment_login.rolcanlogin AS login_can_login,
    deployment_login.rolinherit AS login_inherits,
    deployment_login.rolsuper AS login_superuser,
    deployment_login.rolcreatedb AS login_createdb,
    deployment_login.rolcreaterole AS login_createrole,
    deployment_login.rolreplication AS login_replication,
    deployment_login.rolbypassrls AS login_bypassrls,
    ARRAY(
        SELECT parent.rolname::text
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid
        WHERE membership.member = deployment_login.oid
        ORDER BY parent.rolname
    ) AS direct_role_memberships
FROM pg_catalog.pg_roles AS deployment_login
WHERE deployment_login.rolname = current_user
""".strip()
TARGET_SESSION_HEADER = (
    "database_name",
    "loader_role",
    "tcp_transport",
    "tls_active",
    "server_encoding",
    "server_version_num",
    "postgis_version",
    "login_can_login",
    "login_inherits",
    "login_superuser",
    "login_createdb",
    "login_createrole",
    "login_replication",
    "login_bypassrls",
    "direct_role_memberships",
)
TARGET_MIGRATION_SQL = """
SELECT migration_version, migration_key
FROM loader_control.schema_migration
ORDER BY migration_version
""".strip()
TARGET_MIGRATION_HEADER = ("migration_version", "migration_key")
TARGET_IDENTITY_SQL = """
SELECT environment_id, database_name
FROM loader_control.deployment_identity
WHERE singleton IS TRUE
""".strip()
TARGET_IDENTITY_HEADER = ("environment_id", "database_name")
TARGET_LOCK_SQL = (
    "SELECT pg_catalog.pg_try_advisory_lock(pg_catalog.hashtextextended(%s, 0)) AS acquired"
)
TARGET_UNLOCK_SQL = (
    "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended(%s, 0)) AS released"
)

_FAILURE_CODES = frozenset(
    {
        "LOADER_FAILED",
        "INCREMENTAL_SOURCE_CONTRACT_BLOCKED",
        "LOADER_ALREADY_RUNNING",
        "LOADER_CANDIDATE_INVALID",
        "LOADER_CLEANUP_FAILED",
        "LOADER_CLEANUP_PENDING",
        "LOADER_CONFIGURATION_INVALID",
        "LOADER_COORDINATOR_UNAVAILABLE",
        "LOADER_EXECUTION_FAILED",
        "LOADER_POLICY_INVALID",
        "LOADER_RELEASE_BLOCKED",
        "LOADER_SOURCE_COUNT_REJECTED",
        "LOADER_TARGET_CONNECTION_FAILED",
        "LOADER_TARGET_PROTOCOL_INVALID",
    }
)

_RECONCILIATION_CODES = (
    "SOURCE_INVENTORY",
    "SOURCE_DISPOSITIONS",
    "PUBLIC_CELL_TOTAL",
    "PUBLIC_SPECIES_YEAR_TOTAL",
    "PUBLIC_SPECIES_TOTAL",
    "PRIVACY_ALLOWLIST",
    "DATABASE_DIGEST",
    "ACTIVATION_THRESHOLDS",
)


class _Cursor(Protocol):
    description: object

    def execute(self, query: object, params: Sequence[object] | None = None) -> object: ...

    def executemany(self, query: object, params_seq: Sequence[Sequence[object]]) -> object: ...

    def fetchone(self) -> object: ...

    def fetchmany(self, size: int = 0) -> Sequence[object]: ...

    def close(self) -> None: ...


class _Connection(Protocol):
    def cursor(self, name: str | None = None, **kwargs: object) -> _Cursor: ...

    def rollback(self) -> None: ...

    def cancel_safe(self, *, timeout: float = 0.0) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class _CandidateHandle:
    job_id: UUID
    release_id: UUID
    base_release_id: UUID | None
    mode: LoadMode = LoadMode.INITIAL


@dataclass(frozen=True)
class _CandidateSummary:
    source_rows: int
    published_records: int
    distribution_cells: int
    candidate_sha256: str


@dataclass(frozen=True)
class _ActivationResult:
    run_id: UUID
    release_id: UUID
    source_rows: int
    published_records: int
    distribution_cells: int
    candidate_sha256: str
    reused_active_release: bool


@dataclass(frozen=True)
class _FailureState:
    release_status: str
    job_status: str
    failure_code: str
    cleanup_pending: bool
    active_release_id: UUID | None
    failure_event_count: int


class _SourceConnector(Protocol):
    def _open_safe_initial_snapshot(self, **kwargs: object) -> object: ...


class _TargetStore(Protocol):
    def acquire(self, source_id: str) -> None: ...

    def begin_initial(
        self,
        source_id: str,
        attempt: _CandidateHandle,
    ) -> _CandidateHandle: ...

    def begin_refresh(
        self,
        source_id: str,
        attempt: _CandidateHandle,
    ) -> _CandidateHandle: ...

    def stage_batch(
        self,
        handle: _CandidateHandle,
        batch: tuple[SafeDisposition, ...],
    ) -> None: ...

    def finalize(
        self,
        handle: _CandidateHandle,
        *,
        evidence: SafeSourceSnapshotEvidence,
        policy: PublicationPolicy,
        source_contract: SourceContract,
        projection: tuple[str, ...],
        policy_artifact_sha256: str,
        species_dictionary_artifact_sha256: str,
        species_dictionary_sha256: str,
    ) -> _CandidateSummary: ...

    def activate(
        self,
        handle: _CandidateHandle,
        summary: _CandidateSummary,
    ) -> _ActivationResult: ...

    def fail(self, handle: _CandidateHandle, failure_code: str) -> None: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


def _sanitise(exception: BaseException) -> BaseException:
    exception.__cause__ = None
    exception.__context__ = None
    exception.__suppress_context__ = True
    exception.__traceback__ = None
    return exception


def _default_target_connection_factory(config: LoaderConfig) -> _Connection:
    configuration_failed = False
    try:
        config.target_connection.assert_process_environment()
    except Exception:
        configuration_failed = True
    if configuration_failed:
        raise _sanitise(LoaderConfigurationError())
    try:
        psycopg = importlib.import_module("psycopg")
        rows = importlib.import_module("psycopg.rows")
    except ImportError:
        raise _sanitise(LoaderConnectionFailed()) from None
    try:
        return psycopg.connect(  # type: ignore[no-any-return]
            autocommit=True,
            row_factory=rows.dict_row,
            **config.target_connection.parameters(),
        )
    except Exception:
        raise _sanitise(LoaderConnectionFailed()) from None


def _source_connector_factory(config: SourceConnectorConfig) -> _SourceConnector:
    return TrustedPostgreSQLSourceConnector.from_config(config)


def _target_store_factory(config: LoaderConfig) -> _TargetStore:
    return _PostgreSQLTargetStore(config)


def _one(cursor: _Cursor, expected_header: Sequence[str]) -> dict[str, object]:
    try:
        header = cursor_column_names(cursor.description)
    except ValueError:
        raise LoaderTargetProtocolError() from None
    if header != tuple(expected_header):
        raise LoaderTargetProtocolError()
    first = cursor.fetchone()
    if first is None or cursor.fetchone() is not None:
        raise LoaderTargetProtocolError()
    try:
        row = mapping_row(first, header)
    except ValueError:
        raise LoaderTargetProtocolError() from None
    if tuple(row) != header:
        raise LoaderTargetProtocolError()
    return row


def _execute(
    cursor: _Cursor,
    query: object,
    params: Sequence[object] | None = None,
) -> None:
    if params is None:
        cursor.execute(query)
    else:
        cursor.execute(query, params)


def _canonical_json_sha256(document: object) -> str:
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _compatibility_sha256(
    *,
    source_contract_version: str,
    source_contract_sha256: str,
    observed_view_definition_sha256: str,
    observed_view_identity_sha256: str,
    projection_sha256: str,
    publication_policy_version: str,
    publication_policy_sha256: str,
    policy_approval_sha256: str,
    species_dictionary_sha256: str,
    sensitivity_snapshot_sha256: str,
    reconciliation_key_sha256: str,
) -> str:
    """Bind code/schema/policy/key identity, never snapshot-specific row evidence."""
    return _canonical_json_sha256(
        {
            "digestProfile": DIGEST_PROFILE,
            "etlVersion": LOADER_VERSION,
            "observedViewDefinitionSha256": observed_view_definition_sha256,
            "observedViewIdentitySha256": observed_view_identity_sha256,
            "policyApprovalSha256": policy_approval_sha256,
            "projectionSha256": projection_sha256,
            "projectionVersion": PROJECTION_VERSION,
            "publicationPolicySha256": publication_policy_sha256,
            "publicationPolicyVersion": publication_policy_version,
            "reconciliationKeySha256": reconciliation_key_sha256,
            "sensitivitySnapshotSha256": sensitivity_snapshot_sha256,
            "sourceContractSha256": source_contract_sha256,
            "sourceContractVersion": source_contract_version,
            "sourceResultEvidenceProfile": SOURCE_RESULT_EVIDENCE_PROFILE,
            "speciesDictionarySha256": species_dictionary_sha256,
        }
    )


def _check_deadline(deadline: float, target: _TargetStore | None = None) -> None:
    if time.monotonic() < deadline:
        return
    if target is not None:
        with suppress(Exception):
            target.cancel()
    raise LoaderExecutionFailed()


def _source_count_bounds(config: LoaderConfig, mode: LoadMode) -> tuple[int, int]:
    if mode is LoadMode.INITIAL:
        return (
            config.runtime.initial_min_source_rows,
            config.runtime.initial_max_source_rows,
        )
    if mode is LoadMode.REFRESH:
        return (
            config.runtime.refresh_min_source_rows,
            config.runtime.refresh_max_source_rows,
        )
    raise LoaderConfigurationError()


def _valid_snapshot_handle(handle: object) -> bool:
    return isinstance(handle, _CandidateHandle) and (
        (handle.mode is LoadMode.INITIAL and handle.base_release_id is None)
        or (handle.mode is LoadMode.REFRESH and handle.base_release_id is not None)
    )


def run_load(config: LoaderConfig, mode: LoadMode) -> LoaderRunReport:
    """Run the configured load without exposing policy/source injection hooks."""
    if not isinstance(config, LoaderConfig) or not isinstance(mode, LoadMode):
        raise _sanitise(LoaderConfigurationError())
    if mode is LoadMode.INCREMENTAL:
        raise _sanitise(IncrementalSourceContractBlocked())
    try:
        policy = parse_publication_policy_artifact(
            config.publication.artifact_bytes(),
            expected_sha256=config.publication.expected_sha256,
            public_id_secret=config.publication.public_id_secret_bytes(),
        )
    except LoaderPolicyInvalid as exc:
        raise _sanitise(exc) from None
    try:
        dictionary = parse_species_dictionary_artifact(config.species_dictionary.artifact_bytes())
    except (LoaderConfigurationError, LoaderPolicyInvalid) as exc:
        raise _sanitise(exc) from None
    dictionary_sha256 = dictionary.digest()
    if (
        not _is_sha256(dictionary_sha256)
        or not _is_sha256(policy.species_dictionary_sha256)
        or not hmac.compare_digest(dictionary_sha256, policy.species_dictionary_sha256)
    ):
        raise _sanitise(LoaderPolicyInvalid())
    try:
        BRERC_MAIN_DATA_DASH.require_mode(SourceLoadMode.INITIAL)
        policy.validate()
        policy.assert_approved()
        BRERC_MAIN_DATA_DASH.assert_release_ready()
    except (InvalidPolicy, PolicyNotApproved):
        raise _sanitise(LoaderPolicyInvalid()) from None
    except (IncrementalLoadBlocked, SourceContractError):
        raise _sanitise(LoaderReleaseBlocked()) from None
    try:
        source_config = load_source_config(
            config.source_config_path,
            contract=BRERC_MAIN_DATA_DASH,
        )
    except (SourceConfigError, OSError, ValueError, TypeError):
        raise _sanitise(LoaderConfigurationError()) from None
    return _run_initial_with_inputs(
        config,
        mode=mode,
        source_config=source_config,
        source_contract=BRERC_MAIN_DATA_DASH,
        columns=source_config.column_map,
        policy=policy,
        dictionary=dictionary,
        species_dictionary_artifact_sha256=(config.species_dictionary.expected_raw_sha256),
    )


def _run_initial_with_inputs(
    config: LoaderConfig,
    *,
    mode: LoadMode = LoadMode.INITIAL,
    source_config: SourceConnectorConfig,
    source_contract: SourceContract,
    columns: ColumnMap,
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None = None,
    species_dictionary_artifact_sha256: str | None = None,
) -> LoaderRunReport:
    """Private synthetic-testable full-snapshot orchestration.

    ``refresh`` is a destination lifecycle mode.  Source extraction deliberately
    remains the approval-bound complete ``INITIAL`` snapshot protocol.
    """
    if mode not in (LoadMode.INITIAL, LoadMode.REFRESH) or not isinstance(
        policy, PublicationPolicy
    ):
        raise _sanitise(LoaderPolicyInvalid())
    dictionary_sha256 = dictionary.digest() if isinstance(dictionary, SpeciesDictionary) else None
    if (
        not _is_sha256(dictionary_sha256)
        or not _is_sha256(policy.species_dictionary_sha256)
        or not hmac.compare_digest(dictionary_sha256, policy.species_dictionary_sha256)
        or not _is_sha256(species_dictionary_artifact_sha256)
    ):
        raise _sanitise(LoaderPolicyInvalid())
    try:
        validate_streaming_policy_inputs(policy=policy, dictionary=dictionary)
        source_contract.require_mode(SourceLoadMode.INITIAL)
        policy.validate()
        policy.assert_approved()
        source_contract.assert_release_ready()
        source_contract.validate_safety_mapping(columns, policy)
        projection = (*columns.required(), *columns.optional())
        source_contract.validate_result_header(projection, projection)
    except (InvalidPolicy, PolicyNotApproved):
        raise _sanitise(LoaderPolicyInvalid()) from None
    except (IncrementalLoadBlocked, SourceContractError):
        raise _sanitise(LoaderReleaseBlocked()) from None

    deadline = time.monotonic() + config.runtime.total_timeout_seconds
    target: _TargetStore | None = None
    handle: _CandidateHandle | None = None
    result: LoaderRunReport | None = None
    failure: BaseException | None = None
    try:
        _check_deadline(deadline)
        target = _target_store_factory(config)
        if isinstance(target, _PostgreSQLTargetStore):
            target._bind_deadline(deadline)
        _check_deadline(deadline, target)
        target.acquire(SOURCE_ID)
        _check_deadline(deadline, target)
        attempt = _CandidateHandle(
            job_id=uuid4(),
            release_id=uuid4(),
            base_release_id=None,
            mode=mode,
        )
        handle = attempt
        begun = (
            target.begin_initial(SOURCE_ID, attempt)
            if mode is LoadMode.INITIAL
            else target.begin_refresh(SOURCE_ID, attempt)
        )
        if (
            not isinstance(begun, _CandidateHandle)
            or begun.job_id != attempt.job_id
            or begun.release_id != attempt.release_id
            or begun.mode is not mode
            or (mode is LoadMode.INITIAL and begun.base_release_id is not None)
            or (mode is LoadMode.REFRESH and begun.base_release_id is None)
        ):
            raise LoaderCandidateInvalid()
        handle = begun
        _check_deadline(deadline, target)
        source = _source_connector_factory(source_config)
        snapshot_context = source._open_safe_initial_snapshot(
            source_contract=source_contract,
            columns=columns,
            policy=policy,
            reconciliation_secret=config.reconciliation.secret_bytes(),
            dictionary=dictionary,
            absolute_deadline=deadline,
        )
        staged_rows = 0
        approved_minimum, approved_maximum = _source_count_bounds(config, mode)
        with snapshot_context as snapshot:
            for batch in snapshot:
                _check_deadline(deadline, target)
                if not isinstance(batch, tuple) or not batch:
                    raise LoaderCandidateInvalid()
                maximum = config.runtime.batch_size
                for start in range(0, len(batch), maximum):
                    _check_deadline(deadline, target)
                    chunk = batch[start : start + maximum]
                    if staged_rows + len(chunk) > approved_maximum:
                        raise LoaderSourceCountRejected()
                    target.stage_batch(handle, chunk)
                    staged_rows += len(chunk)
            evidence = snapshot.evidence

        _check_deadline(deadline, target)

        if (
            staged_rows != evidence.rows_seen
            or not approved_minimum <= evidence.rows_seen <= approved_maximum
        ):
            raise LoaderSourceCountRejected()
        if not _is_sha256(evidence.observed_species_dictionary_sha256) or not hmac.compare_digest(
            evidence.observed_species_dictionary_sha256,
            dictionary_sha256,
        ):
            raise LoaderCandidateInvalid()
        summary = target.finalize(
            handle,
            evidence=evidence,
            policy=policy,
            source_contract=source_contract,
            projection=projection,
            policy_artifact_sha256=config.publication.expected_sha256,
            species_dictionary_artifact_sha256=(species_dictionary_artifact_sha256),
            species_dictionary_sha256=dictionary_sha256,
        )
        _check_deadline(deadline, target)
        if summary.source_rows != evidence.rows_seen:
            raise LoaderCandidateInvalid()
        if summary.distribution_cells < 1:
            raise LoaderCandidateInvalid()
        activation = target.activate(handle, summary)
        result = LoaderRunReport(
            run_id=str(activation.run_id),
            release_id=str(activation.release_id),
            mode=mode,
            state=RunState.SUCCEEDED,
            source_rows=activation.source_rows,
            public_records=activation.published_records,
            distribution_cells=activation.distribution_cells,
            candidate_sha256=activation.candidate_sha256,
            activated=True,
            reused_active_release=activation.reused_active_release,
        )
    except LoaderError as exc:
        failure = exc
    except TrustedSourceConnectorError:
        failure = LoaderExecutionFailed()
    except (KeyboardInterrupt, SystemExit) as exc:
        failure = exc
    except Exception:
        failure = LoaderExecutionFailed()

    cleanup_failed = False
    terminal_failure_recorded = False
    if failure is not None and target is not None and handle is not None:
        try:
            target.fail(handle, getattr(failure, "code", "LOADER_EXECUTION_FAILED"))
            terminal_failure_recorded = True
        except Exception:
            cleanup_failed = True
    if target is not None:
        try:
            target.close()
        except Exception:
            cleanup_failed = True
    # Activation is the authoritative terminal boundary. A socket/rollback
    # error while closing an already-committed successful session cannot undo
    # the active pointer, so it must not turn a published release into a false
    # CLI failure. On every pre-activation failure, cleanup failure remains
    # fatal because the database state is not known to be terminal and safe.
    if cleanup_failed and result is None and not terminal_failure_recorded:
        raise _sanitise(LoaderCleanupFailed())
    if failure is not None:
        raise _sanitise(failure)
    if result is None:
        raise _sanitise(LoaderExecutionFailed())
    return result


class _PostgreSQLTargetStore:
    """Concrete insert-only target writer; activation authority stays in SQL.

    The absolute deadline is enforced cooperatively and as a refreshed
    PostgreSQL ``statement_timeout``.  It bounds server work, but cannot be a
    hard wall-clock guarantee while the network or database driver itself is
    unresponsive; cancellation and the connector's network timeouts cover that
    separate failure mode.
    """

    def __init__(self, config: LoaderConfig) -> None:
        self._config = config
        self._absolute_deadline = time.monotonic() + config.runtime.total_timeout_seconds
        self._connection = _default_target_connection_factory(config)
        self._control: _Cursor | None = None
        self._locked_source: str | None = None
        self._closed = False
        try:
            self._control = self._configure_connection(self._connection)
        except LoaderError:
            self.close()
            raise
        except Exception:
            self.close()
            raise _sanitise(LoaderTargetProtocolError()) from None

    @property
    def _cursor(self) -> _Cursor:
        if self._control is None or self._closed:
            raise LoaderTargetProtocolError()
        return self._control

    def _bind_deadline(self, absolute_deadline: float) -> None:
        if not isinstance(absolute_deadline, float) or absolute_deadline <= time.monotonic():
            raise LoaderExecutionFailed()
        self._absolute_deadline = min(self._absolute_deadline, absolute_deadline)

    def _remaining_statement_ms(self) -> int:
        remaining = int((self._absolute_deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            self.cancel()
            raise LoaderExecutionFailed()
        return max(1, min(remaining, self._config.runtime.statement_timeout_ms))

    def _set_statement_budget(self, cursor: _Cursor, *, local: bool = False) -> None:
        scope = "LOCAL " if local else ""
        _execute(cursor, f"SET {scope}statement_timeout = {self._remaining_statement_ms()}")

    def _extend_for_recovery(self) -> float:
        """Open a small bounded ACK/terminal-cleanup window; return workload deadline."""
        workload_deadline = self._absolute_deadline
        recovery_seconds = min(
            5.0,
            self._config.runtime.statement_timeout_ms / 1000.0,
        )
        self._absolute_deadline = time.monotonic() + recovery_seconds
        return workload_deadline

    def _begin(self, cursor: _Cursor) -> None:
        self._set_statement_budget(cursor)
        _execute(cursor, TARGET_BEGIN)
        self._set_statement_budget(cursor, local=True)
        _execute(
            cursor,
            f"SET LOCAL lock_timeout = {min(self._remaining_statement_ms(), self._config.runtime.lock_timeout_ms)}",
        )

    def _tx_execute(
        self,
        cursor: _Cursor,
        query: object,
        params: Sequence[object] | None = None,
    ) -> None:
        self._set_statement_budget(cursor, local=True)
        _execute(cursor, query, params)

    def _configure_connection(self, connection: _Connection) -> _Cursor:
        cursor = connection.cursor()
        runtime = self._config.runtime
        self._set_statement_budget(cursor)
        _execute(cursor, f"SET lock_timeout = {runtime.lock_timeout_ms}")
        _execute(cursor, "SET client_encoding = 'UTF8'")
        _execute(cursor, "SET TimeZone = 'UTC'")
        self._set_statement_budget(cursor)
        _execute(cursor, TARGET_SESSION_SQL)
        session = _one(cursor, TARGET_SESSION_HEADER)
        direct_memberships = session["direct_role_memberships"]
        if (
            session["database_name"] != runtime.expected_target_database
            or session["loader_role"] != runtime.expected_target_role
            or session["tcp_transport"] is not True
            or session["tls_active"] is not True
            or session["server_encoding"] != "UTF8"
            or type(session["server_version_num"]) is not int
            or session["server_version_num"] // 10_000 != 16
            or not isinstance(session["postgis_version"], str)
            or not (
                session["postgis_version"] == "3.5" or session["postgis_version"].startswith("3.5.")
            )
            or session["login_can_login"] is not True
            or session["login_inherits"] is not True
            or session["login_superuser"] is not False
            or session["login_createdb"] is not False
            or session["login_createrole"] is not False
            or session["login_replication"] is not False
            or session["login_bypassrls"] is not False
            or not isinstance(direct_memberships, list | tuple)
            or tuple(direct_memberships) != ("brerc_loader",)
        ):
            raise LoaderTargetProtocolError()
        self._set_statement_budget(cursor)
        _execute(cursor, TARGET_MIGRATION_SQL)
        if cursor_column_names(cursor.description) != TARGET_MIGRATION_HEADER:
            raise LoaderTargetProtocolError()
        migrations: list[object] = []
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            migrations.append(row)
        if len(migrations) != 3:
            raise LoaderTargetProtocolError()
        observed_migrations = tuple(
            mapping_row(migration, TARGET_MIGRATION_HEADER) for migration in migrations
        )
        if observed_migrations != (
            {"migration_version": 1, "migration_key": "0001_publication_store"},
            {"migration_version": 2, "migration_key": "0002_sensitive_record_action"},
            {"migration_version": 3, "migration_key": "0003_full_snapshot_refresh"},
        ):
            raise LoaderTargetProtocolError()
        self._set_statement_budget(cursor)
        _execute(cursor, TARGET_IDENTITY_SQL)
        identity = _one(cursor, TARGET_IDENTITY_HEADER)
        if (
            identity["environment_id"] != runtime.expected_target_environment_id
            or identity["database_name"] != runtime.expected_target_database
        ):
            raise LoaderTargetProtocolError()
        return cursor

    def _replace_connection_and_lock(self, source_id: str) -> None:
        old_cursor = self._control
        old_connection = self._connection
        self._control = None
        self._locked_source = None
        if old_cursor is not None:
            with suppress(Exception):
                old_cursor.close()
        with suppress(Exception):
            old_connection.close()
        try:
            replacement = _default_target_connection_factory(self._config)
            replacement_cursor = self._configure_connection(replacement)
            self._set_statement_budget(replacement_cursor)
            _execute(replacement_cursor, TARGET_LOCK_SQL, (source_id,))
            locked = _one(replacement_cursor, ("acquired",))
            if locked["acquired"] is not True:
                raise LoaderAlreadyRunning()
        except Exception:
            if "replacement_cursor" in locals():
                with suppress(Exception):
                    replacement_cursor.close()
            if "replacement" in locals():
                with suppress(Exception):
                    replacement.close()
            self._closed = True
            raise
        self._connection = replacement
        self._control = replacement_cursor
        self._locked_source = source_id
        self._closed = False

    @staticmethod
    def _require_rowcount(cursor: _Cursor, expected: int) -> None:
        rowcount = getattr(cursor, "rowcount", None)
        if isinstance(rowcount, int) and rowcount >= 0 and rowcount != expected:
            raise LoaderCandidateInvalid()

    def _transaction(self, statements: Sequence[tuple[object, Sequence[object] | None]]) -> None:
        cursor = self._cursor
        try:
            self._begin(cursor)
            for query, params in statements:
                self._tx_execute(cursor, query, params)
            self._set_statement_budget(cursor, local=True)
            _execute(cursor, TARGET_COMMIT)
        except Exception:
            with suppress(Exception):
                _execute(cursor, TARGET_ROLLBACK)
            raise

    def acquire(self, source_id: str) -> None:
        if source_id != SOURCE_ID or self._locked_source is not None:
            raise LoaderTargetProtocolError()
        self._set_statement_budget(self._cursor)
        _execute(self._cursor, TARGET_LOCK_SQL, (source_id,))
        row = _one(self._cursor, ("acquired",))
        if row["acquired"] is not True:
            raise LoaderAlreadyRunning()
        self._locked_source = source_id
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "SELECT loader_control.recover_orphaned_job(%s) AS recovered",
            (source_id,),
        )
        recovered = _one(self._cursor, ("recovered",))["recovered"]
        if type(recovered) is not int or recovered not in (0, 1):
            raise LoaderTargetProtocolError()
        try:
            for release_id in self._pending_cleanup_release_ids(source_id):
                self._discard_inactive_release(release_id)
            if self._pending_cleanup_release_ids(source_id):
                raise LoaderCleanupPending()
        except LoaderCleanupPending:
            raise
        except Exception:
            raise LoaderCleanupPending() from None

    def _pending_cleanup_release_ids(self, source_id: str) -> tuple[UUID, ...]:
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "SELECT release_id FROM loader_control.release "
            "WHERE source_id = %s AND cleanup_pending "
            "AND status IN ('failed', 'discarded') "
            "ORDER BY created_at, release_id",
            (source_id,),
        )
        header = ("release_id",)
        if cursor_column_names(self._cursor.description) != header:
            raise LoaderTargetProtocolError()
        release_ids: list[UUID] = []
        while True:
            raw = self._cursor.fetchone()
            if raw is None:
                break
            row = mapping_row(raw, header)
            try:
                release_ids.append(UUID(str(row["release_id"])))
            except (TypeError, ValueError):
                raise LoaderTargetProtocolError() from None
        return tuple(release_ids)

    def begin_initial(
        self,
        source_id: str,
        attempt: _CandidateHandle,
    ) -> _CandidateHandle:
        if (
            self._locked_source != source_id
            or not isinstance(attempt, _CandidateHandle)
            or attempt.base_release_id is not None
            or attempt.mode is not LoadMode.INITIAL
        ):
            raise LoaderTargetProtocolError()
        return self._begin_snapshot_once(source_id, attempt, allow_ack_retry=True)

    def begin_refresh(
        self,
        source_id: str,
        attempt: _CandidateHandle,
    ) -> _CandidateHandle:
        if (
            self._locked_source != source_id
            or not isinstance(attempt, _CandidateHandle)
            or attempt.base_release_id is not None
            or attempt.mode is not LoadMode.REFRESH
        ):
            raise LoaderTargetProtocolError()
        return self._begin_snapshot_once(source_id, attempt, allow_ack_retry=True)

    def _begin_snapshot_once(
        self,
        source_id: str,
        attempt: _CandidateHandle,
        *,
        allow_ack_retry: bool,
    ) -> _CandidateHandle:
        cursor = self._cursor
        commit_sent = False
        try:
            self._begin(cursor)
            self._tx_execute(
                cursor,
                "INSERT INTO loader_control.source_state (source_id) VALUES (%s) "
                "ON CONFLICT (source_id) DO NOTHING",
                (source_id,),
            )
            # Deliberately an unlocked read.  Two loaders cannot reach this
            # point concurrently: a snapshot begin refuses unless acquire() already
            # took the session-level advisory lock for this source
            # (TARGET_LOCK_SQL / pg_try_advisory_lock), which is held across
            # commits for the whole run, and active_release_id is only ever
            # written by loader_control.activate_release_candidate, a SECURITY
            # DEFINER function whose EXECUTE right is granted to this same role.
            #
            # A FOR UPDATE row lock here would additionally require the UPDATE
            # privilege on loader_control.source_state (PostgreSQL requires it
            # for every locking clause, including FOR KEY SHARE).  The reviewed
            # grant set gives brerc_loader only SELECT and INSERT (source_id) on
            # that table precisely so the loader login cannot repoint the live
            # public release outside the audited lifecycle function, so taking
            # the row lock is not an option we may buy back with a grant.
            self._tx_execute(
                cursor,
                "SELECT active_release_id FROM loader_control.source_state WHERE source_id = %s",
                (source_id,),
            )
            state = _one(cursor, ("active_release_id",))
            raw_base = state["active_release_id"]
            if attempt.mode is LoadMode.INITIAL and raw_base is not None:
                raise LoaderReleaseBlocked()
            if attempt.mode is LoadMode.REFRESH and raw_base is None:
                raise LoaderReleaseBlocked()
            if attempt.mode not in (LoadMode.INITIAL, LoadMode.REFRESH):
                raise LoaderTargetProtocolError()
            try:
                base_release_id = None if raw_base is None else UUID(str(raw_base))
            except (TypeError, ValueError):
                raise LoaderTargetProtocolError() from None
            self._tx_execute(
                cursor,
                "SELECT EXISTS (SELECT 1 FROM loader_control.release "
                "WHERE source_id = %s AND cleanup_pending) AS cleanup_pending",
                (source_id,),
            )
            pending = _one(cursor, ("cleanup_pending",))["cleanup_pending"]
            if type(pending) is not bool:
                raise LoaderTargetProtocolError()
            if pending:
                raise LoaderCleanupPending()
            self._tx_execute(
                cursor,
                "INSERT INTO loader_control.etl_job "
                "(job_id, source_id, load_mode, base_release_id, started_at, heartbeat_at) "
                "VALUES (%s, %s, %s, %s, transaction_timestamp(), transaction_timestamp())",
                (attempt.job_id, source_id, attempt.mode.value, base_release_id),
            )
            self._require_rowcount(cursor, 1)
            self._tx_execute(
                cursor,
                "UPDATE loader_control.etl_job SET status = 'extracting' "
                "WHERE job_id = %s AND source_id = %s AND status = 'queued'",
                (attempt.job_id, source_id),
            )
            self._require_rowcount(cursor, 1)
            self._tx_execute(
                cursor,
                "INSERT INTO loader_control.release "
                "(release_id, source_id, job_id, base_release_id, load_mode) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    attempt.release_id,
                    source_id,
                    attempt.job_id,
                    base_release_id,
                    attempt.mode.value,
                ),
            )
            self._require_rowcount(cursor, 1)
            self._set_statement_budget(cursor, local=True)
            commit_sent = True
            _execute(cursor, TARGET_COMMIT)
            return _CandidateHandle(
                job_id=attempt.job_id,
                release_id=attempt.release_id,
                base_release_id=base_release_id,
                mode=attempt.mode,
            )
        except (LoaderReleaseBlocked, LoaderCleanupPending):
            with suppress(Exception):
                _execute(cursor, TARGET_ROLLBACK)
            raise
        except Exception:
            with suppress(Exception):
                _execute(cursor, TARGET_ROLLBACK)
            if commit_sent:
                return self._recover_begin_ack(
                    source_id,
                    attempt,
                    allow_retry=allow_ack_retry,
                )
            raise LoaderCandidateInvalid() from None

    def _read_known_begin(
        self,
        source_id: str,
        attempt: _CandidateHandle,
    ) -> _CandidateHandle | None:
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "SELECT j.job_id, r.release_id, j.source_id AS job_source_id, "
            "r.source_id AS release_source_id, j.load_mode AS job_load_mode, "
            "r.load_mode AS release_load_mode, j.base_release_id AS job_base_release_id, "
            "r.base_release_id AS release_base_release_id, j.status AS job_status, "
            "r.status AS release_status, s.active_release_id "
            "FROM loader_control.etl_job AS j "
            "FULL JOIN loader_control.release AS r ON r.job_id = j.job_id "
            "LEFT JOIN loader_control.source_state AS s ON s.source_id = j.source_id "
            "WHERE j.job_id = %s OR r.release_id = %s",
            (attempt.job_id, attempt.release_id),
        )
        header = (
            "job_id",
            "release_id",
            "job_source_id",
            "release_source_id",
            "job_load_mode",
            "release_load_mode",
            "job_base_release_id",
            "release_base_release_id",
            "job_status",
            "release_status",
            "active_release_id",
        )
        if cursor_column_names(self._cursor.description) != header:
            raise LoaderTargetProtocolError()
        first = self._cursor.fetchone()
        if first is None:
            return None
        if self._cursor.fetchone() is not None:
            raise LoaderCandidateInvalid()
        row = mapping_row(first, header)
        try:
            job_id = UUID(str(row["job_id"]))
            release_id = UUID(str(row["release_id"]))
            raw_job_base = row["job_base_release_id"]
            raw_release_base = row["release_base_release_id"]
            job_base = None if raw_job_base is None else UUID(str(raw_job_base))
            release_base = None if raw_release_base is None else UUID(str(raw_release_base))
            raw_active = row["active_release_id"]
            active = None if raw_active is None else UUID(str(raw_active))
        except (TypeError, ValueError):
            raise LoaderCandidateInvalid() from None
        if (
            job_id != attempt.job_id
            or release_id != attempt.release_id
            or row["job_source_id"] != source_id
            or row["release_source_id"] != source_id
            or row["job_load_mode"] != attempt.mode.value
            or row["release_load_mode"] != attempt.mode.value
            or job_base != release_base
            or row["job_status"] != "extracting"
            or row["release_status"] != "candidate"
            or (attempt.mode is LoadMode.INITIAL and (job_base is not None or active is not None))
            or (attempt.mode is LoadMode.REFRESH and (job_base is None or active != job_base))
        ):
            raise LoaderCandidateInvalid()
        return _CandidateHandle(
            attempt.job_id,
            attempt.release_id,
            job_base,
            mode=attempt.mode,
        )

    def _recover_begin_ack(
        self,
        source_id: str,
        attempt: _CandidateHandle,
        *,
        allow_retry: bool,
    ) -> _CandidateHandle:
        original_deadline = self._extend_for_recovery()
        try:
            try:
                known = self._read_known_begin(source_id, attempt)
            except Exception:
                self._replace_connection_and_lock(source_id)
                known = self._read_known_begin(source_id, attempt)
        finally:
            self._absolute_deadline = original_deadline
        if known is not None:
            return known
        if not allow_retry or time.monotonic() >= original_deadline:
            raise LoaderCandidateInvalid()
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "SELECT loader_control.recover_orphaned_job(%s) AS recovered",
            (source_id,),
        )
        recovered = _one(self._cursor, ("recovered",))["recovered"]
        if type(recovered) is not int or recovered not in (0, 1):
            raise LoaderTargetProtocolError()
        return self._begin_snapshot_once(source_id, attempt, allow_ack_retry=False)

    @staticmethod
    def _stage_values(
        handle: _CandidateHandle,
        disposition: SafeDisposition,
    ) -> tuple[object, ...]:
        record = disposition.record
        eligible = record is not None
        return (
            handle.job_id,
            bytes.fromhex(disposition.source_token),
            "upsert" if eligible else "withhold",
            bytes.fromhex(disposition.source_fingerprint),
            disposition.withheld_reason,
            record.species_id if eligible else None,
            record.scientific_name if eligible else None,
            record.common_name if eligible else None,
            record.grid_ref if eligible else None,
            record.precision_metres if eligible else None,
            disposition.cell_id if eligible else None,
            disposition.cell_precision_metres if eligible else None,
            disposition.min_easting if eligible else None,
            disposition.min_northing if eligible else None,
            disposition.max_easting if eligible else None,
            disposition.max_northing if eligible else None,
            record.year if eligible else None,
            record.record_id if eligible else None,
            record.place if eligible else None,
            record.abundance if eligible else None,
            record.record_type if eligible else None,
            record.verified if eligible else None,
            record.source if eligible else None,
        )

    def stage_batch(
        self,
        handle: _CandidateHandle,
        batch: tuple[SafeDisposition, ...],
    ) -> None:
        if (
            not _valid_snapshot_handle(handle)
            or not batch
            or len(batch) > self._config.runtime.batch_size
        ):
            raise LoaderCandidateInvalid()
        values = [self._stage_values(handle, disposition) for disposition in batch]
        inventory = [(row[0], row[1], row[3]) for row in values]
        cursor = self._cursor
        try:
            self._begin(cursor)
            self._set_statement_budget(cursor, local=True)
            cursor.executemany(
                "INSERT INTO loader_stage.source_inventory "
                "(job_id, source_key_token, input_fingerprint, observed_modified_date) "
                "VALUES (%s, %s, %s, NULL)",
                inventory,
            )
            self._set_statement_budget(cursor, local=True)
            cursor.executemany(
                "INSERT INTO loader_stage.disposition_delta "
                "(job_id, source_key_token, action, input_fingerprint, withheld_reason, "
                "species_id, scientific_name, common_name, record_grid_ref, "
                "record_precision_metres, cell_id, cell_precision_metres, "
                "min_easting, min_northing, max_easting, max_northing, record_year, "
                "public_record_id, place, abundance, record_type, verified_status, source_label) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                values,
            )
            self._tx_execute(
                cursor,
                "UPDATE loader_control.etl_job SET heartbeat_at = transaction_timestamp() "
                "WHERE job_id = %s AND status = 'extracting'",
                (handle.job_id,),
            )
            self._require_rowcount(cursor, 1)
            self._set_statement_budget(cursor, local=True)
            _execute(cursor, TARGET_COMMIT)
        except Exception:
            with suppress(Exception):
                _execute(cursor, TARGET_ROLLBACK)
            raise LoaderCandidateInvalid() from None

    # Finalisation/activation are defined below to keep the row-staging boundary
    # reviewable on its own.

    def finalize(
        self,
        handle: _CandidateHandle,
        *,
        evidence: SafeSourceSnapshotEvidence,
        policy: PublicationPolicy,
        source_contract: SourceContract,
        projection: tuple[str, ...],
        policy_artifact_sha256: str,
        species_dictionary_artifact_sha256: str,
        species_dictionary_sha256: str,
    ) -> _CandidateSummary:
        return self._finalize_candidate(
            handle,
            evidence=evidence,
            policy=policy,
            source_contract=source_contract,
            projection=projection,
            policy_artifact_sha256=policy_artifact_sha256,
            species_dictionary_artifact_sha256=(species_dictionary_artifact_sha256),
            species_dictionary_sha256=species_dictionary_sha256,
        )

    def activate(
        self,
        handle: _CandidateHandle,
        summary: _CandidateSummary,
    ) -> _ActivationResult:
        result = self._activate_candidate(handle, summary)
        if result.release_id != handle.release_id:
            # The authoritative activation has already succeeded by reusing an
            # identical active release. Purge the discarded candidate when
            # possible, but cleanup debt must never turn that success into a
            # false failure; the durable flag blocks the next job until retry.
            workload_deadline = self._extend_for_recovery()
            try:
                with suppress(Exception):
                    self._discard_inactive_release(handle.release_id)
            finally:
                self._absolute_deadline = workload_deadline
        return result

    def fail(self, handle: _CandidateHandle, failure_code: str) -> None:
        if failure_code not in _FAILURE_CODES:
            failure_code = "LOADER_EXECUTION_FAILED"
        workload_deadline = self._extend_for_recovery()
        try:
            self._call_fail_candidate(handle, failure_code)
            state = self._read_failure_state(handle)
            if state is None:
                return
            if (
                state.release_status != "failed"
                or state.job_status != "failed"
                or state.failure_code != failure_code
                or state.active_release_id == handle.release_id
                or state.failure_event_count != 1
            ):
                raise LoaderCleanupFailed()
            # A large purge is deliberately outside the authoritative failure
            # transaction. Failure/outbox are already durable; timeout or crash
            # leaves cleanup_pending=true for the next lock owner to resume.
            with suppress(Exception):
                self._discard_failed_candidate(handle)
        except Exception:
            raise LoaderCleanupFailed() from None
        finally:
            self._absolute_deadline = workload_deadline

    def _discard_failed_candidate(self, handle: _CandidateHandle) -> None:
        self._discard_inactive_release(handle.release_id)

    def _discard_inactive_release(self, release_id: UUID) -> None:
        for attempt in range(2):
            try:
                self._set_statement_budget(self._cursor)
                _execute(
                    self._cursor,
                    "SELECT loader_control.discard_inactive_candidate(%s) AS removed_rows",
                    (release_id,),
                )
                removed = _one(self._cursor, ("removed_rows",))["removed_rows"]
                if type(removed) is not int or removed < 0:
                    raise LoaderCleanupFailed()
                return
            except Exception:
                with suppress(Exception):
                    self._connection.rollback()
                if attempt == 0:
                    try:
                        pending = release_id in self._pending_cleanup_release_ids(SOURCE_ID)
                    except Exception:
                        self._replace_connection_and_lock(SOURCE_ID)
                        pending = release_id in self._pending_cleanup_release_ids(SOURCE_ID)
                    if pending:
                        continue
                    return
                raise LoaderCleanupFailed() from None
        raise LoaderCleanupFailed()

    def _call_fail_candidate(self, handle: _CandidateHandle, failure_code: str) -> None:
        try:
            self._set_statement_budget(self._cursor)
            _execute(
                self._cursor,
                "SELECT loader_control.fail_candidate(%s, %s) AS failed_release_id",
                (handle.release_id, failure_code),
            )
            returned = _one(self._cursor, ("failed_release_id",))["failed_release_id"]
            if UUID(str(returned)) != handle.release_id:
                raise LoaderCleanupFailed() from None
        except LoaderCleanupFailed:
            raise
        except Exception:
            try:
                self._connection.rollback()
                self._set_statement_budget(self._cursor)
                _execute(
                    self._cursor,
                    "SELECT loader_control.fail_candidate(%s, %s) AS failed_release_id",
                    (handle.release_id, failure_code),
                )
                returned = _one(self._cursor, ("failed_release_id",))["failed_release_id"]
            except Exception:
                self._replace_connection_and_lock(SOURCE_ID)
                self._set_statement_budget(self._cursor)
                _execute(
                    self._cursor,
                    "SELECT loader_control.fail_candidate(%s, %s) AS failed_release_id",
                    (handle.release_id, failure_code),
                )
                returned = _one(self._cursor, ("failed_release_id",))["failed_release_id"]
            if UUID(str(returned)) != handle.release_id:
                raise LoaderCleanupFailed() from None

    def _read_failure_state(
        self,
        handle: _CandidateHandle,
    ) -> _FailureState | None:
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "SELECT r.release_id, r.job_id, r.status AS release_status, "
            "j.status AS job_status, j.failure_code, r.cleanup_pending, "
            "s.active_release_id, (SELECT count(*) FROM loader_control.notification_outbox AS n "
            "WHERE n.job_id = j.job_id AND n.event_type = 'etl_failed' "
            "AND n.failure_code = j.failure_code) AS failure_event_count "
            "FROM loader_control.release AS r "
            "JOIN loader_control.etl_job AS j ON j.job_id = r.job_id "
            "JOIN loader_control.source_state AS s ON s.source_id = r.source_id "
            "WHERE r.release_id = %s OR j.job_id = %s",
            (handle.release_id, handle.job_id),
        )
        header = (
            "release_id",
            "job_id",
            "release_status",
            "job_status",
            "failure_code",
            "cleanup_pending",
            "active_release_id",
            "failure_event_count",
        )
        if cursor_column_names(self._cursor.description) != header:
            raise LoaderCleanupFailed()
        first = self._cursor.fetchone()
        if first is None:
            return None
        if self._cursor.fetchone() is not None:
            raise LoaderCleanupFailed()
        row = mapping_row(first, header)
        if (
            UUID(str(row["release_id"])) != handle.release_id
            or UUID(str(row["job_id"])) != handle.job_id
        ):
            raise LoaderCleanupFailed()
        active = row["active_release_id"]
        if type(row["cleanup_pending"]) is not bool or type(row["failure_event_count"]) is not int:
            raise LoaderCleanupFailed()
        return _FailureState(
            release_status=str(row["release_status"]),
            job_status=str(row["job_status"]),
            failure_code=str(row["failure_code"]),
            cleanup_pending=row["cleanup_pending"],
            active_release_id=None if active is None else UUID(str(active)),
            failure_event_count=row["failure_event_count"],
        )

    def cancel(self) -> None:
        with suppress(Exception):
            self._connection.cancel_safe(timeout=10.0)

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        if self._control is not None and self._locked_source is not None:
            try:
                _execute(self._control, TARGET_UNLOCK_SQL, (self._locked_source,))
                released = _one(self._control, ("released",))
                if released["released"] is not True:
                    failed = True
            except Exception:
                failed = True
        if self._control is not None:
            try:
                self._control.close()
            except Exception:
                failed = True
        try:
            self._connection.rollback()
        except Exception:
            failed = True
        try:
            self._connection.close()
        except Exception:
            failed = True
        self._closed = True
        if failed:
            raise LoaderCleanupFailed()

    def __enter__(self) -> _PostgreSQLTargetStore:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.close()
        return False

    def _finalize_candidate(
        self,
        handle: _CandidateHandle,
        *,
        evidence: SafeSourceSnapshotEvidence,
        policy: PublicationPolicy,
        source_contract: SourceContract,
        projection: tuple[str, ...],
        policy_artifact_sha256: str,
        species_dictionary_artifact_sha256: str,
        species_dictionary_sha256: str,
    ) -> _CandidateSummary:
        if (
            not _valid_snapshot_handle(handle)
            or not isinstance(evidence, SafeSourceSnapshotEvidence)
            or not isinstance(policy, PublicationPolicy)
            or not isinstance(source_contract, SourceContract)
            or not isinstance(projection, tuple)
            or not isinstance(policy_artifact_sha256, str)
            or not isinstance(species_dictionary_artifact_sha256, str)
            or not isinstance(species_dictionary_sha256, str)
        ):
            raise LoaderCandidateInvalid()
        snapshot_at = self._validate_finalization_inputs(
            evidence=evidence,
            policy=policy,
            source_contract=source_contract,
            projection=projection,
            policy_artifact_sha256=policy_artifact_sha256,
            species_dictionary_artifact_sha256=(species_dictionary_artifact_sha256),
            species_dictionary_sha256=species_dictionary_sha256,
        )
        projection_sha256 = _canonical_json_sha256(
            {"version": PROJECTION_VERSION, "columns": list(projection)}
        )
        approval_sha256 = policy.approval_digest
        sensitivity_sha256 = policy.sensitive_snapshot_sha256
        if not isinstance(approval_sha256, str) or not isinstance(sensitivity_sha256, str):
            raise LoaderCandidateInvalid()
        compatibility_sha256 = _compatibility_sha256(
            source_contract_version=evidence.contract_version,
            source_contract_sha256=evidence.contract_sha256,
            observed_view_definition_sha256=evidence.observed_definition_sha256,
            observed_view_identity_sha256=evidence.observed_identity_sha256,
            projection_sha256=projection_sha256,
            publication_policy_version=policy.version,
            publication_policy_sha256=policy_artifact_sha256,
            policy_approval_sha256=approval_sha256,
            species_dictionary_sha256=evidence.observed_species_dictionary_sha256,
            sensitivity_snapshot_sha256=sensitivity_sha256,
            reconciliation_key_sha256=hashlib.sha256(
                self._config.reconciliation.secret_bytes()
            ).hexdigest(),
        )
        # ``dataset_version`` is the serving-contract compatibility identity.
        # It deliberately stays stable when only source rows/timestamps change;
        # release/source/public digests carry the snapshot-specific identities.
        capabilities = self._capabilities(policy)
        refresh_thresholds: tuple[int | None, ...]
        if handle.mode is LoadMode.REFRESH:
            runtime = self._config.runtime
            refresh_thresholds = (
                runtime.refresh_min_source_rows,
                runtime.refresh_max_source_rows,
                runtime.refresh_max_source_row_drop_bps,
                runtime.refresh_max_source_row_growth_bps,
                runtime.refresh_max_publication_basis_drop_bps,
                runtime.refresh_max_species_drop_bps,
                runtime.refresh_max_cell_drop_bps,
                runtime.refresh_max_species_year_drop_bps,
            )
        else:
            refresh_thresholds = (None,) * 8
        cursor = self._cursor
        commit_sent = False
        try:
            self._begin(cursor)
            self._tx_execute(
                cursor,
                "UPDATE loader_control.etl_job SET status = 'reconciling', "
                "heartbeat_at = transaction_timestamp() "
                "WHERE job_id = %s AND source_id = %s AND load_mode = %s "
                "AND base_release_id IS NOT DISTINCT FROM %s AND status = 'extracting'",
                (
                    handle.job_id,
                    SOURCE_ID,
                    handle.mode.value,
                    handle.base_release_id,
                ),
            )
            self._require_rowcount(cursor, 1)
            self._tx_execute(
                cursor,
                "SELECT loader_control.authorize_candidate_writes(%s) AS release_id",
                (handle.release_id,),
            )
            authorised = _one(cursor, ("release_id",))["release_id"]
            if UUID(str(authorised)) != handle.release_id:
                raise LoaderCandidateInvalid()
            self._normalise_complete_candidate(
                handle,
                policy=policy,
                capabilities=capabilities,
            )
            counts = self._materialise_candidate(
                handle,
                evidence=evidence,
                policy=policy,
                snapshot_at=snapshot_at,
                dataset_version=compatibility_sha256,
                capabilities=capabilities,
            )
            if (
                counts["source_inventory_count"] != evidence.rows_seen
                or counts["delta_row_count"] != evidence.rows_seen
                or counts["source_disposition_count"] != evidence.rows_seen
                or counts["eligible_pre_suppression_count"]
                != evidence.records_eligible_before_suppression
                or counts["transform_withheld_count"]
                != evidence.rows_seen - evidence.records_eligible_before_suppression
                or counts["published_basis_count"] < 1
                or counts["species_count"] < 1
                or counts["cell_count"] < 1
                or counts["species_year_count"] < 1
            ):
                raise LoaderCandidateInvalid()
            if self._transform_withheld_summary(handle.release_id) != tuple(
                sorted(evidence.withheld_by_reason)
            ):
                raise LoaderCandidateInvalid()

            source_result_sha256 = self._source_result_digest(
                handle.release_id,
                sensitive_record_action=policy.sensitive_record_action,
                sensitivity_buckets=evidence.sensitivity_buckets,
            )
            candidate_sha256 = self._candidate_public_digest(
                handle.release_id,
                policy=policy,
                dataset_version=compatibility_sha256,
                capabilities=capabilities,
            )
            database_sha256 = self._database_public_digest(handle.release_id)
            if candidate_sha256 != database_sha256:
                raise LoaderCandidateInvalid()

            privacy_violations = self._privacy_violation_count(
                handle.release_id,
                capabilities=capabilities,
            )
            if privacy_violations != 0:
                raise LoaderCandidateInvalid()

            self._tx_execute(
                cursor,
                "INSERT INTO loader_control.release_manifest ("
                "release_id, source_snapshot_at, lower_modified_date, "
                "lower_modified_key_token, upper_modified_date, upper_modified_key_token, "
                "source_contract_version, source_contract_sha256, "
                "observed_view_definition_sha256, observed_view_identity_sha256, "
                "projection_version, projection_sha256, publication_policy_version, "
                "publication_policy_sha256, policy_approval_sha256, sensitive_record_action, "
                "refresh_min_source_rows, refresh_max_source_rows, "
                "refresh_max_source_row_drop_bps, refresh_max_source_row_growth_bps, "
                "refresh_max_publication_basis_drop_bps, refresh_max_species_drop_bps, "
                "refresh_max_cell_drop_bps, refresh_max_species_year_drop_bps, "
                "suppression_mode, min_records_per_cell, etl_version, compatibility_sha256, "
                "species_dictionary_artifact_sha256, species_dictionary_sha256, "
                "sensitivity_snapshot_sha256, source_row_count, "
                "source_inventory_count, delta_row_count, eligible_pre_suppression_count, "
                "transform_withheld_count, suppression_withheld_count, "
                "published_basis_count, species_count, cell_count, species_year_count, "
                "public_record_count, source_result_sha256, candidate_sha256, database_sha256"
                ") VALUES ("
                "%s, %s, NULL, NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
                ")",
                (
                    handle.release_id,
                    snapshot_at,
                    evidence.contract_version,
                    evidence.contract_sha256,
                    evidence.observed_definition_sha256,
                    evidence.observed_identity_sha256,
                    PROJECTION_VERSION,
                    projection_sha256,
                    policy.version,
                    policy_artifact_sha256,
                    approval_sha256,
                    policy.sensitive_record_action,
                    refresh_thresholds[0],
                    refresh_thresholds[1],
                    refresh_thresholds[2],
                    refresh_thresholds[3],
                    refresh_thresholds[4],
                    refresh_thresholds[5],
                    refresh_thresholds[6],
                    refresh_thresholds[7],
                    policy.suppression_mode,
                    policy.min_records_per_cell,
                    LOADER_VERSION,
                    compatibility_sha256,
                    species_dictionary_artifact_sha256,
                    evidence.observed_species_dictionary_sha256,
                    sensitivity_sha256,
                    evidence.rows_seen,
                    counts["source_inventory_count"],
                    counts["delta_row_count"],
                    counts["eligible_pre_suppression_count"],
                    counts["transform_withheld_count"],
                    counts["suppression_withheld_count"],
                    counts["published_basis_count"],
                    counts["species_count"],
                    counts["cell_count"],
                    counts["species_year_count"],
                    counts["public_record_count"],
                    source_result_sha256,
                    candidate_sha256,
                    database_sha256,
                ),
            )
            self._require_rowcount(cursor, 1)
            checks = self._reconciliation_rows(
                handle,
                evidence=evidence,
                counts=counts,
                privacy_violations=privacy_violations,
                digests_match=candidate_sha256 == database_sha256,
            )
            self._set_statement_budget(cursor, local=True)
            cursor.executemany(
                "INSERT INTO loader_stage.reconciliation_result "
                "(job_id, check_code, expected_count, actual_count, passed) "
                "VALUES (%s, %s, %s, %s, %s)",
                checks,
            )
            self._tx_execute(
                cursor,
                "UPDATE loader_control.etl_job SET status = 'activating', "
                "source_rows_seen = %s, candidate_rows = %s, rows_withheld = %s, "
                "heartbeat_at = transaction_timestamp() "
                "WHERE job_id = %s AND status = 'reconciling'",
                (
                    evidence.rows_seen,
                    counts["published_basis_count"],
                    counts["transform_withheld_count"] + counts["suppression_withheld_count"],
                    handle.job_id,
                ),
            )
            self._require_rowcount(cursor, 1)
            self._set_statement_budget(cursor, local=True)
            commit_sent = True
            _execute(cursor, TARGET_COMMIT)
            return _CandidateSummary(
                source_rows=evidence.rows_seen,
                published_records=counts["public_record_count"],
                distribution_cells=counts["cell_count"],
                candidate_sha256=candidate_sha256,
            )
        except LoaderError:
            with suppress(Exception):
                _execute(cursor, TARGET_ROLLBACK)
            if commit_sent:
                recovered = self._recover_finalized_summary_ack(handle)
                if recovered is not None:
                    return recovered
            raise
        except Exception:
            with suppress(Exception):
                _execute(cursor, TARGET_ROLLBACK)
            if commit_sent:
                recovered = self._recover_finalized_summary_ack(handle)
                if recovered is not None:
                    return recovered
            raise LoaderCandidateInvalid() from None

    @staticmethod
    def _validate_finalization_inputs(
        *,
        evidence: SafeSourceSnapshotEvidence,
        policy: PublicationPolicy,
        source_contract: SourceContract,
        projection: tuple[str, ...],
        policy_artifact_sha256: str,
        species_dictionary_artifact_sha256: str,
        species_dictionary_sha256: str,
    ) -> datetime:
        withheld = evidence.withheld_by_reason
        sensitivity_buckets = evidence.sensitivity_buckets
        if not isinstance(withheld, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or type(item[1]) is not int
            or item[1] < 1
            for item in withheld
        ):
            raise LoaderCandidateInvalid()
        if (
            not isinstance(sensitivity_buckets, tuple)
            or len(sensitivity_buckets) > 4
            or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or item[0] not in {"no", "yes", "null-or-blank", "other"}
                or type(item[1]) is not int
                or item[1] < 1
                for item in sensitivity_buckets
            )
            or len({bucket for bucket, _ in sensitivity_buckets}) != len(sensitivity_buckets)
            or tuple(sorted(sensitivity_buckets)) != sensitivity_buckets
            or sum(count for _, count in sensitivity_buckets) != evidence.rows_seen
        ):
            raise LoaderCandidateInvalid()
        try:
            policy.validate()
            policy.assert_approved()
            source_contract.require_mode(SourceLoadMode.INITIAL)
            source_contract.assert_release_ready()
        except (InvalidPolicy, PolicyNotApproved, IncrementalLoadBlocked, SourceContractError):
            raise LoaderCandidateInvalid() from None
        try:
            snapshot_at = datetime.fromisoformat(evidence.captured_at_utc.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise LoaderCandidateInvalid() from None
        if snapshot_at.tzinfo is None or snapshot_at.utcoffset() != timezone.utc.utcoffset(
            snapshot_at
        ):
            raise LoaderCandidateInvalid()
        if (
            evidence.contract_version != source_contract.version
            or evidence.contract_sha256 != source_contract.digest()
            or evidence.policy_version != policy.version
            or evidence.policy_approval_digest != policy.approval_digest
            or evidence.sensitive_record_action != policy.sensitive_record_action
            or evidence.result_columns != projection
            or not projection
            or len(set(projection)) != len(projection)
            or evidence.rows_seen < 1
            or evidence.records_eligible_before_suppression < 0
            or evidence.records_eligible_before_suppression > evidence.rows_seen
            or sum(count for _, count in withheld)
            != evidence.rows_seen - evidence.records_eligible_before_suppression
            or len(withheld) > 128
            or len({reason for reason, _ in withheld}) != len(withheld)
        ):
            raise LoaderCandidateInvalid()
        digests = (
            evidence.contract_sha256,
            evidence.observed_definition_sha256,
            evidence.observed_identity_sha256,
            evidence.observed_species_dictionary_sha256,
            policy_artifact_sha256,
            policy.approval_digest,
            policy.species_dictionary_sha256,
            species_dictionary_artifact_sha256,
            species_dictionary_sha256,
            policy.sensitive_snapshot_sha256,
        )
        if any(not _is_sha256(value) for value in digests):
            raise LoaderCandidateInvalid()
        if not (
            hmac.compare_digest(
                evidence.observed_species_dictionary_sha256,
                species_dictionary_sha256,
            )
            and hmac.compare_digest(
                evidence.observed_species_dictionary_sha256,
                policy.species_dictionary_sha256,
            )
        ):
            raise LoaderCandidateInvalid()
        return snapshot_at.astimezone(timezone.utc)

    @staticmethod
    def _capabilities(policy: PublicationPolicy) -> dict[str, bool]:
        verification = policy.verification_publication_mode == "publish"
        individual = policy.publish_individual_records
        return {
            "verification": verification,
            "individual": individual,
            "record_verification": (
                individual and verification and policy.publish_record_verification
            ),
            "place": individual and policy.publish_place_names,
            "abundance": individual and policy.publish_abundance,
            "record_type": individual and policy.publish_record_type,
        }

    def _normalise_complete_candidate(
        self,
        handle: _CandidateHandle,
        *,
        policy: PublicationPolicy,
        capabilities: Mapping[str, bool],
    ) -> None:
        cursor = self._cursor
        self._tx_execute(
            cursor,
            "UPDATE loader_stage.disposition_delta SET "
            "place = CASE WHEN %s THEN place ELSE NULL END, "
            "abundance = CASE WHEN %s THEN abundance ELSE NULL END, "
            "record_type = CASE WHEN %s THEN record_type ELSE NULL END, "
            "verified_status = CASE WHEN %s THEN verified_status ELSE NULL END "
            "WHERE job_id = %s AND action = 'upsert'",
            (
                capabilities["place"],
                capabilities["abundance"],
                capabilities["record_type"],
                capabilities["verification"],
                handle.job_id,
            ),
        )
        self._tx_execute(
            cursor,
            "WITH sparse AS ("
            "SELECT species_id, record_year, cell_id, cell_precision_metres "
            "FROM loader_stage.disposition_delta "
            "WHERE job_id = %s AND action = 'upsert' "
            "GROUP BY species_id, record_year, cell_id, cell_precision_metres "
            "HAVING count(*) < %s"
            ") UPDATE loader_stage.disposition_delta AS d SET "
            "action = 'suppress', withheld_reason = 'suppressed-sparse-cell', "
            "scientific_name = NULL, common_name = NULL, record_grid_ref = NULL, "
            "record_precision_metres = NULL, public_record_id = NULL, place = NULL, "
            "abundance = NULL, record_type = NULL, verified_status = NULL, source_label = NULL "
            "FROM sparse AS s WHERE d.job_id = %s AND d.action = 'upsert' "
            "AND d.species_id = s.species_id AND d.record_year = s.record_year "
            "AND d.cell_id = s.cell_id AND d.cell_precision_metres = s.cell_precision_metres",
            (handle.job_id, policy.min_records_per_cell, handle.job_id),
        )
        self._tx_execute(
            cursor,
            "INSERT INTO loader_control.source_disposition ("
            "release_id, source_key_token, input_fingerprint, disposition, withheld_reason, "
            "species_id, scientific_name, common_name, record_grid_ref, "
            "record_precision_metres, cell_id, cell_precision_metres, min_easting, "
            "min_northing, max_easting, max_northing, record_year, public_record_id, "
            "place, abundance, record_type, verified_status, source_label"
            ") SELECT %s, source_key_token, input_fingerprint, "
            "CASE action WHEN 'upsert' THEN 'eligible' WHEN 'suppress' THEN 'suppressed' "
            "WHEN 'withhold' THEN 'withheld' ELSE NULL END, withheld_reason, species_id, "
            "scientific_name, common_name, record_grid_ref, record_precision_metres, cell_id, "
            "cell_precision_metres, min_easting, min_northing, max_easting, max_northing, "
            "record_year, public_record_id, place, abundance, record_type, verified_status, "
            "source_label FROM loader_stage.disposition_delta "
            "WHERE job_id = %s AND action IN ('upsert', 'suppress', 'withhold')",
            (handle.release_id, handle.job_id),
        )
        self._tx_execute(
            cursor,
            "INSERT INTO loader_control.withheld_summary (release_id, reason_code, row_count) "
            "SELECT %s, withheld_reason, count(*) FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition IN ('withheld', 'suppressed') "
            "GROUP BY withheld_reason",
            (handle.release_id, handle.release_id),
        )

    def _materialise_candidate(
        self,
        handle: _CandidateHandle,
        *,
        evidence: SafeSourceSnapshotEvidence,
        policy: PublicationPolicy,
        snapshot_at: datetime,
        dataset_version: str,
        capabilities: Mapping[str, bool],
    ) -> dict[str, int]:
        cursor = self._cursor
        self._tx_execute(
            cursor,
            "SELECT EXISTS ("
            "SELECT 1 FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition = 'eligible' GROUP BY species_id "
            "HAVING count(DISTINCT scientific_name) <> 1 "
            "OR count(DISTINCT common_name) > 1 "
            "OR (count(common_name) > 0 AND count(common_name) < count(*))"
            ") AS conflicts",
            (handle.release_id,),
        )
        if _one(cursor, ("conflicts",))["conflicts"] is not False:
            raise LoaderCandidateInvalid()
        self._tx_execute(
            cursor,
            "INSERT INTO publication.public_release ("
            "release_id, source_data_as_of, publication_policy_version, dataset_version, "
            "sensitive_record_action, suppression_mode, min_records_per_cell, verification_available, "
            "individual_records_available, record_verification_available, place_available, "
            "abundance_available, record_type_available, public_source_label"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                handle.release_id,
                snapshot_at,
                policy.version,
                dataset_version,
                policy.sensitive_record_action,
                policy.suppression_mode,
                policy.min_records_per_cell,
                capabilities["verification"],
                capabilities["individual"],
                capabilities["record_verification"],
                capabilities["place"],
                capabilities["abundance"],
                capabilities["record_type"],
                policy.public_source_label,
            ),
        )
        self._require_rowcount(cursor, 1)
        self._tx_execute(
            cursor,
            "INSERT INTO publication.public_species ("
            "release_id, species_id, scientific_name, common_name, taxon_group, "
            "total_records, first_year, last_year"
            ") SELECT %s, species_id, min(scientific_name), min(common_name), NULL, count(*), "
            "min(record_year), max(record_year) FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition = 'eligible' GROUP BY species_id",
            (handle.release_id, handle.release_id),
        )
        self._tx_execute(
            cursor,
            "INSERT INTO publication.public_distribution_cell ("
            "release_id, species_id, record_year, cell_id, precision_metres, record_count, "
            "verified_count, geom"
            ") SELECT %s, species_id, record_year, cell_id, cell_precision_metres, count(*), "
            "CASE WHEN %s THEN count(*) FILTER (WHERE verified_status = 'accepted') "
            "ELSE NULL END, loader_control.bng_cell_polygon(cell_id, cell_precision_metres) "
            "FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition = 'eligible' "
            "GROUP BY species_id, record_year, cell_id, cell_precision_metres",
            (handle.release_id, capabilities["verification"], handle.release_id),
        )
        self._tx_execute(
            cursor,
            "INSERT INTO publication.public_species_year ("
            "release_id, species_id, record_year, record_count, verified_count"
            ") SELECT %s, species_id, record_year, count(*), "
            "CASE WHEN %s THEN count(*) FILTER (WHERE verified_status = 'accepted') "
            "ELSE NULL END FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition = 'eligible' "
            "GROUP BY species_id, record_year",
            (handle.release_id, capabilities["verification"], handle.release_id),
        )
        if capabilities["individual"]:
            self._tx_execute(
                cursor,
                "INSERT INTO publication.public_record ("
                "release_id, public_record_id, species_id, scientific_name, common_name, "
                "grid_ref, precision_metres, place, record_year, abundance, record_type, "
                "verified_status, source_label"
                ") SELECT %s, public_record_id, species_id, scientific_name, common_name, "
                "record_grid_ref, record_precision_metres, place, record_year, abundance, "
                "record_type, CASE WHEN %s THEN verified_status ELSE NULL END, source_label "
                "FROM loader_control.source_disposition "
                "WHERE release_id = %s AND disposition = 'eligible'",
                (
                    handle.release_id,
                    capabilities["record_verification"],
                    handle.release_id,
                ),
            )
        self._tx_execute(
            cursor,
            "SELECT "
            "(SELECT count(*) FROM loader_stage.source_inventory WHERE job_id = %s) "
            "AS source_inventory_count, "
            "(SELECT count(*) FROM loader_stage.disposition_delta WHERE job_id = %s) "
            "AS delta_row_count, "
            "(SELECT count(*) FROM loader_control.source_disposition WHERE release_id = %s) "
            "AS source_disposition_count, "
            "(SELECT count(*) FROM loader_stage.disposition_delta WHERE job_id = %s "
            "AND action IN ('upsert', 'suppress')) AS eligible_pre_suppression_count, "
            "(SELECT count(*) FROM loader_control.source_disposition WHERE release_id = %s "
            "AND disposition = 'withheld') AS transform_withheld_count, "
            "(SELECT count(*) FROM loader_control.source_disposition WHERE release_id = %s "
            "AND disposition = 'suppressed') AS suppression_withheld_count, "
            "(SELECT count(*) FROM loader_control.source_disposition WHERE release_id = %s "
            "AND disposition = 'eligible') AS published_basis_count, "
            "(SELECT count(*) FROM publication.public_species WHERE release_id = %s) "
            "AS species_count, "
            "(SELECT count(*) FROM publication.public_distribution_cell WHERE release_id = %s) "
            "AS cell_count, "
            "(SELECT count(*) FROM publication.public_species_year WHERE release_id = %s) "
            "AS species_year_count, "
            "(SELECT count(*) FROM publication.public_record WHERE release_id = %s) "
            "AS public_record_count, "
            "(SELECT COALESCE(sum(record_count), 0) FROM publication.public_distribution_cell "
            "WHERE release_id = %s) AS cell_total, "
            "(SELECT COALESCE(sum(record_count), 0) FROM publication.public_species_year "
            "WHERE release_id = %s) AS species_year_total, "
            "(SELECT COALESCE(sum(total_records), 0) FROM publication.public_species "
            "WHERE release_id = %s) AS species_total",
            (
                handle.job_id,
                handle.job_id,
                handle.release_id,
                handle.job_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
                handle.release_id,
            ),
        )
        header = (
            "source_inventory_count",
            "delta_row_count",
            "source_disposition_count",
            "eligible_pre_suppression_count",
            "transform_withheld_count",
            "suppression_withheld_count",
            "published_basis_count",
            "species_count",
            "cell_count",
            "species_year_count",
            "public_record_count",
            "cell_total",
            "species_year_total",
            "species_total",
        )
        row = _one(cursor, header)
        try:
            counts = {key: int(value) for key, value in row.items()}
        except (TypeError, ValueError):
            raise LoaderCandidateInvalid() from None
        if any(value < 0 for value in counts.values()):
            raise LoaderCandidateInvalid()
        return counts

    def _transform_withheld_summary(self, release_id: UUID) -> tuple[tuple[str, int], ...]:
        self._tx_execute(
            self._cursor,
            "SELECT reason_code, row_count FROM loader_control.withheld_summary "
            "WHERE release_id = %s AND reason_code <> 'suppressed-sparse-cell' "
            'ORDER BY reason_code COLLATE "C" ASC NULLS FIRST',
            (release_id,),
        )
        header = ("reason_code", "row_count")
        if cursor_column_names(self._cursor.description) != header:
            raise LoaderTargetProtocolError()
        result: list[tuple[str, int]] = []
        while True:
            row = self._cursor.fetchone()
            if row is None:
                break
            mapped = mapping_row(row, header)
            reason = mapped["reason_code"]
            count = mapped["row_count"]
            if (
                not isinstance(reason, str)
                or type(count) is not int
                or count < 1
                or len(result) >= 128
            ):
                raise LoaderCandidateInvalid()
            result.append((reason, count))
        return tuple(result)

    def _digest_from_queries(
        self,
        tables: Sequence[DigestTable],
        queries: Sequence[tuple[str, Sequence[object]]],
    ) -> str:
        if len(tables) != len(queries):
            raise LoaderCandidateInvalid()
        digest = ReleaseDigest(tables)
        for table, (query, params) in zip(tables, queries, strict=True):
            self._set_statement_budget(self._cursor, local=True)
            stream = self._connection.cursor(name=f"brerc_{table.name}_{uuid4().hex}")
            try:
                _execute(stream, query, params)
                header = cursor_column_names(stream.description)
                if header != table.columns:
                    raise LoaderCandidateInvalid()
                digest.begin(table.name, header)
                while True:
                    self._set_statement_budget(self._cursor, local=True)
                    batch = stream.fetchmany(self._config.runtime.batch_size)
                    if not batch:
                        break
                    canonical_rows: list[tuple[object, ...]] = []
                    for raw_row in batch:
                        row = mapping_row(raw_row, header)
                        if tuple(row) != header:
                            raise LoaderCandidateInvalid()
                        canonical_rows.append(tuple(row[column] for column in header))
                    digest.rows(canonical_rows)
                digest.end()
            except LoaderError:
                raise
            except Exception:
                raise LoaderCandidateInvalid() from None
            finally:
                with suppress(Exception):
                    stream.close()
        return digest.hexdigest()

    def _source_result_digest(
        self,
        release_id: UUID,
        *,
        sensitive_record_action: str,
        sensitivity_buckets: tuple[tuple[str, int], ...],
    ) -> str:
        disposition_sql = (
            "SELECT source_key_token, input_fingerprint, disposition, withheld_reason, "
            "species_id, scientific_name, common_name, record_grid_ref, "
            "record_precision_metres, cell_id, cell_precision_metres, min_easting, "
            "min_northing, max_easting, max_northing, record_year, public_record_id, place, "
            "abundance, record_type, verified_status, source_label "
            "FROM loader_control.source_disposition WHERE release_id = %s "
            "ORDER BY source_key_token ASC"
        )
        withheld_sql = (
            "SELECT reason_code, row_count FROM loader_control.withheld_summary "
            'WHERE release_id = %s ORDER BY reason_code COLLATE "C" ASC NULLS FIRST'
        )
        ledger_sha256 = self._digest_from_queries(
            SOURCE_RESULT_DIGEST_TABLES,
            ((disposition_sql, (release_id,)), (withheld_sql, (release_id,))),
        )
        return _canonical_json_sha256(
            {
                "ledgerSha256": ledger_sha256,
                "profile": SOURCE_RESULT_EVIDENCE_PROFILE,
                "sensitiveRecordAction": sensitive_record_action,
                "sensitivityBuckets": [list(bucket) for bucket in sensitivity_buckets],
            }
        )

    @staticmethod
    def _expected_public_queries(
        release_id: UUID,
        *,
        policy: PublicationPolicy,
        dataset_version: str,
        capabilities: Mapping[str, bool],
    ) -> tuple[tuple[str, Sequence[object]], ...]:
        release_sql = (
            "SELECT %s::text AS publication_policy_version, %s::text AS dataset_version, "
            "%s::text AS sensitive_record_action, %s::text AS suppression_mode, "
            "%s::integer AS min_records_per_cell, "
            "%s::boolean AS verification_available, %s::boolean AS individual_records_available, "
            "%s::boolean AS record_verification_available, %s::boolean AS place_available, "
            "%s::boolean AS abundance_available, %s::boolean AS record_type_available, "
            "%s::text AS public_source_label"
        )
        release_params: Sequence[object] = (
            policy.version,
            dataset_version,
            policy.sensitive_record_action,
            policy.suppression_mode,
            policy.min_records_per_cell,
            capabilities["verification"],
            capabilities["individual"],
            capabilities["record_verification"],
            capabilities["place"],
            capabilities["abundance"],
            capabilities["record_type"],
            policy.public_source_label,
        )
        species_sql = (
            "SELECT species_id, min(scientific_name) AS scientific_name, "
            "min(common_name) AS common_name, NULL::text AS taxon_group, "
            "count(*) AS total_records, min(record_year) AS first_year, "
            "max(record_year) AS last_year FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition = 'eligible' GROUP BY species_id "
            'ORDER BY species_id COLLATE "C" ASC NULLS FIRST'
        )
        cell_sql = (
            "SELECT species_id, record_year, cell_id, cell_precision_metres AS precision_metres, "
            "count(*) AS record_count, CASE WHEN %s THEN count(*) FILTER "
            "(WHERE verified_status = 'accepted') ELSE NULL END AS verified_count, "
            "min(min_easting) AS min_easting, min(min_northing) AS min_northing, "
            "max(max_easting) AS max_easting, max(max_northing) AS max_northing "
            "FROM loader_control.source_disposition WHERE release_id = %s "
            "AND disposition = 'eligible' "
            "GROUP BY species_id, record_year, cell_id, cell_precision_metres "
            'ORDER BY species_id COLLATE "C" ASC NULLS FIRST, record_year ASC NULLS FIRST, '
            'cell_id COLLATE "C" ASC NULLS FIRST, cell_precision_metres ASC NULLS FIRST'
        )
        year_sql = (
            "SELECT species_id, record_year, count(*) AS record_count, CASE WHEN %s THEN "
            "count(*) FILTER (WHERE verified_status = 'accepted') ELSE NULL END "
            "AS verified_count FROM loader_control.source_disposition WHERE release_id = %s "
            "AND disposition = 'eligible' GROUP BY species_id, record_year "
            'ORDER BY species_id COLLATE "C" ASC NULLS FIRST, record_year ASC NULLS FIRST'
        )
        record_sql = (
            "SELECT public_record_id, species_id, scientific_name, common_name, "
            "record_grid_ref AS grid_ref, record_precision_metres AS precision_metres, place, "
            "record_year, abundance, record_type, CASE WHEN %s THEN verified_status ELSE NULL END "
            "AS verified_status, source_label FROM loader_control.source_disposition "
            "WHERE release_id = %s AND disposition = 'eligible' AND %s "
            'ORDER BY public_record_id COLLATE "C" ASC NULLS FIRST'
        )
        return (
            (release_sql, release_params),
            (species_sql, (release_id,)),
            (cell_sql, (capabilities["verification"], release_id)),
            (year_sql, (capabilities["verification"], release_id)),
            (
                record_sql,
                (
                    capabilities["record_verification"],
                    release_id,
                    capabilities["individual"],
                ),
            ),
        )

    def _candidate_public_digest(
        self,
        release_id: UUID,
        *,
        policy: PublicationPolicy,
        dataset_version: str,
        capabilities: Mapping[str, bool],
    ) -> str:
        return self._digest_from_queries(
            PUBLIC_RELEASE_DIGEST_TABLES,
            self._expected_public_queries(
                release_id,
                policy=policy,
                dataset_version=dataset_version,
                capabilities=capabilities,
            ),
        )

    def _database_public_digest(self, release_id: UUID) -> str:
        release_sql = (
            "SELECT publication_policy_version, dataset_version, sensitive_record_action, "
            "suppression_mode, min_records_per_cell, verification_available, individual_records_available, "
            "record_verification_available, place_available, abundance_available, "
            "record_type_available, public_source_label FROM publication.public_release "
            "WHERE release_id = %s"
        )
        species_sql = (
            "SELECT species_id, scientific_name, common_name, taxon_group, total_records, "
            "first_year, last_year FROM publication.public_species WHERE release_id = %s "
            'ORDER BY species_id COLLATE "C" ASC NULLS FIRST'
        )
        cell_sql = (
            "SELECT species_id, record_year, cell_id, precision_metres, record_count, "
            "verified_count, public.ST_XMin(public.ST_Envelope(geom))::integer AS min_easting, "
            "public.ST_YMin(public.ST_Envelope(geom))::integer AS min_northing, "
            "public.ST_XMax(public.ST_Envelope(geom))::integer AS max_easting, "
            "public.ST_YMax(public.ST_Envelope(geom))::integer AS max_northing "
            "FROM publication.public_distribution_cell WHERE release_id = %s "
            'ORDER BY species_id COLLATE "C" ASC NULLS FIRST, record_year ASC NULLS FIRST, '
            'cell_id COLLATE "C" ASC NULLS FIRST, precision_metres ASC NULLS FIRST'
        )
        year_sql = (
            "SELECT species_id, record_year, record_count, verified_count "
            "FROM publication.public_species_year WHERE release_id = %s "
            'ORDER BY species_id COLLATE "C" ASC NULLS FIRST, record_year ASC NULLS FIRST'
        )
        record_sql = (
            "SELECT public_record_id, species_id, scientific_name, common_name, grid_ref, "
            "precision_metres, place, record_year, abundance, record_type, verified_status, "
            "source_label FROM publication.public_record WHERE release_id = %s "
            'ORDER BY public_record_id COLLATE "C" ASC NULLS FIRST'
        )
        return self._digest_from_queries(
            PUBLIC_RELEASE_DIGEST_TABLES,
            (
                (release_sql, (release_id,)),
                (species_sql, (release_id,)),
                (cell_sql, (release_id,)),
                (year_sql, (release_id,)),
                (record_sql, (release_id,)),
            ),
        )

    def _privacy_violation_count(
        self,
        release_id: UUID,
        *,
        capabilities: Mapping[str, bool],
    ) -> int:
        self._tx_execute(
            self._cursor,
            "SELECT ("
            "SELECT count(*) FROM loader_control.source_disposition AS d "
            "JOIN publication.public_release AS p ON p.release_id = d.release_id "
            "WHERE d.release_id = %s AND d.disposition = 'eligible' AND ("
            "d.source_label IS DISTINCT FROM p.public_source_label "
            "OR (NOT %s AND d.verified_status IS NOT NULL) "
            "OR (NOT %s AND d.place IS NOT NULL) "
            "OR (NOT %s AND d.abundance IS NOT NULL) "
            "OR (NOT %s AND d.record_type IS NOT NULL))) + ("
            "SELECT count(*) FROM publication.public_species WHERE release_id = %s "
            "AND taxon_group IS NOT NULL) + ("
            "SELECT count(*) FROM publication.public_distribution_cell WHERE release_id = %s "
            "AND NOT %s AND verified_count IS NOT NULL) + ("
            "SELECT count(*) FROM publication.public_species_year WHERE release_id = %s "
            "AND NOT %s AND verified_count IS NOT NULL) + ("
            "SELECT count(*) FROM publication.public_record WHERE release_id = %s AND ("
            "(NOT %s AND verified_status IS NOT NULL) OR (NOT %s AND place IS NOT NULL) "
            "OR (NOT %s AND abundance IS NOT NULL) OR (NOT %s AND record_type IS NOT NULL)"
            ")) AS violations",
            (
                release_id,
                capabilities["verification"],
                capabilities["place"],
                capabilities["abundance"],
                capabilities["record_type"],
                release_id,
                release_id,
                capabilities["verification"],
                release_id,
                capabilities["verification"],
                release_id,
                capabilities["record_verification"],
                capabilities["place"],
                capabilities["abundance"],
                capabilities["record_type"],
            ),
        )
        value = _one(self._cursor, ("violations",))["violations"]
        if type(value) is not int or value < 0:
            raise LoaderCandidateInvalid()
        return value

    @staticmethod
    def _reconciliation_rows(
        handle: _CandidateHandle,
        *,
        evidence: SafeSourceSnapshotEvidence,
        counts: Mapping[str, int],
        privacy_violations: int,
        digests_match: bool,
    ) -> tuple[tuple[object, ...], ...]:
        threshold_ok = int(
            counts["published_basis_count"] >= 1
            and counts["species_count"] >= 1
            and counts["cell_count"] >= 1
            and counts["species_year_count"] >= 1
        )
        pairs = {
            "SOURCE_INVENTORY": (evidence.rows_seen, counts["source_inventory_count"]),
            "SOURCE_DISPOSITIONS": (
                counts["source_inventory_count"],
                counts["source_disposition_count"],
            ),
            "PUBLIC_CELL_TOTAL": (counts["published_basis_count"], counts["cell_total"]),
            "PUBLIC_SPECIES_YEAR_TOTAL": (
                counts["published_basis_count"],
                counts["species_year_total"],
            ),
            "PUBLIC_SPECIES_TOTAL": (
                counts["published_basis_count"],
                counts["species_total"],
            ),
            "PRIVACY_ALLOWLIST": (0, privacy_violations),
            "DATABASE_DIGEST": (1, int(digests_match)),
            "ACTIVATION_THRESHOLDS": (1, threshold_ok),
        }
        if tuple(pairs) != _RECONCILIATION_CODES:
            raise LoaderCandidateInvalid()
        return tuple(
            (handle.job_id, code, expected, actual, expected == actual)
            for code, (expected, actual) in pairs.items()
        )

    def _recover_finalized_summary_ack(
        self,
        handle: _CandidateHandle,
    ) -> _CandidateSummary | None:
        workload_deadline = self._extend_for_recovery()
        try:
            try:
                return self._read_finalized_summary(handle)
            except Exception:
                self._replace_connection_and_lock(SOURCE_ID)
                return self._read_finalized_summary(handle)
        except Exception:
            return None
        finally:
            self._absolute_deadline = workload_deadline

    def _read_finalized_summary(self, handle: _CandidateHandle) -> _CandidateSummary | None:
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "SELECT m.source_row_count, m.public_record_count, m.cell_count, "
            "m.candidate_sha256, j.status AS job_status, r.status AS release_status, "
            "j.load_mode AS job_load_mode, r.load_mode AS release_load_mode, "
            "j.base_release_id AS job_base_release_id, "
            "r.base_release_id AS release_base_release_id "
            "FROM loader_control.release AS r "
            "JOIN loader_control.etl_job AS j ON j.job_id = r.job_id "
            "JOIN loader_control.release_manifest AS m ON m.release_id = r.release_id "
            "WHERE r.release_id = %s AND r.job_id = %s",
            (handle.release_id, handle.job_id),
        )
        header = (
            "source_row_count",
            "public_record_count",
            "cell_count",
            "candidate_sha256",
            "job_status",
            "release_status",
            "job_load_mode",
            "release_load_mode",
            "job_base_release_id",
            "release_base_release_id",
        )
        if cursor_column_names(self._cursor.description) != header:
            raise LoaderTargetProtocolError()
        first = self._cursor.fetchone()
        if first is None:
            return None
        if self._cursor.fetchone() is not None:
            raise LoaderCandidateInvalid()
        row = mapping_row(first, header)
        try:
            raw_job_base = row["job_base_release_id"]
            raw_release_base = row["release_base_release_id"]
            job_base = None if raw_job_base is None else UUID(str(raw_job_base))
            release_base = None if raw_release_base is None else UUID(str(raw_release_base))
        except (TypeError, ValueError):
            raise LoaderCandidateInvalid() from None
        if (
            row["job_status"] != "activating"
            or row["release_status"] not in ("candidate", "validated")
            or row["job_load_mode"] != handle.mode.value
            or row["release_load_mode"] != handle.mode.value
            or job_base != handle.base_release_id
            or release_base != handle.base_release_id
        ):
            raise LoaderCandidateInvalid()
        try:
            return _CandidateSummary(
                source_rows=int(row["source_row_count"]),
                published_records=int(row["public_record_count"]),
                distribution_cells=int(row["cell_count"]),
                candidate_sha256=str(row["candidate_sha256"]),
            )
        except (TypeError, ValueError):
            raise LoaderCandidateInvalid() from None

    def _activate_candidate(
        self,
        handle: _CandidateHandle,
        summary: _CandidateSummary,
    ) -> _ActivationResult:
        if (
            not _valid_snapshot_handle(handle)
            or summary.source_rows < 1
            or summary.distribution_cells < 1
            or len(summary.candidate_sha256) != 64
            or any(character not in "0123456789abcdef" for character in summary.candidate_sha256)
        ):
            raise LoaderCandidateInvalid()
        activation_sent = False
        returned_release: UUID | None = None
        original_deadline = self._absolute_deadline
        try:
            self._set_statement_budget(self._cursor)
            activation_sent = True
            _execute(
                self._cursor,
                "SELECT loader_control.activate_release_candidate(%s) AS release_id",
                (handle.release_id,),
            )
            raw_release = _one(self._cursor, ("release_id",))["release_id"]
            returned_release = UUID(str(raw_release))
        except Exception:
            with suppress(Exception):
                self._connection.rollback()

        if activation_sent:
            authoritative = self._recover_activation_ack(
                handle,
                summary,
                returned_release=returned_release,
            )
            if authoritative is not None:
                return authoritative

        if time.monotonic() >= original_deadline:
            raise LoaderExecutionFailed()
        self._absolute_deadline = original_deadline
        try:
            self._set_statement_budget(self._cursor)
            _execute(
                self._cursor,
                "SELECT loader_control.activate_release_candidate(%s) AS release_id",
                (handle.release_id,),
            )
            raw_release = _one(self._cursor, ("release_id",))["release_id"]
            returned_release = UUID(str(raw_release))
        except Exception:
            with suppress(Exception):
                self._connection.rollback()
            authoritative = self._recover_activation_ack(
                handle,
                summary,
                returned_release=None,
            )
            if authoritative is not None:
                return authoritative
            raise LoaderExecutionFailed() from None
        authoritative = self._recover_activation_ack(
            handle,
            summary,
            returned_release=returned_release,
        )
        if authoritative is None:
            raise LoaderCandidateInvalid()
        return authoritative

    def _recover_activation_ack(
        self,
        handle: _CandidateHandle,
        summary: _CandidateSummary,
        *,
        returned_release: UUID | None,
    ) -> _ActivationResult | None:
        workload_deadline = self._extend_for_recovery()
        try:
            try:
                return self._read_activation_result(
                    handle,
                    summary,
                    returned_release=returned_release,
                )
            except Exception:
                self._replace_connection_and_lock(SOURCE_ID)
                return self._read_activation_result(
                    handle,
                    summary,
                    returned_release=returned_release,
                )
        except Exception:
            return None
        finally:
            self._absolute_deadline = workload_deadline

    def _read_activation_result(
        self,
        handle: _CandidateHandle,
        summary: _CandidateSummary,
        *,
        returned_release: UUID | None,
    ) -> _ActivationResult | None:
        self._set_statement_budget(self._cursor)
        _execute(
            self._cursor,
            "WITH RECURSIVE active_lineage (release_id, base_release_id, source_id) AS ("
            "SELECT ar.release_id, ar.base_release_id, ar.source_id "
            "FROM loader_control.release AS ar "
            "JOIN loader_control.source_state AS ast "
            "ON ast.active_release_id = ar.release_id AND ast.source_id = ar.source_id "
            "WHERE ast.source_id = %s UNION "
            "SELECT parent.release_id, parent.base_release_id, parent.source_id "
            "FROM loader_control.release AS parent "
            "JOIN active_lineage AS child ON child.base_release_id = parent.release_id "
            "AND child.source_id = parent.source_id) "
            "SELECT j.status AS job_status, j.result_release_id, j.reused_active_release, "
            "s.active_release_id, r.status AS result_release_status, m.source_row_count, "
            "m.public_record_count, m.cell_count, m.candidate_sha256, "
            "(r.status = 'active' AND r.release_id = s.active_release_id "
            "AND a.status = 'active' AND a.activated_at IS NOT NULL) AS result_is_current, "
            "(r.status = 'retired' AND r.release_id <> s.active_release_id "
            "AND r.retired_at IS NOT NULL AND a.status = 'active' "
            "AND a.activated_at IS NOT NULL AND a.activated_at >= r.retired_at "
            "AND EXISTS (SELECT 1 FROM active_lineage AS al "
            "WHERE al.release_id = r.release_id)) AS result_was_superseded, "
            "j.load_mode AS job_load_mode, j.base_release_id AS job_base_release_id, "
            "c.release_id AS candidate_release_id, c.load_mode AS candidate_load_mode, "
            "c.base_release_id AS candidate_base_release_id, "
            "c.status AS candidate_release_status, c.cleanup_pending AS candidate_cleanup_pending, "
            "CASE WHEN c.status = 'discarded' AND NOT c.cleanup_pending THEN NOT ("
            "EXISTS (SELECT 1 FROM loader_control.source_disposition AS sd "
            "WHERE sd.release_id = c.release_id) OR "
            "EXISTS (SELECT 1 FROM publication.public_release AS pr "
            "WHERE pr.release_id = c.release_id) OR "
            "EXISTS (SELECT 1 FROM publication.public_species AS ps "
            "WHERE ps.release_id = c.release_id) OR "
            "EXISTS (SELECT 1 FROM publication.public_distribution_cell AS pc "
            "WHERE pc.release_id = c.release_id) OR "
            "EXISTS (SELECT 1 FROM publication.public_species_year AS py "
            "WHERE py.release_id = c.release_id) OR "
            "EXISTS (SELECT 1 FROM publication.public_record AS po "
            "WHERE po.release_id = c.release_id) OR "
            "EXISTS (SELECT 1 FROM loader_stage.source_inventory AS si "
            "WHERE si.job_id = j.job_id) OR "
            "EXISTS (SELECT 1 FROM loader_stage.disposition_delta AS dd "
            "WHERE dd.job_id = j.job_id) OR "
            "EXISTS (SELECT 1 FROM loader_stage.reconciliation_result AS rr "
            "WHERE rr.job_id = j.job_id)) ELSE NULL END AS candidate_cleanup_complete "
            "FROM loader_control.etl_job AS j "
            "JOIN loader_control.source_state AS s ON s.source_id = j.source_id "
            "JOIN loader_control.release AS c ON c.job_id = j.job_id "
            "AND c.source_id = j.source_id "
            "JOIN loader_control.release AS a ON a.release_id = s.active_release_id "
            "AND a.source_id = j.source_id "
            "LEFT JOIN loader_control.release AS r ON r.release_id = j.result_release_id "
            "AND r.source_id = j.source_id "
            "LEFT JOIN loader_control.release_manifest AS m ON m.release_id = j.result_release_id "
            "WHERE j.job_id = %s AND j.source_id = %s",
            (SOURCE_ID, handle.job_id, SOURCE_ID),
        )
        header = (
            "job_status",
            "result_release_id",
            "reused_active_release",
            "active_release_id",
            "result_release_status",
            "source_row_count",
            "public_record_count",
            "cell_count",
            "candidate_sha256",
            "result_is_current",
            "result_was_superseded",
            "job_load_mode",
            "job_base_release_id",
            "candidate_release_id",
            "candidate_load_mode",
            "candidate_base_release_id",
            "candidate_release_status",
            "candidate_cleanup_pending",
            "candidate_cleanup_complete",
        )
        if cursor_column_names(self._cursor.description) != header:
            raise LoaderTargetProtocolError()
        first = self._cursor.fetchone()
        if first is None or self._cursor.fetchone() is not None:
            raise LoaderCandidateInvalid()
        row = mapping_row(first, header)
        if row["job_status"] == "activating" and row["result_release_id"] is None:
            return None
        if row["job_status"] != "succeeded" or row["result_release_id"] is None:
            raise LoaderCandidateInvalid()
        try:
            result_release_id = UUID(str(row["result_release_id"]))
            active_release_id = UUID(str(row["active_release_id"]))
            source_rows = int(row["source_row_count"])
            public_records = int(row["public_record_count"])
            distribution_cells = int(row["cell_count"])
            candidate_release_id = UUID(str(row["candidate_release_id"]))
            raw_job_base = row["job_base_release_id"]
            raw_candidate_base = row["candidate_base_release_id"]
            job_base = None if raw_job_base is None else UUID(str(raw_job_base))
            candidate_base = None if raw_candidate_base is None else UUID(str(raw_candidate_base))
        except (TypeError, ValueError):
            raise LoaderCandidateInvalid() from None
        reused = row["reused_active_release"]
        cleanup_pending = row["candidate_cleanup_pending"]
        cleanup_complete = row["candidate_cleanup_complete"]
        result_is_current = row["result_is_current"]
        result_was_superseded = row["result_was_superseded"]
        result_lifecycle_valid = (result_is_current is True) != (result_was_superseded is True)
        reused_shape_valid = (
            reused is True
            and result_release_id != handle.release_id
            and row["candidate_release_status"] == "discarded"
            and (
                (cleanup_pending is True and cleanup_complete is None)
                or (cleanup_pending is False and cleanup_complete is True)
            )
        )
        activated_shape_valid = (
            reused is False
            and result_release_id == handle.release_id
            and row["candidate_release_status"] == row["result_release_status"]
            and row["candidate_release_status"] in ("active", "retired")
            and cleanup_pending is False
            and cleanup_complete is None
        )
        if (
            (returned_release is not None and returned_release != result_release_id)
            or source_rows != summary.source_rows
            or public_records != summary.published_records
            or distribution_cells != summary.distribution_cells
            or row["candidate_sha256"] != summary.candidate_sha256
            or type(reused) is not bool
            or type(cleanup_pending) is not bool
            or (cleanup_complete is not None and type(cleanup_complete) is not bool)
            or type(result_is_current) is not bool
            or type(result_was_superseded) is not bool
            or not result_lifecycle_valid
            or (result_is_current and result_release_id != active_release_id)
            or (result_was_superseded and result_release_id == active_release_id)
            or candidate_release_id != handle.release_id
            or row["job_load_mode"] != handle.mode.value
            or row["candidate_load_mode"] != handle.mode.value
            or job_base != handle.base_release_id
            or candidate_base != handle.base_release_id
            or not (reused_shape_valid or activated_shape_valid)
        ):
            raise LoaderCandidateInvalid()
        return _ActivationResult(
            run_id=handle.job_id,
            release_id=result_release_id,
            source_rows=source_rows,
            published_records=public_records,
            distribution_cells=distribution_cells,
            candidate_sha256=summary.candidate_sha256,
            reused_active_release=reused,
        )

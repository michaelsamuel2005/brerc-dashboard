"""Trusted, read-only PostgreSQL extraction for BRERC's reviewed source view.

This module owns the trust evidence.  Callers provide an approved contract and
policy, never database rows, cursor headers, view SQL, or checksums.  Catalogue
evidence and the projected rows are obtained on one connection in one explicit
``REPEATABLE READ READ ONLY`` transaction, and the connection is always rolled
back rather than committed.

Psycopg is imported only by the private connection factory. Unit tests patch
that private edge around the small protocols from :mod:`brerc_source.models`;
the public constructor has no evidence-source injection hook, and importing the
ETL safety boundary therefore remains standard-library-only.
"""

from __future__ import annotations

import importlib
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from types import TracebackType

from etl.pipeline import ColumnMap, ValidatedSourceRun, run_pipeline_for_source
from etl.policy import InvalidPolicy, PolicyNotApproved, PublicationPolicy
from etl.source_contract import (
    LoadMode,
    SourceColumn,
    SourceContract,
    SourceContractError,
    SourceMetadata,
)
from etl.species import SpeciesDictionary
from etl.streaming import (
    MIN_RECONCILIATION_SECRET_BYTES,
    SafeDisposition,
    StreamingTransformError,
    StreamingTransformSession,
    begin_streaming_transform,
)
from etl.view_identity import EXPECTED_CAPTURE_SESSION, ViewCaptureEvidence, ViewIdentityError

from .config import SourceConnectorConfig
from .errors import (
    SourceCancelled,
    SourceCleanupFailed,
    SourceConfigurationError,
    SourceConnectionFailed,
    SourceDatabaseFailed,
    SourceDriverUnavailable,
    SourceProtocolError,
    SourceTimedOut,
    TrustedSourceConnectorError,
)
from .models import (
    CancellationToken,
    PostgreSQLConnection,
    PostgreSQLCursor,
    SafeSourceSnapshotEvidence,
    SourcePreflightReport,
    cursor_column_names,
    mapping_row,
)

BEGIN_SQL = "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"

# These are the exact settings in the approved view-definition digest profile.
# They remain literals rather than deployment configuration: a caller may not
# change how PostgreSQL renders the definition being compared with approval.
#
# quote_all_identifiers is pinned OFF, and the value is load-bearing rather than
# arbitrary. information_schema.columns.data_type is rendered with
# format_type(), which honours this GUC. With the setting ON, PostgreSQL quotes
# types such as date and text, so the observed 39-column schema no longer matches
# the reviewed contract. OFF also keeps the captured form aligned with psql.
FIXED_SESSION_SQL: tuple[str, ...] = (
    "SET LOCAL search_path = pg_catalog",
    "SET LOCAL client_encoding = 'UTF8'",
    "SET LOCAL quote_all_identifiers = off",
    "SET LOCAL standard_conforming_strings = on",
    "SET LOCAL DateStyle = 'ISO, YMD'",
    "SET LOCAL IntervalStyle = 'postgres'",
    "SET LOCAL TimeZone = 'UTC'",
    "SET LOCAL extra_float_digits = 3",
    "SET LOCAL bytea_output = 'hex'",
    "SET LOCAL lc_numeric = 'C'",
)

SESSION_VERIFY_SQL = """
SELECT
    current_setting('transaction_isolation') AS transaction_isolation,
    current_setting('transaction_read_only') AS transaction_read_only,
    current_setting('search_path') AS search_path,
    current_setting('client_encoding') AS client_encoding,
    current_setting('quote_all_identifiers') AS quote_all_identifiers,
    current_setting('standard_conforming_strings') AS standard_conforming_strings,
    current_setting('DateStyle') AS "DateStyle",
    current_setting('IntervalStyle') AS "IntervalStyle",
    current_setting('TimeZone') AS "TimeZone",
    current_setting('extra_float_digits') AS extra_float_digits,
    current_setting('bytea_output') AS bytea_output,
    current_setting('lc_numeric') AS lc_numeric,
    pg_catalog.inet_server_addr() IS NOT NULL AS tcp_transport,
    COALESCE(
        (
            SELECT ssl
            FROM pg_catalog.pg_stat_ssl
            WHERE pid = pg_catalog.pg_backend_pid()
        ),
        false
    ) AS tls_active,
    current_database() AS database_name,
    current_user AS extraction_role
""".strip()

SESSION_HEADER = (
    "transaction_isolation",
    "transaction_read_only",
    *EXPECTED_CAPTURE_SESSION,
    "tcp_transport",
    "tls_active",
    "database_name",
    "extraction_role",
)

# One fixed, value-parameterised catalogue statement captures the view identity
# and every ordered information_schema attribute consumed by ViewCaptureEvidence.
# It does not read a source row.  Schema/object values are bound parameters,
# never interpolated identifiers.
CATALOG_CAPTURE_SQL = """
WITH target AS MATERIALIZED (
    SELECT
        c.oid,
        c.relkind,
        c.relpersistence,
        c.relowner,
        c.reloptions,
        n.nspname,
        c.relname
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = %s
      AND c.relname = %s
      AND c.relkind = 'v'
),
column_evidence AS MATERIALIZED (
    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'ordinal_position', ordinal_position,
                'column_name', column_name,
                'data_type', data_type,
                'udt_schema', udt_schema,
                'udt_name', udt_name,
                'character_maximum_length', character_maximum_length,
                'numeric_precision', numeric_precision,
                'numeric_scale', numeric_scale,
                'is_nullable', is_nullable,
                'collation_schema', collation_schema,
                'collation_name', collation_name
            ) ORDER BY ordinal_position
        ),
        '[]'::jsonb
    ) AS columns
    FROM information_schema.columns
    WHERE table_catalog = current_database()
      AND table_schema = %s
      AND table_name = %s
)
SELECT
    to_char(
        transaction_timestamp() AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    ) AS captured_at_utc,
    current_database() AS database_name,
    current_setting('server_version') AS server_version,
    current_setting('server_version_num')::integer AS server_version_num,
    current_setting('server_encoding') AS server_encoding,
    current_user AS extraction_role,
    t.nspname AS schema_name,
    t.relname AS object_name,
    t.nspname || '.' || t.relname AS qualified_name,
    t.oid AS relation_oid,
    t.relkind,
    t.relpersistence,
    pg_catalog.pg_get_userbyid(t.relowner) AS owner,
    COALESCE(
        (
            SELECT jsonb_agg(option ORDER BY option)
            FROM unnest(COALESCE(t.reloptions, ARRAY[]::text[])) AS options(option)
        ),
        '[]'::jsonb
    ) AS reloptions,
    pg_catalog.pg_get_viewdef(t.oid, false) AS view_definition,
    encode(
        convert_to(pg_catalog.pg_get_viewdef(t.oid, false), 'UTF8'),
        'hex'
    ) AS view_definition_utf8_hex,
    ce.columns
FROM target AS t
CROSS JOIN column_evidence AS ce
""".strip()

CATALOG_HEADER = (
    "captured_at_utc",
    "database_name",
    "server_version",
    "server_version_num",
    "server_encoding",
    "extraction_role",
    "schema_name",
    "object_name",
    "qualified_name",
    "relation_oid",
    "relkind",
    "relpersistence",
    "owner",
    "reloptions",
    "view_definition",
    "view_definition_utf8_hex",
    "columns",
)

_SAFE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")


def _quoted_identifier(value: str) -> str:
    """Quote a contract identifier after enforcing the reviewed name profile."""
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise SourceConfigurationError()
    return f'"{value}"'


def _default_connection_factory(
    config: SourceConnectorConfig,
) -> PostgreSQLConnection:
    """Open a fresh Psycopg connection without importing it at module import."""
    configuration_failure: TrustedSourceConnectorError | None = None
    try:
        config.connection.assert_process_environment()
    except Exception:
        # Environment/config exceptions may contain infrastructure paths. They
        # never cross the connector boundary and no driver import is attempted.
        configuration_failure = SourceConfigurationError()
    if configuration_failure is not None:
        raise configuration_failure

    driver_failure: TrustedSourceConnectorError | None = None
    try:
        psycopg = importlib.import_module("psycopg")
        rows = importlib.import_module("psycopg.rows")
    except ImportError:
        driver_failure = SourceDriverUnavailable()
    if driver_failure is not None:
        raise driver_failure

    connection_failure: TrustedSourceConnectorError | None = None
    try:
        return psycopg.connect(  # type: ignore[no-any-return]
            autocommit=True,
            row_factory=rows.dict_row,
            **config.connection.parameters(),
        )
    except Exception:
        connection_failure = SourceConnectionFailed()
    raise connection_failure


def _sanitise_exception(exception: BaseException) -> BaseException:
    """Remove every inspectable link to a lower-level exception or traceback."""
    exception.__cause__ = None
    exception.__context__ = None
    exception.__suppress_context__ = True
    exception.__traceback__ = None
    return exception


def _execute(
    cursor: PostgreSQLCursor,
    query: object,
    params: Sequence[object] | None = None,
) -> None:
    if params is None:
        cursor.execute(query)
    else:
        cursor.execute(query, params)


def _one_row(
    cursor: PostgreSQLCursor,
    *,
    expected_header: Sequence[str],
) -> dict[str, object]:
    """Read exactly one result row and validate its header before its values."""
    try:
        header = cursor_column_names(cursor.description)
    except ValueError:
        raise SourceProtocolError() from None
    if header != tuple(expected_header):
        raise SourceProtocolError()
    first = cursor.fetchone()
    if first is None or cursor.fetchone() is not None:
        raise SourceProtocolError()
    try:
        row = mapping_row(first, header)
    except ValueError:
        raise SourceProtocolError() from None
    if tuple(row) != header:
        raise SourceProtocolError()
    return row


def _capture_document(row: Mapping[str, object]) -> dict[str, object]:
    """Create the exact raw document parsed by the existing identity boundary."""
    return {
        "artifact_format": "brerc-view-capture/v1",
        "captured_at_utc": row["captured_at_utc"],
        "postgres": {
            "database": row["database_name"],
            "server_version": row["server_version"],
            "server_version_num": row["server_version_num"],
            "server_major": int(row["server_version_num"]) // 10000,
            "server_encoding": row["server_encoding"],
            "captured_by_database_role": row["extraction_role"],
        },
        "session": dict(EXPECTED_CAPTURE_SESSION),
        "object": {
            "schema": row["schema_name"],
            "name": row["object_name"],
            "qualified_name": row["qualified_name"],
            "relation_oid": row["relation_oid"],
            "relkind": row["relkind"],
            "relpersistence": row["relpersistence"],
            "owner": row["owner"],
            "reloptions": row["reloptions"],
        },
        "view_definition": row["view_definition"],
        "view_definition_utf8_hex": row["view_definition_utf8_hex"],
        "columns": row["columns"],
    }


def _metadata_from_evidence(evidence: ViewCaptureEvidence) -> SourceMetadata:
    return SourceMetadata(
        schema=evidence.observation.schema,
        name=evidence.observation.name,
        object_type="view",
        columns=tuple(
            SourceColumn(
                column.name,
                column.data_type,
                column.character_maximum_length,
                column.numeric_precision,
                column.numeric_scale,
            )
            for column in evidence.contract_columns
        ),
        observed_view=evidence.observation,
        observed_catalog_columns_sha256=evidence.catalog_columns_sha256,
    )


class _SafeInitialSnapshot:
    """Private context/iterator yielding only already-generalised row batches."""

    def __init__(
        self,
        connector: TrustedPostgreSQLSourceConnector,
        *,
        source_contract: SourceContract,
        columns: ColumnMap,
        policy: PublicationPolicy,
        reconciliation_secret: bytes,
        dictionary: SpeciesDictionary | None,
        cancellation: CancellationToken | None,
        absolute_deadline: float | None,
    ) -> None:
        self._connector = connector
        self._source_contract = source_contract
        self._columns = columns
        self._policy = policy
        self._secret = reconciliation_secret
        self._dictionary = dictionary
        self._cancellation = cancellation
        self._absolute_deadline = absolute_deadline
        self._connection: PostgreSQLConnection | None = None
        self._control_cursor: PostgreSQLCursor | None = None
        self._row_cursor: PostgreSQLCursor | None = None
        self._transform: StreamingTransformSession | None = None
        self._evidence: ViewCaptureEvidence | None = None
        self._header: tuple[str, ...] | None = None
        self._deadline = 0.0
        self._exhausted = False
        self._snapshot_evidence: SafeSourceSnapshotEvidence | None = None

    def __enter__(self) -> _SafeInitialSnapshot:
        connection: PostgreSQLConnection | None = None
        try:
            own_deadline = self._connector._deadline()
            self._deadline = (
                own_deadline
                if self._absolute_deadline is None
                else min(own_deadline, self._absolute_deadline)
            )
            self._connector._check_interrupt(self._cancellation, None, self._deadline)
            connection = self._connector._open_connection()
            self._connection = connection
            self._connector._check_interrupt(self._cancellation, connection, self._deadline)
            control = connection.cursor()
            self._control_cursor = control
            _execute(control, BEGIN_SQL)
            for statement in FIXED_SESSION_SQL:
                _execute(control, statement)
            runtime = self._connector._config.runtime
            remaining_ms = max(1, int((self._deadline - time.monotonic()) * 1_000))
            statement_timeout_ms = min(runtime.statement_timeout_ms, remaining_ms)
            lock_timeout_ms = min(runtime.lock_timeout_ms, remaining_ms)
            _execute(control, f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'")
            _execute(control, f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
            _execute(
                control,
                "SET LOCAL idle_in_transaction_session_timeout = "
                f"'{runtime.idle_in_transaction_session_timeout_ms}ms'",
            )
            qualified_view = (
                f"{_quoted_identifier(self._source_contract.schema)}."
                f"{_quoted_identifier(self._source_contract.name)}"
            )
            _execute(control, f"LOCK TABLE {qualified_view} IN ACCESS SHARE MODE")
            self._connector._check_interrupt(self._cancellation, connection, self._deadline)
            session = self._connector._read_session(control)
            self._connector._validate_session(session)
            evidence = self._connector._capture_view(control, self._source_contract)
            metadata = _metadata_from_evidence(evidence)
            self._source_contract.validate_initial(metadata)
            projection = (*self._columns.required(), *self._columns.optional())
            row_cursor = connection.cursor(name="brerc_safe_source_rows")
            self._row_cursor = row_cursor
            _execute(
                row_cursor,
                self._connector._row_query(
                    self._source_contract,
                    projection,
                    qualified_view,
                ),
            )
            try:
                header = cursor_column_names(row_cursor.description)
            except ValueError:
                raise SourceProtocolError() from None
            self._source_contract.validate_result_header(header, projection)
            self._transform = begin_streaming_transform(
                columns=self._columns,
                source_contract=self._source_contract,
                source_metadata=metadata,
                source_result_columns=header,
                policy=self._policy,
                reconciliation_secret=self._secret,
                dictionary=self._dictionary,
            )
            self._evidence = evidence
            self._header = header
            return self
        except TrustedSourceConnectorError as exc:
            failure: BaseException = exc
        except (SourceContractError, ViewIdentityError, StreamingTransformError):
            failure = SourceProtocolError()
        except (KeyboardInterrupt, SystemExit) as exc:
            if connection is not None:
                self._connector._cancel_without_raising(connection)
            failure = exc
        except Exception:
            failure = SourceDatabaseFailed()
        self._cleanup()
        raise _sanitise_exception(failure)

    def __iter__(self) -> _SafeInitialSnapshot:
        return self

    def __next__(self) -> tuple[SafeDisposition, ...]:
        if self._exhausted:
            raise StopIteration
        connection = self._connection
        cursor = self._row_cursor
        transform = self._transform
        header = self._header
        evidence = self._evidence
        if None in (connection, cursor, transform, header, evidence):
            raise _sanitise_exception(SourceProtocolError())
        try:
            self._connector._check_interrupt(self._cancellation, connection, self._deadline)
            batch = cursor.fetchmany(self._connector._config.runtime.batch_size)
            self._connector._check_interrupt(self._cancellation, connection, self._deadline)
            if len(batch) > self._connector._config.runtime.batch_size:
                raise SourceProtocolError()
            if not batch:
                report = transform.finish()
                if not report.reconciles():
                    raise SourceProtocolError()
                approval_digest = self._policy.approval_digest
                if approval_digest is None:
                    raise SourceProtocolError()
                self._snapshot_evidence = SafeSourceSnapshotEvidence(
                    captured_at_utc=evidence.captured_at_utc,
                    contract_version=self._source_contract.version,
                    contract_sha256=self._source_contract.digest(),
                    policy_version=self._policy.version,
                    policy_approval_digest=approval_digest,
                    observed_definition_sha256=evidence.observation.definition_sha256,
                    observed_identity_sha256=evidence.identity_sha256,
                    result_columns=header,
                    rows_seen=report.rows_in,
                    records_eligible_before_suppression=report.records_public,
                    withheld_by_reason=tuple(sorted(report.withheld.items())),
                    sensitivity_buckets=transform.sensitivity_buckets,
                )
                self._exhausted = True
                raise StopIteration
            mapped: list[dict[str, object]] = []
            for raw in batch:
                try:
                    row = mapping_row(raw, header)
                except ValueError:
                    raise SourceProtocolError() from None
                if tuple(row) != header:
                    raise SourceProtocolError()
                mapped.append(row)
            result = transform.transform_batch(mapped)
            self._connector._check_interrupt(self._cancellation, connection, self._deadline)
            return result
        except StopIteration:
            raise
        except TrustedSourceConnectorError as exc:
            failure = exc
        except (SourceContractError, ViewIdentityError, StreamingTransformError):
            failure = SourceProtocolError()
        except (KeyboardInterrupt, SystemExit) as exc:
            self._connector._cancel_without_raising(connection)
            failure = exc
        except Exception:
            failure = SourceDatabaseFailed()
        raise _sanitise_exception(failure)

    @property
    def evidence(self) -> SafeSourceSnapshotEvidence:
        if not self._exhausted or self._snapshot_evidence is None:
            raise SourceProtocolError()
        return self._snapshot_evidence

    def _cleanup(self) -> bool:
        failed = False
        for cursor in (self._row_cursor, self._control_cursor):
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    failed = True
        if self._connection is not None:
            try:
                self._connection.rollback()
            except Exception:
                failed = True
            try:
                self._connection.close()
            except Exception:
                failed = True
        return failed

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        cleanup_failed = self._cleanup()
        if cleanup_failed:
            raise _sanitise_exception(SourceCleanupFailed())
        return False


class TrustedPostgreSQLSourceConnector:
    """Extract one initial-load candidate from an approved PostgreSQL view."""

    def __init__(
        self,
        config: SourceConnectorConfig,
    ) -> None:
        if not isinstance(config, SourceConnectorConfig):
            raise SourceConfigurationError()
        self._config = config

    @classmethod
    def from_config(
        cls,
        config: SourceConnectorConfig,
    ) -> TrustedPostgreSQLSourceConnector:
        """Construct from the sole accepted, contract-bound config object."""
        return cls(config)

    def _open_safe_initial_snapshot(
        self,
        *,
        source_contract: SourceContract,
        columns: ColumnMap,
        policy: PublicationPolicy,
        reconciliation_secret: bytes,
        dictionary: SpeciesDictionary | None = None,
        cancellation: CancellationToken | None = None,
        absolute_deadline: float | None = None,
    ) -> _SafeInitialSnapshot:
        """Build the private bounded-memory source stream used by the loader.

        The returned context yields only :class:`SafeDisposition` batches. Raw
        rows, headers, catalogue data and source identifiers remain inside this
        module and the database transaction is rolled back on every exit path.
        """
        self._validate_config(source_contract, columns)
        source_contract.require_mode(LoadMode.INITIAL)
        policy.validate()
        policy.assert_approved()
        source_contract.assert_release_ready()
        source_contract.validate_safety_mapping(columns, policy)
        projection = (*columns.required(), *columns.optional())
        source_contract.validate_result_header(projection, projection)
        if (
            not isinstance(reconciliation_secret, bytes)
            or len(reconciliation_secret) < MIN_RECONCILIATION_SECRET_BYTES
        ):
            raise SourceConfigurationError()
        if absolute_deadline is not None and (
            isinstance(absolute_deadline, bool)
            or not isinstance(absolute_deadline, int | float)
            or absolute_deadline <= time.monotonic()
        ):
            raise SourceConfigurationError()
        return _SafeInitialSnapshot(
            self,
            source_contract=source_contract,
            columns=columns,
            policy=policy,
            reconciliation_secret=bytes(reconciliation_secret),
            dictionary=dictionary,
            cancellation=cancellation,
            absolute_deadline=None if absolute_deadline is None else float(absolute_deadline),
        )

    def extract_initial(
        self,
        *,
        source_contract: SourceContract,
        columns: ColumnMap,
        policy: PublicationPolicy,
        dictionary: SpeciesDictionary | None = None,
        cancellation: CancellationToken | None = None,
    ) -> ValidatedSourceRun:
        """Return only a fully source-validated run; partial data never escapes."""
        # Every configuration/policy/approval failure must occur before opening
        # a socket or touching source rows.
        self._validate_config(source_contract, columns)
        source_contract.require_mode(LoadMode.INITIAL)
        policy.validate()
        policy.assert_approved()
        source_contract.assert_release_ready()
        source_contract.validate_safety_mapping(columns, policy)
        projection = (*columns.required(), *columns.optional())
        source_contract.validate_result_header(projection, projection)
        deadline = self._deadline()
        self._check_interrupt(cancellation, None, deadline)

        connection = self._open_connection()
        control_cursor: PostgreSQLCursor | None = None
        row_cursor: PostgreSQLCursor | None = None
        result: ValidatedSourceRun | None = None
        operation_error: BaseException | None = None
        cleanup_failed = False
        try:
            self._check_interrupt(cancellation, connection, deadline)
            control_cursor = connection.cursor()
            _execute(control_cursor, BEGIN_SQL)
            self._check_interrupt(cancellation, connection, deadline)
            for statement in FIXED_SESSION_SQL:
                _execute(control_cursor, statement)
            self._check_interrupt(cancellation, connection, deadline)
            runtime = self._config.runtime
            _execute(
                control_cursor,
                f"SET LOCAL statement_timeout = '{runtime.statement_timeout_ms}ms'",
            )
            _execute(
                control_cursor,
                f"SET LOCAL lock_timeout = '{runtime.lock_timeout_ms}ms'",
            )
            _execute(
                control_cursor,
                "SET LOCAL idle_in_transaction_session_timeout = "
                f"'{runtime.idle_in_transaction_session_timeout_ms}ms'",
            )
            self._check_interrupt(cancellation, connection, deadline)
            # LOCK must precede the first SELECT in REPEATABLE READ: that first
            # SELECT establishes the transaction snapshot. Locking first closes
            # the DDL window between identity capture and row extraction.
            qualified_view = (
                f"{_quoted_identifier(source_contract.schema)}."
                f"{_quoted_identifier(source_contract.name)}"
            )
            _execute(
                control_cursor,
                f"LOCK TABLE {qualified_view} IN ACCESS SHARE MODE",
            )
            self._check_interrupt(cancellation, connection, deadline)
            session = self._read_session(control_cursor)
            self._check_interrupt(cancellation, connection, deadline)
            self._validate_session(session)
            evidence = self._capture_view(control_cursor, source_contract)
            self._check_interrupt(cancellation, connection, deadline)
            metadata = SourceMetadata(
                schema=evidence.observation.schema,
                name=evidence.observation.name,
                object_type="view",
                columns=tuple(
                    SourceColumn(
                        column.name,
                        column.data_type,
                        column.character_maximum_length,
                        column.numeric_precision,
                        column.numeric_scale,
                    )
                    for column in evidence.contract_columns
                ),
                observed_view=evidence.observation,
                observed_catalog_columns_sha256=evidence.catalog_columns_sha256,
            )
            # This is deliberately repeated by run_pipeline_for_source.  Here it
            # guarantees identity/schema drift fails before DECLARE/FETCH.
            source_contract.validate_initial(metadata)

            row_cursor = connection.cursor(name="brerc_source_rows")
            row_query = self._row_query(source_contract, projection, qualified_view)
            _execute(row_cursor, row_query)
            self._check_interrupt(cancellation, connection, deadline)
            try:
                result_header = cursor_column_names(row_cursor.description)
            except ValueError:
                raise SourceProtocolError() from None
            source_contract.validate_result_header(result_header, projection)

            result = run_pipeline_for_source(
                self._rows(row_cursor, result_header, connection, cancellation, deadline),
                columns,
                source_contract=source_contract,
                source_metadata=metadata,
                source_result_columns=result_header,
                load_mode=LoadMode.INITIAL,
                policy=policy,
                dictionary=dictionary,
            )
            # The database statement timeouts do not cover in-process ETL.
            # Check once more before allowing a candidate to escape so a run
            # that exceeded its total operational deadline is discarded.
            self._check_interrupt(cancellation, connection, deadline)
        except TrustedSourceConnectorError as exc:
            operation_error = exc
        except (InvalidPolicy, PolicyNotApproved, SourceContractError, ViewIdentityError):
            # Post-connect validation exceptions may contain observed catalogue
            # values.  Do not let those details cross the connector boundary.
            operation_error = SourceProtocolError()
        except (KeyboardInterrupt, SystemExit) as exc:
            self._cancel_without_raising(connection)
            operation_error = exc
        except Exception:
            operation_error = SourceDatabaseFailed()
        finally:
            for cursor in (row_cursor, control_cursor):
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        cleanup_failed = True
            try:
                connection.rollback()
            except Exception:
                cleanup_failed = True
            try:
                connection.close()
            except Exception:
                cleanup_failed = True

        if operation_error is not None:
            raise _sanitise_exception(operation_error)
        if cleanup_failed:
            raise _sanitise_exception(SourceCleanupFailed())
        if result is None:  # defensive: every normal path assigns a result
            raise _sanitise_exception(SourceDatabaseFailed())
        return result

    def preflight(
        self,
        *,
        source_contract: SourceContract,
        columns: ColumnMap,
        cancellation: CancellationToken | None = None,
    ) -> SourcePreflightReport:
        """Validate live source structure without reading a source row.

        Unlike extraction, this diagnostic is usable before BRERC approval is
        integrated. It reports ``release_ready=False`` rather than weakening the
        release gate. It still uses the same lock/snapshot/session/catalogue and
        explicit projection, and it never calls ``fetchmany``.
        """
        self._validate_config(source_contract, columns)
        source_contract.require_mode(LoadMode.INITIAL)
        deadline = self._deadline()
        self._check_interrupt(cancellation, None, deadline)
        connection = self._open_connection()
        control_cursor: PostgreSQLCursor | None = None
        row_cursor: PostgreSQLCursor | None = None
        report: SourcePreflightReport | None = None
        operation_error: BaseException | None = None
        cleanup_failed = False
        try:
            self._check_interrupt(cancellation, connection, deadline)
            control_cursor = connection.cursor()
            _execute(control_cursor, BEGIN_SQL)
            self._check_interrupt(cancellation, connection, deadline)
            for statement in FIXED_SESSION_SQL:
                _execute(control_cursor, statement)
            self._check_interrupt(cancellation, connection, deadline)
            runtime = self._config.runtime
            _execute(
                control_cursor,
                f"SET LOCAL statement_timeout = '{runtime.statement_timeout_ms}ms'",
            )
            _execute(control_cursor, f"SET LOCAL lock_timeout = '{runtime.lock_timeout_ms}ms'")
            _execute(
                control_cursor,
                "SET LOCAL idle_in_transaction_session_timeout = "
                f"'{runtime.idle_in_transaction_session_timeout_ms}ms'",
            )
            self._check_interrupt(cancellation, connection, deadline)
            qualified_view = (
                f"{_quoted_identifier(source_contract.schema)}."
                f"{_quoted_identifier(source_contract.name)}"
            )
            _execute(control_cursor, f"LOCK TABLE {qualified_view} IN ACCESS SHARE MODE")
            self._check_interrupt(cancellation, connection, deadline)
            session = self._read_session(control_cursor)
            self._check_interrupt(cancellation, connection, deadline)
            self._validate_session(session)
            evidence = self._capture_view(control_cursor, source_contract)
            self._check_interrupt(cancellation, connection, deadline)
            metadata = SourceMetadata(
                schema=evidence.observation.schema,
                name=evidence.observation.name,
                object_type="view",
                columns=tuple(
                    SourceColumn(
                        column.name,
                        column.data_type,
                        column.character_maximum_length,
                        column.numeric_precision,
                        column.numeric_scale,
                    )
                    for column in evidence.contract_columns
                ),
                observed_view=evidence.observation,
                observed_catalog_columns_sha256=evidence.catalog_columns_sha256,
            )
            schema_report = source_contract.validate_initial(metadata)
            projection = self._config.projection
            row_cursor = connection.cursor(name="brerc_source_preflight")
            row_query = self._preflight_query(projection, qualified_view)
            _execute(row_cursor, row_query)
            self._check_interrupt(cancellation, connection, deadline)
            try:
                header = cursor_column_names(row_cursor.description)
            except ValueError:
                raise SourceProtocolError() from None
            source_contract.validate_result_header(header, projection)
            report = SourcePreflightReport(
                contract_version=source_contract.version,
                contract_sha256=source_contract.digest(),
                observed_definition_sha256=evidence.observation.definition_sha256,
                observed_identity_sha256=evidence.identity_sha256,
                confirmed_columns=schema_report.confirmed_columns,
                result_columns=header,
                release_ready=schema_report.release_supported,
            )
        except TrustedSourceConnectorError as exc:
            operation_error = exc
        except (SourceContractError, ViewIdentityError):
            # Observed headers/catalogue details remain inside the boundary.
            operation_error = SourceProtocolError()
        except (KeyboardInterrupt, SystemExit) as exc:
            self._cancel_without_raising(connection)
            operation_error = exc
        except Exception:
            operation_error = SourceDatabaseFailed()
        finally:
            for cursor in (row_cursor, control_cursor):
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        cleanup_failed = True
            try:
                connection.rollback()
            except Exception:
                cleanup_failed = True
            try:
                connection.close()
            except Exception:
                cleanup_failed = True
        if operation_error is not None:
            raise _sanitise_exception(operation_error)
        if cleanup_failed:
            raise _sanitise_exception(SourceCleanupFailed())
        if report is None:
            raise _sanitise_exception(SourceDatabaseFailed())
        return report

    def _open_connection(self) -> PostgreSQLConnection:
        failure: TrustedSourceConnectorError | None = None
        try:
            return _default_connection_factory(self._config)
        except TrustedSourceConnectorError as exc:
            failure = exc
        except Exception:
            failure = SourceConnectionFailed()
        raise _sanitise_exception(failure)

    def _validate_config(self, source_contract: SourceContract, columns: ColumnMap) -> None:
        # SQL identifiers are contract-controlled, but validate their restricted
        # profile before opening a socket so an invalid contract cannot reach a
        # transaction and cannot participate in dynamic SQL composition.
        for identifier in (
            source_contract.schema,
            source_contract.name,
            source_contract.record_id_column,
            *self._config.projection,
        ):
            _quoted_identifier(identifier)
        if self._config.contract_version != source_contract.version:
            raise SourceConfigurationError()
        if self._config.column_map != columns:
            raise SourceConfigurationError()
        if self._config.source_columns != tuple(column.name for column in source_contract.columns):
            raise SourceConfigurationError()
        projection = (*columns.required(), *columns.optional())
        if self._config.projection != projection:
            raise SourceConfigurationError()
        if (
            self._config.source.engine != "postgresql"
            or self._config.source.schema != source_contract.schema
            or self._config.source.object != source_contract.name
            or self._config.source.object_type != source_contract.object_type
            or not self._config.source.strict_schema
        ):
            raise SourceConfigurationError()
        required = source_contract.required_source_environment
        if required is not None and self._config.runtime.source_environment != required:
            raise SourceConfigurationError()

    def _read_session(self, cursor: PostgreSQLCursor) -> dict[str, object]:
        _execute(cursor, SESSION_VERIFY_SQL)
        return _one_row(cursor, expected_header=SESSION_HEADER)

    def _validate_session(self, row: Mapping[str, object]) -> None:
        if row["transaction_isolation"] != "repeatable read":
            raise SourceProtocolError()
        if row["transaction_read_only"] != "on":
            raise SourceProtocolError()
        if row["tcp_transport"] is not True or row["tls_active"] is not True:
            raise SourceProtocolError()
        if row["database_name"] != self._config.runtime.expected_database:
            raise SourceProtocolError()
        if row["extraction_role"] != self._config.runtime.expected_role:
            raise SourceProtocolError()
        for name, expected in EXPECTED_CAPTURE_SESSION.items():
            if row[name] != expected:
                raise SourceProtocolError()

    def _capture_view(
        self,
        cursor: PostgreSQLCursor,
        contract: SourceContract,
    ) -> ViewCaptureEvidence:
        params = (contract.schema, contract.name, contract.schema, contract.name)
        _execute(cursor, CATALOG_CAPTURE_SQL, params)
        row = _one_row(cursor, expected_header=CATALOG_HEADER)
        if row["database_name"] != self._config.runtime.expected_database:
            raise SourceProtocolError()
        if row["extraction_role"] != self._config.runtime.expected_role:
            raise SourceProtocolError()
        try:
            return ViewCaptureEvidence.from_document(_capture_document(row))
        except (KeyError, TypeError, ValueError, ViewIdentityError):
            raise SourceProtocolError() from None

    def _rows(
        self,
        cursor: PostgreSQLCursor,
        header: tuple[str, ...],
        connection: PostgreSQLConnection,
        cancellation: CancellationToken | None,
        deadline: float,
    ) -> Iterator[dict[str, object]]:
        while True:
            self._check_interrupt(cancellation, connection, deadline)
            batch = cursor.fetchmany(self._config.runtime.batch_size)
            self._check_interrupt(cancellation, connection, deadline)
            if not batch:
                return
            if len(batch) > self._config.runtime.batch_size:
                raise SourceProtocolError()
            for raw in batch:
                try:
                    row = mapping_row(raw, header)
                except ValueError:
                    raise SourceProtocolError() from None
                if tuple(row) != header:
                    raise SourceProtocolError()
                yield row

    def _deadline(self) -> float:
        return time.monotonic() + self._config.runtime.total_timeout_seconds

    def _check_interrupt(
        self,
        cancellation: CancellationToken | None,
        connection: PostgreSQLConnection | None,
        deadline: float,
    ) -> None:
        if time.monotonic() >= deadline:
            if connection is not None:
                self._cancel_without_raising(connection)
            raise SourceTimedOut()
        if cancellation is None or not cancellation.is_cancelled():
            return
        if connection is not None:
            self._cancel_without_raising(connection)
        raise SourceCancelled()

    def _cancel_without_raising(self, connection: PostgreSQLConnection) -> None:
        try:
            connection.cancel_safe(timeout=min(10.0, self._config.runtime.total_timeout_seconds))
        except Exception:
            # Cancellation is advisory. Rollback and connection disposal in the
            # caller remain mandatory even when the server cannot acknowledge it.
            return

    @staticmethod
    def _row_query(
        source_contract: SourceContract,
        projection: Sequence[str],
        qualified_view: str,
    ) -> str:
        projection_sql = ", ".join(_quoted_identifier(name) for name in projection)
        record_id_sql = _quoted_identifier(source_contract.record_id_column)
        # Every fragment was first matched against the versioned contract and
        # then restricted/quoted by _quoted_identifier. No caller or row value
        # participates in SQL composition.  Psycopg parameters cannot represent
        # identifiers, so this reviewed builder is intentional.
        return f"SELECT {projection_sql} FROM {qualified_view} ORDER BY {record_id_sql} ASC NULLS FIRST"  # noqa: S608

    @staticmethod
    def _preflight_query(
        projection: Sequence[str],
        qualified_view: str,
    ) -> str:
        """Compile a reviewed zero-row statement used only to verify headers."""
        projection_sql = ", ".join(_quoted_identifier(name) for name in projection)
        # LIMIT 0 resolves the projection without fetching a source row. Every
        # identifier passed the strict contract-name profile and is quoted.
        return f"SELECT {projection_sql} FROM {qualified_view} LIMIT 0"  # noqa: S608

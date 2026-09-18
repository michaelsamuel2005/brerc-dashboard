"""Adversarial lifecycle tests for the trusted PostgreSQL source connector."""

from __future__ import annotations

import dataclasses
import inspect
import unittest
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from types import SimpleNamespace
from typing import NoReturn
from unittest.mock import patch

from brerc_source import (
    SourceCancelled,
    SourceCleanupFailed,
    SourceConfigurationError,
    SourceConnectionFailed,
    SourceDatabaseFailed,
    SourceProtocolError,
    SourceTimedOut,
    TrustedPostgreSQLSourceConnector,
)
from brerc_source.config import (
    ConnectionConfig,
    RuntimeConfig,
    SourceConnectorConfig,
    SourceLocation,
)
from brerc_source.postgres import (
    BEGIN_SQL,
    CATALOG_CAPTURE_SQL,
    CATALOG_HEADER,
    FIXED_SESSION_SQL,
    SESSION_HEADER,
    SESSION_VERIFY_SQL,
    _default_connection_factory,
)
from etl.pipeline import ColumnMap, ValidatedSourceRun
from etl.policy import InvalidPolicy, PublicationPolicy
from etl.sensitivity import SENSITIVE_SNAPSHOT_SHA256, SENSITIVE_SNAPSHOT_VERSION
from etl.source_contract import BRERC_MAIN_DATA_DASH, SourceContract, SourceContractError
from etl.species import SpeciesDictionary
from etl.view_identity import (
    EXPECTED_CAPTURE_SESSION,
    ViewCaptureEvidence,
    ViewDefinitionApproval,
)

VIEW_COLUMNS = ColumnMap(
    record_id="unique_no",
    species_id="species_no",
    scientific_name="scientific_name",
    grid_ref="grid_ref",
    year="year_end",
    common_name="common_name",
    abundance="abundance",
    record_type="record_type",
    licence="licence",
    sensitivity="sensitive",
)
PROJECTION = (*VIEW_COLUMNS.required(), *VIEW_COLUMNS.optional())
CONNECTOR_DICTIONARY = SpeciesDictionary.from_rows(
    [
        {
            "SPECIES_NO": "5088",
            "SCIENTIFIC": "Anguis fragilis",
            "COMMON_NAM": "Slow-worm",
            "SENSITIVE": "No",
        },
        {
            "SPECIES_NO": "SYNTH-1",
            "SCIENTIFIC": "Synthetic species alpha",
            "COMMON_NAM": "Synthetic alpha",
            "SENSITIVE": "No",
        },
        {
            "SPECIES_NO": "SYNTH-2",
            "SCIENTIFIC": "Synthetic species beta",
            "COMMON_NAM": "Synthetic beta",
            "SENSITIVE": "Yes",
        },
    ]
)


class TestConnector:
    """Test-only proxy that patches private module dependencies for one call."""

    def __init__(self, config, *, connection_factory, monotonic=None):
        self.connector = TrustedPostgreSQLSourceConnector.from_config(config)
        self.connection_factory = connection_factory
        self.monotonic = monotonic

    def _call(self, method, **kwargs):
        with patch(
            "brerc_source.postgres._default_connection_factory",
            side_effect=self.connection_factory,
        ):
            if self.monotonic is None:
                return method(**kwargs)
            with patch("brerc_source.postgres.time.monotonic", side_effect=self.monotonic):
                return method(**kwargs)

    def extract_initial(self, **kwargs):
        kwargs.setdefault("dictionary", CONNECTOR_DICTIONARY)
        return self._call(self.connector.extract_initial, **kwargs)

    def preflight(self, **kwargs):
        return self._call(self.connector.preflight, **kwargs)


def test_connector(config, *, connection_factory, monotonic=None):
    return TestConnector(
        config,
        connection_factory=connection_factory,
        monotonic=monotonic,
    )


def approved_policy() -> PublicationPolicy:
    policy = PublicationPolicy(
        version="connector-test-policy",
        precision_mode="approved",
        suppression_mode="none",
        licensing_mode="not-applicable",
        record_type_safety_mode="not-used",
        row_level_records_mode="aggregates-only",
        verification_publication_mode="unavailable",
        sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
        sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
        species_dictionary_sha256=CONNECTOR_DICTIONARY.digest(),
        ordinary_resolution_metres=100,
        default_sensitive_metres=10_000,
        row_sensitive_resolution_metres=1_000,
        non_sensitive_values=frozenset({"no"}),
        publish_individual_records=False,
        public_id_salt="connector-test-secret-material-32-bytes",
    )
    return policy.with_approval(
        approved_by="Synthetic BRERC owner",
        approver_role="Test data owner",
        approver_organisation="BRERC",
        evidence_reference="CONNECTOR-TEST-ONLY",
        approved_on=date.today().isoformat(),
        review_due=(date.today() + timedelta(days=365)).isoformat(),
    )


def raw_catalog_columns() -> list[dict[str, object]]:
    result = []
    for position, spec in enumerate(BRERC_MAIN_DATA_DASH.columns, start=1):
        if spec.data_type == "character varying":
            udt_name = "varchar"
        elif spec.data_type == "numeric":
            udt_name = "numeric"
        elif spec.data_type == "date":
            udt_name = "date"
        else:
            udt_name = "text"
        result.append(
            {
                "ordinal_position": position,
                "column_name": spec.name,
                "data_type": spec.data_type,
                "udt_schema": "pg_catalog",
                "udt_name": udt_name,
                "character_maximum_length": spec.character_maximum_length,
                "numeric_precision": spec.numeric_precision,
                "numeric_scale": spec.numeric_scale,
                "is_nullable": "YES",
                "collation_schema": None,
                "collation_name": None,
            }
        )
    return result


def session_row() -> dict[str, object]:
    return {
        "transaction_isolation": "repeatable read",
        "transaction_read_only": "on",
        **EXPECTED_CAPTURE_SESSION,
        "tcp_transport": True,
        "tls_active": True,
        "database_name": "brerc_source_test",
        "authenticated_role": "brerc_extract",
        "extraction_role": "brerc_extract",
    }


def catalog_row(*, definition: str = "SELECT synthetic_reviewed_source") -> dict[str, object]:
    return {
        "captured_at_utc": "2026-08-01T12:00:00.000000Z",
        "database_name": "brerc_source_test",
        "server_version": "16.4",
        "server_version_num": 160004,
        "server_encoding": "UTF8",
        "extraction_role": "brerc_extract",
        "schema_name": "dashboard",
        "object_name": "main_data_dash",
        "qualified_name": "dashboard.main_data_dash",
        "relation_oid": 12345,
        "relkind": "v",
        "relpersistence": "p",
        "owner": "brerc_owner",
        "reloptions": [],
        "view_definition": definition,
        "view_definition_utf8_hex": definition.encode("utf-8").hex(),
        "columns": raw_catalog_columns(),
    }


def capture_document(row: Mapping[str, object]) -> dict[str, object]:
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


def approved_contract() -> SourceContract:
    evidence = ViewCaptureEvidence.from_document(capture_document(catalog_row()))
    observation = evidence.observation
    approval = ViewDefinitionApproval(
        source_version="connector-test-source-v1",
        source_environment="synthetic-approved-source",
        client_reference_document_sha256=BRERC_MAIN_DATA_DASH.client_reference_document_sha256,
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
        approved_by="Synthetic BRERC owner",
        approver_role="Test data owner",
        approver_organisation="BRERC",
        captured_at_utc=evidence.captured_at_utc,
        approved_on=date.today().isoformat(),
        evidence_reference="CONNECTOR-VIEW-TEST-ONLY",
    )
    return dataclasses.replace(
        BRERC_MAIN_DATA_DASH,
        version="connector-test-source-v1",
        required_source_environment="synthetic-approved-source",
        view_approval=approval,
        release_blockers=(),
    )


def source_row(identifier: str = "1.00") -> dict[str, object]:
    return {
        "unique_no": identifier,
        "species_no": "5088",
        "scientific_name": "Anguis fragilis",
        "grid_ref": "ST587721",
        "year_end": "2024",
        "common_name": "Slow-worm",
        "abundance": "1",
        "record_type": "field record",
        "licence": "y",
        "sensitive": "No",
    }


class Description:
    def __init__(self, name: str):
        self.name = name


class FakeCursor:
    def __init__(self, connection: FakeConnection, *, rows: bool = False):
        self.connection = connection
        self.is_rows = rows
        self.description: Sequence[Description] | None = None
        self._single_rows: list[object] = []
        self._batches = [list(batch) for batch in connection.row_batches]
        self.fetchmany_calls: list[int] = []
        self.closed = False

    def execute(self, query: object, params: Sequence[object] | None = None) -> FakeCursor:
        text = str(query)
        self.connection.transcript.append(
            ("execute_rows" if self.is_rows else "execute", text, params)
        )
        if self.connection.fail_on and self.connection.fail_on in text:
            raise RuntimeError(f"adapter leaked {self.connection.adapter_detail}")
        if text == SESSION_VERIFY_SQL:
            self.description = [Description(name) for name in SESSION_HEADER]
            self._single_rows = [dict(self.connection.session)]
        elif text == CATALOG_CAPTURE_SQL:
            self.description = [Description(name) for name in CATALOG_HEADER]
            self._single_rows = [dict(self.connection.catalog)]
        elif self.is_rows:
            self.description = [Description(name) for name in self.connection.row_header]
        return self

    def fetchone(self) -> object:
        self.connection.transcript.append(("fetchone", "rows" if self.is_rows else "control", None))
        return self._single_rows.pop(0) if self._single_rows else None

    def fetchmany(self, size: int = 0) -> Sequence[object]:
        self.connection.transcript.append(("fetchmany", str(size), None))
        self.fetchmany_calls.append(size)
        return self._batches.pop(0) if self._batches else []

    def fetchall(self) -> NoReturn:  # pragma: no cover - a call is an immediate failure
        raise AssertionError("trusted connector must never call fetchall")

    def close(self) -> None:
        self.connection.transcript.append(
            ("close_cursor", "rows" if self.is_rows else "control", None)
        )
        self.closed = True
        if self.connection.fail_cursor_close:
            raise RuntimeError(f"cursor close leaked {self.connection.adapter_detail}")


class FakeConnection:
    def __init__(
        self,
        *,
        row_batches: Sequence[Sequence[object]],
        session: Mapping[str, object] | None = None,
        catalog: Mapping[str, object] | None = None,
        row_header: Sequence[str] = PROJECTION,
        fail_on: str | None = None,
        adapter_detail: str = "private-adapter-detail",
        fail_cursor_close: bool = False,
        fail_rollback: bool = False,
        fail_connection_close: bool = False,
    ):
        self.row_batches = row_batches
        self.session = session or session_row()
        self.catalog = catalog or catalog_row()
        self.row_header = tuple(row_header)
        self.fail_on = fail_on
        self.adapter_detail = adapter_detail
        self.fail_cursor_close = fail_cursor_close
        self.fail_rollback = fail_rollback
        self.fail_connection_close = fail_connection_close
        self.transcript: list[tuple[str, str, object]] = []
        self.control_cursor: FakeCursor | None = None
        self.row_cursor: FakeCursor | None = None
        self.rollback_calls = 0
        self.close_calls = 0
        self.cancel_calls = 0

    def cursor(self, name: str | None = None, **kwargs: object) -> FakeCursor:
        self.transcript.append(("cursor", name or "control", kwargs or None))
        cursor = FakeCursor(self, rows=name is not None)
        if name is None:
            self.control_cursor = cursor
        else:
            self.row_cursor = cursor
        return cursor

    def rollback(self) -> None:
        self.transcript.append(("rollback", "", None))
        self.rollback_calls += 1
        if self.fail_rollback:
            raise RuntimeError(f"rollback leaked {self.adapter_detail}")

    def close(self) -> None:
        self.transcript.append(("close_connection", "", None))
        self.close_calls += 1
        if self.fail_connection_close:
            raise RuntimeError(f"close leaked {self.adapter_detail}")

    def cancel_safe(self, *, timeout: float = 30.0) -> None:
        self.transcript.append(("cancel", str(timeout), None))
        self.cancel_calls += 1


class CancelAfter:
    def __init__(self, checks: int):
        self.remaining = checks

    def is_cancelled(self) -> bool:
        self.remaining -= 1
        return self.remaining <= 0


class SequenceClock:
    def __init__(self, values: Sequence[float]):
        self.values = list(values)

    def __call__(self) -> float:
        return self.values.pop(0) if self.values else 10_000.0


def connector_config(contract: SourceContract) -> SourceConnectorConfig:
    runtime = RuntimeConfig(
        source_environment=contract.required_source_environment or "development-source",
        expected_database="brerc_source_test",
        expected_role="brerc_extract",
        batch_size=100,
        connect_timeout_seconds=5,
        lock_timeout_ms=1_000,
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
            _resolved_parameters=(
                ("host", "db.example.test"),
                ("port", 5432),
                ("dbname", "brerc_source_test"),
                ("user", "brerc_extract"),
                ("passfile", "/controlled/pgpass"),
                ("sslrootcert", "/controlled/ca.pem"),
                ("sslmode", "verify-full"),
                ("application_name", "brerc-dashboard-source-connector"),
                ("connect_timeout", runtime.connect_timeout_seconds),
            ),
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


class TestConnectorSuccess(unittest.TestCase):
    def test_one_snapshot_is_validated_before_batched_rows_and_always_rolled_back(self):
        contract = approved_contract()
        connection = FakeConnection(
            row_batches=[[source_row("1.00"), source_row("2.00")], [source_row("3.00")], []]
        )
        connector = test_connector(
            connector_config(contract), connection_factory=lambda _: connection
        )
        result = connector.extract_initial(
            source_contract=contract,
            columns=VIEW_COLUMNS,
            policy=approved_policy(),
        )

        self.assertIsInstance(result, ValidatedSourceRun)
        records, report = result
        self.assertEqual(report.rows_in, 3)
        self.assertEqual(len(records), 3)
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)
        self.assertEqual(connection.row_cursor.fetchmany_calls, [100, 100, 100])

        statements = [entry[1] for entry in connection.transcript if entry[0].startswith("execute")]
        self.assertEqual(CATALOG_CAPTURE_SQL.count("JOIN pg_catalog.pg_namespace"), 1)
        self.assertEqual(statements[0], BEGIN_SQL)
        for statement in FIXED_SESSION_SQL:
            self.assertLess(statements.index(statement), statements.index(SESSION_VERIFY_SQL))
        lock_index = next(i for i, value in enumerate(statements) if value.startswith("LOCK TABLE"))
        self.assertLess(lock_index, statements.index(SESSION_VERIFY_SQL))
        self.assertLess(lock_index, statements.index(CATALOG_CAPTURE_SQL))
        self.assertFalse(any(value.startswith("SELECT") for value in statements[:lock_index]))
        row_query_index = next(
            i for i, value in enumerate(statements) if value.startswith('SELECT "unique_no"')
        )
        self.assertLess(statements.index(CATALOG_CAPTURE_SQL), row_query_index)
        self.assertIn('FROM "dashboard"."main_data_dash"', statements[row_query_index])
        self.assertIn('ORDER BY "unique_no" ASC NULLS FIRST', statements[row_query_index])
        self.assertFalse(any(entry[1] == "COMMIT" for entry in connection.transcript))

    def test_unlisted_taxon_is_withheld_by_the_concrete_extraction_path(self):
        contract = approved_contract()
        unlisted = source_row() | {
            "species_no": "UNLISTED-1",
            "scientific_name": "Synthetic unlisted species",
        }
        connection = FakeConnection(row_batches=[[unlisted], []])
        records, report = test_connector(
            connector_config(contract),
            connection_factory=lambda _: connection,
        ).extract_initial(
            source_contract=contract,
            columns=VIEW_COLUMNS,
            policy=approved_policy(),
        )

        self.assertEqual(records, [])
        self.assertEqual(report.rows_in, 1)
        self.assertEqual(report.withheld["species-not-permitted"], 1)

    def test_zero_rows_still_validate_the_cursor_header(self):
        contract = approved_contract()
        connection = FakeConnection(row_batches=[[]])
        result = test_connector(
            connector_config(contract), connection_factory=lambda _: connection
        ).extract_initial(
            source_contract=contract,
            columns=VIEW_COLUMNS,
            policy=approved_policy(),
        )
        _, report = result
        self.assertEqual(report.rows_in, 0)
        self.assertEqual(connection.row_cursor.fetchmany_calls, [100])

    def test_preflight_reads_no_source_row_and_reports_current_contract_not_ready(self):
        connection = FakeConnection(row_batches=[[source_row()]])
        report = test_connector(
            connector_config(BRERC_MAIN_DATA_DASH),
            connection_factory=lambda _: connection,
        ).preflight(
            source_contract=BRERC_MAIN_DATA_DASH,
            columns=VIEW_COLUMNS,
        )
        self.assertFalse(report.release_ready)
        self.assertEqual(report.confirmed_columns, 39)
        self.assertEqual(report.result_columns, PROJECTION)
        self.assertEqual(connection.row_cursor.fetchmany_calls, [])
        row_statements = [entry[1] for entry in connection.transcript if entry[0] == "execute_rows"]
        self.assertEqual(len(row_statements), 1)
        self.assertTrue(row_statements[0].endswith(" LIMIT 0"))
        self.assertNotIn("ORDER BY", row_statements[0])
        statements = [entry[1] for entry in connection.transcript if entry[0].startswith("execute")]
        lock_index = next(i for i, value in enumerate(statements) if value.startswith("LOCK TABLE"))
        self.assertFalse(any(value.startswith("SELECT") for value in statements[:lock_index]))
        self.assertLess(lock_index, statements.index(SESSION_VERIFY_SQL))
        self.assertLess(lock_index, statements.index(CATALOG_CAPTURE_SQL))
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)
        rendered = repr(report)
        self.assertNotIn("SELECT synthetic_reviewed_source", rendered)
        self.assertNotIn("brerc_source_test", rendered)
        self.assertNotIn("brerc_extract", rendered)


class TestPrivateSafeSnapshot(unittest.TestCase):
    def test_only_safe_bounded_batches_and_structural_evidence_escape(self):
        contract = approved_contract()
        config = connector_config(contract)
        connection = FakeConnection(
            row_batches=[
                [source_row("1.00"), source_row("2.00")],
                [source_row("3.00") | {"sensitive": "Yes"}],
                [],
            ]
        )
        connector = TrustedPostgreSQLSourceConnector.from_config(config)
        with patch(
            "brerc_source.postgres._default_connection_factory",
            return_value=connection,
        ):
            stream = connector._open_safe_initial_snapshot(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
                reconciliation_secret=b"reconciliation-secret-for-tests-32bytes",
                dictionary=CONNECTOR_DICTIONARY,
            )
            with stream as snapshot:
                batches = list(snapshot)
                evidence = snapshot.evidence

        self.assertEqual([len(batch) for batch in batches], [2, 1])
        self.assertEqual(evidence.rows_seen, 3)
        self.assertEqual(evidence.records_eligible_before_suppression, 3)
        self.assertEqual(
            evidence.observed_species_dictionary_sha256,
            CONNECTOR_DICTIONARY.digest(),
        )
        self.assertEqual(evidence.sensitivity_buckets, (("no", 2), ("yes", 1)))
        self.assertEqual(connection.row_cursor.fetchmany_calls, [100, 100, 100])
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)
        rendered = repr((batches, evidence))
        for private in ("1.00", "2.00", "3.00", "Yes"):
            self.assertNotIn(private, rendered)
        self.assertNotIn("ST587721", repr(batches[1]))
        self.assertEqual(batches[1][0].record.grid_ref, "ST5872")

    def test_short_reconciliation_secret_fails_before_a_socket(self):
        contract = approved_contract()
        calls = 0

        def factory(_: object) -> FakeConnection:
            nonlocal calls
            calls += 1
            return FakeConnection(row_batches=[])

        connector = TrustedPostgreSQLSourceConnector.from_config(connector_config(contract))
        with (
            patch(
                "brerc_source.postgres._default_connection_factory",
                side_effect=factory,
            ),
            self.assertRaises(SourceConfigurationError),
        ):
            connector._open_safe_initial_snapshot(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
                reconciliation_secret=b"short",
                dictionary=CONNECTOR_DICTIONARY,
            )
        self.assertEqual(calls, 0)

    def test_missing_or_mismatched_dictionary_fails_before_a_socket(self):
        contract = approved_contract()
        calls = 0

        def factory(_: object) -> FakeConnection:
            nonlocal calls
            calls += 1
            return FakeConnection(row_batches=[])

        connector = TrustedPostgreSQLSourceConnector.from_config(connector_config(contract))
        mismatched = SpeciesDictionary.from_rows(
            [{"SPECIES_NO": "other", "SCIENTIFIC": "Other species"}]
        )
        for dictionary in (None, mismatched):
            with (
                self.subTest(dictionary=dictionary is not None),
                patch(
                    "brerc_source.postgres._default_connection_factory",
                    side_effect=factory,
                ),
                self.assertRaises(InvalidPolicy),
            ):
                connector._open_safe_initial_snapshot(
                    source_contract=contract,
                    columns=VIEW_COLUMNS,
                    policy=approved_policy(),
                    reconciliation_secret=b"reconciliation-secret-for-tests-32bytes",
                    dictionary=dictionary,
                )
        self.assertEqual(calls, 0)

    def test_early_consumer_failure_still_rolls_back_and_closes_source(self):
        contract = approved_contract()
        connection = FakeConnection(row_batches=[[source_row()], []])
        connector = TrustedPostgreSQLSourceConnector.from_config(connector_config(contract))
        with patch(
            "brerc_source.postgres._default_connection_factory",
            return_value=connection,
        ):
            stream = connector._open_safe_initial_snapshot(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
                reconciliation_secret=b"reconciliation-secret-for-tests-32bytes",
                dictionary=CONNECTOR_DICTIONARY,
            )
            with self.assertRaisesRegex(RuntimeError, "target failed"), stream as snapshot:
                next(snapshot)
                raise RuntimeError("target failed")
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)

    def test_source_value_failure_is_sanitised_and_context_free(self):
        contract = approved_contract()
        private_identifier = "PRIVATE-INVALID-IDENTIFIER"
        connection = FakeConnection(row_batches=[[source_row(private_identifier)]])
        connector = TrustedPostgreSQLSourceConnector.from_config(connector_config(contract))
        with (
            patch(
                "brerc_source.postgres._default_connection_factory",
                return_value=connection,
            ),
            self.assertRaises(SourceDatabaseFailed) as raised,
            connector._open_safe_initial_snapshot(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
                reconciliation_secret=b"reconciliation-secret-for-tests-32bytes",
                dictionary=CONNECTOR_DICTIONARY,
            ) as snapshot,
        ):
            next(snapshot)
        self.assertNotIn(private_identifier, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)


class TestFailClosedOrdering(unittest.TestCase):
    def test_unapproved_source_fails_before_connection(self):
        calls = 0

        def factory(_: object) -> FakeConnection:
            nonlocal calls
            calls += 1
            return FakeConnection(row_batches=[])

        connector = test_connector(
            connector_config(BRERC_MAIN_DATA_DASH), connection_factory=factory
        )
        with self.assertRaises(SourceContractError):
            connector.extract_initial(
                source_contract=BRERC_MAIN_DATA_DASH,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertEqual(calls, 0)

    def test_identity_drift_fails_before_a_row_cursor_is_created(self):
        contract = approved_contract()
        connection = FakeConnection(
            row_batches=[[source_row()]],
            catalog=catalog_row(definition="SELECT changed_source"),
        )
        connector = test_connector(
            connector_config(contract), connection_factory=lambda _: connection
        )
        with self.assertRaises(SourceProtocolError) as raised:
            connector.extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertNotIn("changed_source", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(connection.row_cursor)
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)

    def test_observed_catalogue_secrets_do_not_cross_the_library_boundary(self):
        contract = approved_contract()
        observed = catalog_row()
        observed["owner"] = "private-owner-name-must-not-escape"
        connection = FakeConnection(row_batches=[[source_row()]], catalog=observed)
        with self.assertRaises(SourceProtocolError) as raised:
            test_connector(
                connector_config(contract), connection_factory=lambda _: connection
            ).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertNotIn("private-owner-name", str(raised.exception))
        self.assertNotIn("private-owner-name", repr(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(connection.row_cursor)

    def test_catalogue_parser_context_is_removed_at_the_library_boundary(self):
        contract = approved_contract()
        observed = catalog_row()
        del observed["owner"]
        connection = FakeConnection(row_batches=[[source_row()]], catalog=observed)
        with self.assertRaises(SourceProtocolError) as raised:
            test_connector(
                connector_config(contract), connection_factory=lambda _: connection
            ).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(connection.row_cursor)

    def test_wrong_database_or_role_fails_before_catalogue_or_rows(self):
        for change in (
            {"database_name": "lookalike"},
            {"authenticated_role": "startup_role"},
            {"extraction_role": "postgres"},
            {"transaction_isolation": "read committed"},
            {"transaction_read_only": "off"},
            {"tcp_transport": False},
            {"tls_active": False},
        ):
            observed = session_row()
            observed.update(change)
            contract = approved_contract()
            connection = FakeConnection(row_batches=[[source_row()]], session=observed)
            with self.subTest(change=change), self.assertRaises(SourceProtocolError):
                test_connector(
                    connector_config(contract),
                    connection_factory=lambda _, conn=connection: conn,
                ).extract_initial(
                    source_contract=contract,
                    columns=VIEW_COLUMNS,
                    policy=approved_policy(),
                )
            self.assertFalse(
                any(entry[1] == CATALOG_CAPTURE_SQL for entry in connection.transcript)
            )
            self.assertIsNone(connection.row_cursor)

    def test_row_header_drift_fails_before_fetch(self):
        contract = approved_contract()
        connection = FakeConnection(row_batches=[[source_row()]], row_header=PROJECTION[:-1])
        with self.assertRaises(SourceProtocolError) as raised:
            test_connector(
                connector_config(contract), connection_factory=lambda _: connection
            ).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertNotIn("sensitive", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(connection.row_cursor.fetchmany_calls, [])
        self.assertEqual(connection.rollback_calls, 1)

    def test_cancellation_discards_the_connection_and_returns_no_partial_run(self):
        contract = approved_contract()
        connection = FakeConnection(row_batches=[[source_row()], [source_row("2.00")]])
        with self.assertRaises(SourceCancelled):
            test_connector(
                connector_config(contract), connection_factory=lambda _: connection
            ).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
                cancellation=CancelAfter(4),
            )
        self.assertEqual(connection.cancel_calls, 1)
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)

    def test_total_deadline_cancels_and_discards_the_snapshot(self):
        contract = approved_contract()
        config = connector_config(contract)
        config = dataclasses.replace(
            config,
            runtime=dataclasses.replace(config.runtime, total_timeout_seconds=60),
        )
        connection = FakeConnection(row_batches=[[source_row()]])
        with self.assertRaises(SourceTimedOut):
            test_connector(
                config,
                connection_factory=lambda _: connection,
                # Fourteen checks complete through the final empty fetch. Only
                # the post-pipeline check crosses the deadline, proving that a
                # fully transformed candidate is still discarded when late.
                monotonic=SequenceClock((*([0.0] * 14), 61.0)),
            ).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertEqual(connection.cancel_calls, 1)
        self.assertEqual(connection.row_cursor.fetchmany_calls, [100, 100])
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)


class TestRedactionAndConfiguration(unittest.TestCase):
    def test_public_constructor_has_no_evidence_or_clock_injection_hooks(self):
        constructor = inspect.signature(TrustedPostgreSQLSourceConnector)
        factory = inspect.signature(TrustedPostgreSQLSourceConnector.from_config)
        self.assertEqual(tuple(constructor.parameters), ("config",))
        self.assertEqual(tuple(factory.parameters), ("config",))
        for signature in (constructor, factory):
            self.assertNotIn("connection_factory", signature.parameters)
            self.assertNotIn("monotonic", signature.parameters)

    def test_default_factory_checks_service_file_binding_before_driver_import(self):
        config = connector_config(approved_contract())
        with (
            patch.object(
                ConnectionConfig,
                "assert_process_environment",
                side_effect=RuntimeError("/private/service/path-must-not-escape"),
            ),
            patch("brerc_source.postgres.importlib.import_module") as importer,
            self.assertRaises(SourceConfigurationError) as context,
        ):
            _default_connection_factory(config)
        importer.assert_not_called()
        self.assertNotIn("/private/service", str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)

    def test_default_factory_discards_raw_driver_exception_object(self):
        private_detail = "private-driver-dsn-must-not-escape"

        def fail_connect(**_kwargs):
            raise RuntimeError(private_detail)

        modules = (
            SimpleNamespace(connect=fail_connect),
            SimpleNamespace(dict_row=object()),
        )
        with (
            patch.object(ConnectionConfig, "assert_process_environment"),
            patch("brerc_source.postgres.importlib.import_module", side_effect=modules),
            self.assertRaises(SourceConnectionFailed) as context,
        ):
            _default_connection_factory(connector_config(approved_contract()))
        self.assertNotIn(private_detail, str(context.exception))
        self.assertNotIn(private_detail, repr(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)

    def test_any_cleanup_failure_invalidates_an_apparent_success(self):
        contract = approved_contract()
        for failure in ("fail_cursor_close", "fail_rollback", "fail_connection_close"):
            connection = FakeConnection(row_batches=[[]], **{failure: True})
            with self.subTest(failure=failure), self.assertRaises(SourceCleanupFailed):
                test_connector(
                    connector_config(contract), connection_factory=lambda _, item=connection: item
                ).extract_initial(
                    source_contract=contract,
                    columns=VIEW_COLUMNS,
                    policy=approved_policy(),
                )
            operations = [entry[0] for entry in connection.transcript]
            self.assertIn("rollback", operations)
            self.assertIn("close_connection", operations)
            self.assertLess(operations.index("rollback"), operations.index("close_connection"))
            self.assertFalse(any(entry[1] == "COMMIT" for entry in connection.transcript))

    def test_malformed_factory_result_is_sanitised_and_no_rows_escape(self):
        contract = approved_contract()
        with self.assertRaises(SourceDatabaseFailed) as context:
            test_connector(
                connector_config(contract), connection_factory=lambda _: object()
            ).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertIsNone(context.exception.__cause__)

    def test_adapter_exception_does_not_cross_the_boundary(self):
        private_detail = "/controlled/" + "-".join(
            ("private", "adapter", "detail", "must", "not", "escape")
        )
        connection = FakeConnection(
            row_batches=[],
            fail_on="BEGIN TRANSACTION",
            adapter_detail=private_detail,
        )
        contract = approved_contract()
        config = connector_config(contract)
        resolved = tuple(
            (name, private_detail if name == "passfile" else value)
            for name, value in config.connection._resolved_parameters
        )
        config = dataclasses.replace(
            config,
            connection=dataclasses.replace(
                config.connection,
                _resolved_parameters=resolved,
            ),
        )
        with self.assertRaises(SourceDatabaseFailed) as context:
            test_connector(config, connection_factory=lambda _: connection).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertNotIn(private_detail, str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)
        self.assertNotIn(private_detail, repr(config))
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)

    def test_config_contract_mismatch_fails_before_connection(self):
        contract = approved_contract()
        config = dataclasses.replace(connector_config(contract), contract_version="other")
        calls = 0

        def factory(_: object) -> FakeConnection:
            nonlocal calls
            calls += 1
            return FakeConnection(row_batches=[])

        with self.assertRaises(SourceConfigurationError):
            test_connector(config, connection_factory=factory).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertEqual(calls, 0)

    def test_invalid_contract_identifier_fails_before_connection(self):
        contract = dataclasses.replace(
            BRERC_MAIN_DATA_DASH,
            name="main-data-dash",
            required_source_environment="synthetic-approved-source",
            release_blockers=(),
        )
        config = dataclasses.replace(
            connector_config(contract),
            source=SourceLocation(
                engine="postgresql",
                schema=contract.schema,
                object=contract.name,
                object_type=contract.object_type,
                strict_schema=True,
            ),
        )
        calls = 0

        def factory(_: object) -> FakeConnection:
            nonlocal calls
            calls += 1
            return FakeConnection(row_batches=[])

        with self.assertRaises(SourceConfigurationError):
            test_connector(config, connection_factory=factory).extract_initial(
                source_contract=contract,
                columns=VIEW_COLUMNS,
                policy=approved_policy(),
            )
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)

"""Real-driver integration against an entirely synthetic PostgreSQL 16 service.

CI enables this module with ``BRERC_PG_INTEGRATION=1`` after provisioning TLS,
the exact 39-column view shape and non-privileged roles. No BRERC record or
credential is used here.
"""

from __future__ import annotations

import dataclasses
import os
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path

from brerc_source import (
    BRERC_SOURCE_APPLICATION_NAME,
    SourceConnectorConfig,
    SourceProtocolError,
    TrustedPostgreSQLSourceConnector,
    load_source_config,
)
from brerc_source.postgres import (
    BEGIN_SQL,
    CATALOG_CAPTURE_SQL,
    CATALOG_HEADER,
    FIXED_SESSION_SQL,
    _capture_document,
)
from connector_tests.test_postgres_connector import (
    CONNECTOR_DICTIONARY,
    VIEW_COLUMNS,
    approved_policy,
)
from etl.source_contract import BRERC_MAIN_DATA_DASH
from etl.view_identity import ViewCaptureEvidence, ViewDefinitionApproval

ENABLED = os.environ.get("BRERC_PG_INTEGRATION") == "1"
API_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(ENABLED, "requires the synthetic PostgreSQL 16 TLS service")
class TestPostgreSQL16TLSIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg
        from psycopg.rows import dict_row

        cls.psycopg = psycopg
        cls.dict_row = dict_row
        cls.temporary_directory = tempfile.TemporaryDirectory()
        template = (API_ROOT / "configuration.example.yaml").read_text(encoding="utf-8")
        configured = (
            template.replace("brerc-production", "synthetic-postgres16")
            .replace("REPLACE_WITH_BRERC_DATABASE_NAME", "brerc_connector")
            .replace("REPLACE_WITH_READ_ONLY_ROLE_NAME", "brerc_extract")
        )
        config_path = Path(cls.temporary_directory.name, "configuration.yaml")
        config_path.write_text(configured, encoding="utf-8")
        cls.service_config = load_source_config(config_path)
        startup_environment = dict(os.environ)
        startup_environment["BRERC_SOURCE_SERVICE"] = "synthetic_startup"
        startup_environment["BRERC_SOURCE_PASSFILE"] = os.environ["BRERC_STARTUP_PASSFILE"]
        cls.startup_role_config = load_source_config(
            config_path,
            environ=startup_environment,
        )
        service_block = """connection:
  mode: service
  service_env: BRERC_SOURCE_SERVICE
  # libpq/Psycopg reads this standard process variable directly; it is not a
  # connection keyword. Its value remains a deployment-controlled absolute path.
  service_file_env: PGSERVICEFILE
  passfile_env: BRERC_SOURCE_PASSFILE
  sslrootcert_env: BRERC_SOURCE_SSLROOTCERT
  sslmode: verify-full"""
        direct_block = """connection:
  mode: direct
  host_env: BRERC_SOURCE_HOST
  port_env: BRERC_SOURCE_PORT
  database_env: BRERC_SOURCE_DATABASE
  user_env: BRERC_SOURCE_USER
  passfile_env: BRERC_SOURCE_PASSFILE
  sslrootcert_env: BRERC_SOURCE_SSLROOTCERT
  sslmode: verify-full"""
        direct_document = configured.replace(service_block, direct_block)
        if direct_document == configured:
            raise AssertionError("integration template no longer has the reviewed service block")
        direct_path = Path(cls.temporary_directory.name, "configuration-direct.yaml")
        direct_path.write_text(direct_document, encoding="utf-8")
        cls.direct_config = load_source_config(direct_path)
        evidence = cls._capture_live_evidence(cls.service_config)
        observation = evidence.observation
        version = "synthetic-postgres16-approved-v1"
        approval = ViewDefinitionApproval(
            source_version=version,
            source_environment="synthetic-postgres16",
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
            approved_by="Synthetic CI data owner",
            approver_role="Synthetic integration test owner",
            approver_organisation="BRERC",
            captured_at_utc=evidence.captured_at_utc,
            approved_on=date.today().isoformat(),
            evidence_reference="SYNTHETIC-POSTGRES16-CI-ONLY",
        )
        cls.approved_contract = dataclasses.replace(
            BRERC_MAIN_DATA_DASH,
            version=version,
            required_source_environment="synthetic-postgres16",
            view_approval=approval,
            release_blockers=(),
        )
        cls.approved_service_config = dataclasses.replace(
            cls.service_config,
            contract_version=version,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    @classmethod
    def _capture_live_evidence(cls, config: SourceConnectorConfig) -> ViewCaptureEvidence:
        connection = cls.psycopg.connect(
            autocommit=True,
            row_factory=cls.dict_row,
            **config.connection.parameters(),
        )
        cursor = connection.cursor()
        try:
            # The real public connector enforces this independently. This
            # bootstrap capture must also refuse a non-TLS source.
            cursor.execute(
                """
                SELECT COALESCE(
                    (
                        SELECT ssl
                        FROM pg_catalog.pg_stat_ssl
                        WHERE pid = pg_catalog.pg_backend_pid()
                    ),
                    false
                ) AS tls_active
                """
            )
            tls_row = cursor.fetchone()
            if tls_row is None or tls_row["tls_active"] is not True:
                raise AssertionError("synthetic approval capture did not use TLS")
            cursor.execute(BEGIN_SQL)
            for statement in FIXED_SESSION_SQL:
                cursor.execute(statement)
            cursor.execute('LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE')
            cursor.execute(
                CATALOG_CAPTURE_SQL,
                ("dashboard", "main_data_dash", "dashboard", "main_data_dash"),
            )
            if tuple(item.name for item in cursor.description) != CATALOG_HEADER:
                raise AssertionError("catalogue capture header differs from the connector contract")
            row = cursor.fetchone()
            if row is None or cursor.fetchone() is not None:
                raise AssertionError("catalogue capture must return exactly one row")
            return ViewCaptureEvidence.from_document(_capture_document(row))
        finally:
            cursor.close()
            connection.rollback()
            connection.close()

    def test_public_service_preflight_overrides_hostile_service_file_and_uses_tls(self):
        report = TrustedPostgreSQLSourceConnector.from_config(self.service_config).preflight(
            source_contract=BRERC_MAIN_DATA_DASH,
            columns=VIEW_COLUMNS,
        )
        self.assertFalse(report.release_ready)
        self.assertEqual(report.confirmed_columns, 39)
        self.assertEqual(report.result_columns, self.service_config.projection)

        with self.psycopg.connect(**self.service_config.connection.parameters()) as connection:
            tls_active, application_name, server_version = connection.execute(
                """
                SELECT
                    ssl,
                    current_setting('application_name'),
                    current_setting('server_version_num')::integer
                FROM pg_catalog.pg_stat_ssl
                WHERE pid = pg_catalog.pg_backend_pid()
                """
            ).fetchone()
        self.assertTrue(tls_active)
        self.assertEqual(application_name, BRERC_SOURCE_APPLICATION_NAME)
        self.assertGreaterEqual(server_version, 160000)
        self.assertLess(server_version, 170000)

    def test_service_profile_cannot_hide_an_unapproved_authenticated_role(self):
        with self.assertRaises(SourceProtocolError) as raised:
            TrustedPostgreSQLSourceConnector.from_config(self.startup_role_config).preflight(
                source_contract=BRERC_MAIN_DATA_DASH,
                columns=VIEW_COLUMNS,
            )
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_public_direct_preflight_and_approved_named_cursor_extraction(self):
        direct_report = TrustedPostgreSQLSourceConnector.from_config(self.direct_config).preflight(
            source_contract=BRERC_MAIN_DATA_DASH,
            columns=VIEW_COLUMNS,
        )
        self.assertEqual(direct_report.confirmed_columns, 39)

        run = TrustedPostgreSQLSourceConnector.from_config(
            self.approved_service_config
        ).extract_initial(
            source_contract=self.approved_contract,
            columns=VIEW_COLUMNS,
            policy=approved_policy(),
            dictionary=CONNECTOR_DICTIONARY,
        )
        records, report = run
        self.assertEqual(report.rows_in, 3)
        self.assertEqual(len(records), 3)
        self.assertEqual(report.records_public, 3)
        self.assertEqual(report.rows_withheld, 0)
        self.assertEqual({record.species_id for record in records}, {"SYNTH-1", "SYNTH-2"})
        sensitive = next(record for record in records if record.species_id == "SYNTH-2")
        self.assertGreaterEqual(sensitive.precision_metres, 1_000)
        rendered = repr(records) + repr(report)
        self.assertNotIn("PRIVATE-SYNTHETIC-PLACE", rendered)
        self.assertNotIn("PRIVATE-SYNTHETIC-COMMENT", rendered)

    def test_extraction_role_is_read_only_but_has_whole_view_visibility(self):
        with self.psycopg.connect(**self.direct_config.connection.parameters()) as connection:
            self.assertEqual(connection.execute("SHOW transaction_read_only").fetchone()[0], "on")
            count = connection.execute(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'dashboard' AND table_name = 'main_data_dash'
                """
            ).fetchone()[0]
            self.assertEqual(count, 39)
            write_privileges = connection.execute(
                """
                SELECT has_table_privilege(
                    current_user,
                    'dashboard.main_data_dash',
                    'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                )
                """
            ).fetchone()[0]
            self.assertFalse(write_privileges)
            role = connection.execute(
                """
                SELECT
                    rolsuper, rolcreatedb, rolcreaterole, rolinherit,
                    rolreplication, rolbypassrls
                FROM pg_catalog.pg_roles
                WHERE rolname = current_user
                """
            ).fetchone()
            self.assertEqual(role, (False, False, False, False, False, False))
            # Either exception proves the role cannot write. With no explicit
            # transaction PostgreSQL may reject the role's missing UPDATE grant
            # before it evaluates transaction read-only state.
            with self.assertRaises(
                (
                    self.psycopg.errors.InsufficientPrivilege,
                    self.psycopg.errors.ReadOnlySqlTransaction,
                )
            ):
                connection.execute("UPDATE dashboard.main_data_dash SET common_name = 'must fail'")

    def test_column_only_role_cannot_satisfy_the_trusted_capture(self):
        parameters = dict(self.direct_config.connection.parameters())
        parameters["user"] = "brerc_column_reader"
        parameters["passfile"] = os.environ["BRERC_COLUMN_PASSFILE"]

        connection = self.psycopg.connect(autocommit=True, **parameters)
        try:
            visible = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'dashboard' AND table_name = 'main_data_dash'
                ORDER BY ordinal_position
                """
            ).fetchall()
            # information_schema returns catalogue order while projection uses
            # pipeline mapping order; security depends on exact membership.
            self.assertEqual(
                sorted(row[0] for row in visible),
                sorted(self.service_config.projection),
            )

            connection.execute(BEGIN_SQL)
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                connection.execute('LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE')
            connection.rollback()
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT easting FROM dashboard.main_data_dash LIMIT 1")
        finally:
            connection.rollback()
            connection.close()

    def test_repeatable_read_snapshot_is_stable_and_view_ddl_waits_for_lock(self):
        reader = self.psycopg.connect(autocommit=True, **self.direct_config.connection.parameters())
        admin_parameters = dict(self.direct_config.connection.parameters())
        admin_parameters.update(user="postgres", password=os.environ["BRERC_PG_ADMIN_SECRET"])
        admin_parameters.pop("passfile")
        admin = self.psycopg.connect(autocommit=True, **admin_parameters)
        ddl_started = threading.Event()
        ddl_finished = threading.Event()
        ddl_error: list[BaseException] = []

        def replace_view() -> None:
            try:
                ddl_started.set()
                admin.execute(
                    """
                    CREATE OR REPLACE VIEW dashboard.main_data_dash AS
                    SELECT * FROM dashboard.synthetic_records
                    """
                )
            except BaseException as exc:  # captured and asserted in the main thread
                ddl_error.append(exc)
            finally:
                ddl_finished.set()

        try:
            reader.execute(BEGIN_SQL)
            reader.execute('LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE')
            first_count = reader.execute(
                "SELECT count(*) FROM dashboard.main_data_dash"
            ).fetchone()[0]
            admin.execute(
                """
                INSERT INTO dashboard.synthetic_records (
                    scientific_name, grid_ref, species_no, year_end,
                    unique_no, licence, sensitive
                ) VALUES (
                    'Synthetic concurrent species', 'ST587721', 'SYNTH-4',
                    '2024', 4.00, 'y', 'No'
                )
                """
            )
            snapshot_count = reader.execute(
                "SELECT count(*) FROM dashboard.main_data_dash"
            ).fetchone()[0]
            self.assertEqual((first_count, snapshot_count), (3, 3))
            worker = threading.Thread(target=replace_view, daemon=True)
            worker.start()
            self.assertTrue(ddl_started.wait(timeout=2))
            time.sleep(0.25)
            self.assertFalse(ddl_finished.is_set(), "view DDL bypassed ACCESS SHARE")
            reader.rollback()
            self.assertTrue(ddl_finished.wait(timeout=5))
            worker.join(timeout=1)
            self.assertEqual(ddl_error, [])
            admin.execute("DELETE FROM dashboard.synthetic_records WHERE unique_no = 4.00")
        finally:
            reader.rollback()
            reader.close()
            admin.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)

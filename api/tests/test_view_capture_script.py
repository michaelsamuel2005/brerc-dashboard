"""Integration tests for the BRERC view-capture handoff tooling."""

import dataclasses
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from etl.source_contract import BRERC_MAIN_DATA_DASH, SourceContractError
from etl.view_identity import (
    EXPECTED_CAPTURE_SESSION,
    ViewDefinitionApproval,
    ViewIdentityError,
)
from scripts.prepare_view_approval import read_json, render_pending, validate_capture
from scripts.verify_view_approval import main as verify_approval_main


def full_capture() -> dict[str, object]:
    definition = 'SELECT "md"."scientific_name"\nFROM "main_data"."records" AS "md"'
    columns = []
    for ordinal, column in enumerate(BRERC_MAIN_DATA_DASH.columns, start=1):
        udt_name = {
            "character varying": "varchar",
            "date": "date",
            "numeric": "numeric",
            "text": "text",
        }[column.data_type]
        columns.append(
            {
                "ordinal_position": ordinal,
                "column_name": column.name,
                "data_type": column.data_type,
                "udt_schema": "pg_catalog",
                "udt_name": udt_name,
                "character_maximum_length": column.character_maximum_length,
                "numeric_precision": column.numeric_precision,
                "numeric_scale": column.numeric_scale,
                "is_nullable": "YES",
                "collation_schema": None,
                "collation_name": None,
            }
        )
    return {
        "artifact_format": "brerc-view-capture/v1",
        "captured_at_utc": "2026-08-10T12:00:00.000000Z",
        "postgres": {
            "database": "never_emit_this_database",
            "server_version": "16.4",
            "server_version_num": 160004,
            "server_major": 16,
            "server_encoding": "UTF8",
            "captured_by_database_role": "never_emit_this_role",
        },
        "session": dict(EXPECTED_CAPTURE_SESSION),
        "object": {
            "schema": "dashboard",
            "name": "main_data_dash",
            "qualified_name": "dashboard.main_data_dash",
            "relation_oid": 12345,
            "relkind": "v",
            "relpersistence": "p",
            "owner": "postgres",
            "reloptions": [],
        },
        "view_definition": definition,
        "view_definition_utf8_hex": definition.encode("utf-8").hex(),
        "columns": columns,
    }


def completed_approval_document() -> dict[str, object]:
    document = json.loads(render_pending(validate_capture(full_capture())))
    document["status"] = "approved"
    document["sourceVersion"] = "BRERC-main-data-dash-v1"
    document["sourceEnvironment"] = "BRERC production"
    document["approval"] = {
        "approvedBy": "Authorised BRERC owner",
        "approverRole": "BRERC data owner",
        "approverOrganisation": "BRERC",
        "approvedOn": date.today().isoformat(),
        "reviewExpiresOn": (date.today() + timedelta(days=365)).isoformat(),
        "evidenceReference": "BRERC-APPROVAL-REFERENCE",
    }
    return document


class TestPrepareApproval(unittest.TestCase):
    def test_full_capture_matches_the_reviewed_39_column_contract(self):
        evidence = validate_capture(full_capture())
        self.assertEqual(len(evidence.columns_document), 39)
        self.assertEqual(evidence.columns_sha256, BRERC_MAIN_DATA_DASH.columns_sha256())

    def test_pending_handoff_contains_digests_but_no_raw_internal_context(self):
        evidence = validate_capture(full_capture())
        rendered = render_pending(evidence)
        document = json.loads(rendered)
        self.assertEqual(document["status"], "pending-brerc-approval")
        self.assertEqual(
            document["clientReferenceDocumentSha256"],
            BRERC_MAIN_DATA_DASH.client_reference_document_sha256,
        )
        self.assertNotIn("never_emit_this_database", rendered)
        self.assertNotIn("never_emit_this_role", rendered)
        self.assertNotIn(full_capture()["view_definition"], rendered)

    def test_pending_handoff_becomes_valid_only_after_named_brerc_fields_are_completed(self):
        document = completed_approval_document()
        approval = ViewDefinitionApproval.from_document(document)
        contract = dataclasses.replace(
            BRERC_MAIN_DATA_DASH,
            required_source_environment="BRERC production",
            view_approval=approval,
        )
        self.assertEqual(contract.view_approval, approval)
        self.assertFalse(contract.is_release_ready())  # other implementation blockers remain

    def test_changed_column_type_or_added_column_is_rejected(self):
        wrong_type = full_capture()
        wrong_type["columns"][28]["data_type"] = "text"
        extra = full_capture()
        extra["columns"].append(dict(extra["columns"][-1], ordinal_position=40))
        for document in (wrong_type, extra):
            with (
                self.subTest(document=document),
                self.assertRaises((SourceContractError, ViewIdentityError)),
            ):
                validate_capture(document)

    def test_evidence_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            for contents in ('{"status":"pending","status":"approved"}', '{"x":NaN}'):
                path.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaises(ViewIdentityError):
                    read_json(path)

    def test_cli_verifies_the_exact_capture_and_independent_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture_path = root / "source.brerc-view-capture.json"
            approval_path = root / "source.brerc-view-approval.json"
            capture_path.write_text(json.dumps(full_capture()), encoding="utf-8")
            approval_path.write_text(
                json.dumps(completed_approval_document()),
                encoding="utf-8",
            )
            arguments = [
                "verify_view_approval.py",
                str(approval_path),
                "--expected-source-environment",
                "BRERC production",
                "--capture",
                str(capture_path),
            ]
            with (
                mock.patch.object(sys, "argv", arguments),
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(verify_approval_main(), 0)
            self.assertIn("OK: approval envelope", stdout.getvalue())

            wrong_environment = list(arguments)
            wrong_environment[3] = "local development"
            with (
                mock.patch.object(sys, "argv", wrong_environment),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                self.assertEqual(verify_approval_main(), 1)
            self.assertIn("sourceEnvironment", stderr.getvalue())

    def test_cli_rejects_a_different_raw_capture_even_when_identity_is_same(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture_path = root / "source.brerc-view-capture.json"
            approval_path = root / "source.brerc-view-approval.json"
            changed_capture = full_capture()
            changed_capture["captured_at_utc"] = "2026-08-10T12:00:01.000000Z"
            capture_path.write_text(json.dumps(changed_capture), encoding="utf-8")
            approval_path.write_text(
                json.dumps(completed_approval_document()),
                encoding="utf-8",
            )
            arguments = [
                "verify_view_approval.py",
                str(approval_path),
                "--expected-source-environment",
                "BRERC production",
                "--capture",
                str(capture_path),
            ]
            with (
                mock.patch.object(sys, "argv", arguments),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                self.assertEqual(verify_approval_main(), 1)
            self.assertIn("capture", stderr.getvalue())


class TestCaptureSql(unittest.TestCase):
    def test_query_is_read_only_snapshot_scoped_and_never_reads_view_rows(self):
        path = Path(__file__).resolve().parents[1] / "sql" / "capture_main_data_dash_view.sql"
        sql = path.read_text(encoding="utf-8")
        self.assertIn("REPEATABLE READ READ ONLY", sql)
        self.assertIn("SET LOCAL search_path = pg_catalog", sql)
        self.assertIn("SET LOCAL quote_all_identifiers = on", sql)
        self.assertIn("SET LOCAL standard_conforming_strings = on", sql)
        self.assertIn("SET LOCAL DateStyle = 'ISO, YMD'", sql)
        self.assertIn("SET LOCAL TimeZone = 'UTC'", sql)
        self.assertIn("SET LOCAL extra_float_digits = 3", sql)
        self.assertIn("SET LOCAL lock_timeout = '5s'", sql)
        self.assertIn(
            'LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE',
            sql,
        )
        self.assertIn("pg_catalog.pg_get_viewdef(t.oid, false)", sql)
        self.assertIn("encode(convert_to(d.sql_text, 'UTF8'), 'hex')", sql)
        self.assertIn("ROLLBACK", sql)
        self.assertNotIn("FROM dashboard.main_data_dash", sql)
        self.assertNotIn("SELECT *", sql)

    def test_capture_locks_the_view_before_reading_catalogue_identity(self):
        path = Path(__file__).resolve().parents[1] / "sql" / "capture_main_data_dash_view.sql"
        sql = path.read_text(encoding="utf-8")
        timeout = sql.index("SET LOCAL lock_timeout = '5s'")
        lock = sql.index('LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE')
        target = sql.index("WITH target AS MATERIALIZED")
        definition = sql.index("pg_catalog.pg_get_viewdef(t.oid, false)")
        columns = sql.index("FROM information_schema.columns")
        rollback = sql.index("ROLLBACK")

        self.assertLess(timeout, lock)
        self.assertLess(lock, target)
        self.assertLess(lock, definition)
        self.assertLess(lock, columns)
        self.assertLess(columns, rollback)

    def test_capture_uses_only_the_read_only_compatible_view_lock(self):
        path = Path(__file__).resolve().parents[1] / "sql" / "capture_main_data_dash_view.sql"
        sql = path.read_text(encoding="utf-8")
        lock_lines = [
            line.strip() for line in sql.splitlines() if line.lstrip().startswith("LOCK ")
        ]
        self.assertEqual(
            lock_lines,
            ['LOCK TABLE "dashboard"."main_data_dash" IN ACCESS SHARE MODE;'],
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)

"""The operator CLI exposes only safe preflight output."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from dataclasses import dataclass
from unittest import mock

from brerc_source.cli import main
from brerc_source.config import SourceConfigError
from brerc_source.errors import SourceDatabaseFailed


@dataclass(frozen=True)
class FakeReport:
    contract_version: str = "contract-v1"
    contract_sha256: str = "a" * 64
    observed_definition_sha256: str = "b" * 64
    observed_identity_sha256: str = "c" * 64
    confirmed_columns: int = 39
    result_columns: tuple[str, ...] = ("unique_no", "sensitive")
    release_ready: bool = False


class FakeConfig:
    column_map = object()


class FakeConnector:
    def __init__(self, result: object):
        self.result = result

    def preflight(self, **_kwargs: object) -> object:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def run_cli(connector_result: object):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        mock.patch("brerc_source.cli.load_source_config", return_value=FakeConfig()),
        mock.patch(
            "brerc_source.cli.TrustedPostgreSQLSourceConnector.from_config",
            return_value=FakeConnector(connector_result),
        ),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        code = main(["preflight", "--config", "/controlled/configuration.yaml"])
    return code, stdout.getvalue(), stderr.getvalue()


class TestPreflightCli(unittest.TestCase):
    def test_success_is_fixed_json_and_does_not_claim_release_readiness(self) -> None:
        code, stdout, stderr = run_cli(FakeReport())
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        document = json.loads(stdout)
        self.assertEqual(
            set(document),
            {
                "status",
                "contractVersion",
                "contractSha256",
                "observedDefinitionSha256",
                "observedIdentitySha256",
                "confirmedColumns",
                "resultColumns",
                "releaseReady",
            },
        )
        self.assertEqual(document["status"], "ok")
        self.assertFalse(document["releaseReady"])

    def test_configuration_and_database_failures_emit_only_stable_codes(self) -> None:
        sensitive_values = (
            "secret-password",
            "internal-db.example",
            "SELECT private_grid_ref",
            "ST000000",
        )
        for failure, expected_code in (
            (SourceDatabaseFailed(), "SOURCE_DATABASE_FAILED"),
            (RuntimeError(" ".join(sensitive_values)), "SOURCE_PREFLIGHT_FAILED"),
        ):
            with self.subTest(failure=failure):
                code, stdout, stderr = run_cli(failure)
                self.assertNotEqual(code, 0)
                self.assertEqual(stdout, "")
                self.assertEqual(json.loads(stderr)["code"], expected_code)
                for value in sensitive_values:
                    self.assertNotIn(value, stderr)

    def test_configuration_parser_text_is_never_echoed(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "brerc_source.cli.load_source_config",
                side_effect=SourceConfigError("postgresql://user:secret@internal/private"),
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(["preflight", "--config", "/controlled/configuration.yaml"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"status": "failed", "code": "SOURCE_CONFIGURATION_INVALID"},
        )
        self.assertNotIn("secret", stderr.getvalue())

    def test_help_has_no_unsafe_connection_or_bypass_options(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(stdout):
            main(["preflight", "--help"])
        self.assertEqual(caught.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--config", help_text)
        for forbidden in ("--dsn", "--password", "--query", "--force", "--skip-contract"):
            self.assertNotIn(forbidden, help_text)

    def test_invalid_arguments_do_not_echo_their_values(self) -> None:
        sensitive_argument = "postgresql://user:" + "secret@internal/private"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            self.assertRaises(SystemExit) as caught,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            main(["preflight", "--dsn", sensitive_argument])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"status": "failed", "code": "SOURCE_CLI_USAGE_INVALID"},
        )
        self.assertNotIn(sensitive_argument, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

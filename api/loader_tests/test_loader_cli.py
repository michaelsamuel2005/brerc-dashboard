"""Safe operator-boundary tests for full-snapshot and incremental release loads."""

from __future__ import annotations

import contextlib
import io
import json
import types
import unittest
from unittest import mock

from brerc_loader.cli import _parser, main
from brerc_loader.errors import (
    LoaderConfigurationError,
    LoaderExecutionFailed,
    LoaderPolicyInvalid,
)
from brerc_loader.models import LoaderRunReport, LoadMode, RunState


class FakeConfig:
    """Opaque stand-in: CLI tests must not need YAML or database credentials."""


def successful_report(
    mode: LoadMode = LoadMode.INITIAL,
    *,
    reused_active_release: bool = False,
) -> LoaderRunReport:
    return LoaderRunReport(
        run_id="11111111-1111-4111-8111-111111111111",
        release_id="22222222-2222-4222-8222-222222222222",
        mode=mode,
        state=RunState.SUCCEEDED,
        source_rows=10,
        public_records=8,
        distribution_cells=3,
        candidate_sha256="a" * 64,
        activated=True,
        reused_active_release=reused_active_release,
    )


def _successful_operation(_config: object, mode: LoadMode) -> LoaderRunReport:
    return successful_report(mode)


def run_command(command: str, operation: object = None):
    if operation is None:
        operation = _successful_operation
    module = types.SimpleNamespace(run_load=operation)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        mock.patch("brerc_loader.cli.load_loader_config", return_value=FakeConfig()),
        mock.patch("brerc_loader.cli._load_coordinator", return_value=module),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        code = main([command, "--config", "/controlled/loader.yaml"])
    return code, stdout.getvalue(), stderr.getvalue()


def run_initial(operation: object = None):
    return run_command("initial", operation)


def run_refresh(operation: object = None):
    return run_command("refresh", operation)


class TestInitialCommand(unittest.TestCase):
    def test_success_is_one_fixed_json_document(self) -> None:
        code, stdout, stderr = run_initial()
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("\n"), 1)
        self.assertEqual(
            json.loads(stdout),
            {
                "status": "ok",
                "mode": "initial",
                "state": "succeeded",
                "runId": "11111111-1111-4111-8111-111111111111",
                "releaseId": "22222222-2222-4222-8222-222222222222",
                "sourceRows": 10,
                "publicRecords": 8,
                "distributionCells": 3,
                "candidateSha256": "a" * 64,
                "activated": True,
                "reusedActiveRelease": False,
            },
        )

    def test_coordinator_receives_the_explicit_mode_and_config(self) -> None:
        operation = mock.Mock(return_value=successful_report())
        code, _stdout, _stderr = run_initial(operation)
        self.assertEqual(code, 0)
        operation.assert_called_once()
        config, mode = operation.call_args.args
        self.assertIsInstance(config, FakeConfig)
        self.assertIs(mode, LoadMode.INITIAL)

    def test_configuration_coordinator_and_execution_failures_are_fixed_codes(self) -> None:
        cases = (
            (
                LoaderConfigurationError(),
                "LOADER_CONFIGURATION_INVALID",
                2,
                "configuration",
            ),
            (ImportError("private adapter path"), "LOADER_COORDINATOR_UNAVAILABLE", 3, "import"),
            (
                RuntimeError("SELECT exact_grid_ref FROM private"),
                "LOADER_EXECUTION_FAILED",
                3,
                "run",
            ),
            (LoaderExecutionFailed(), "LOADER_EXECUTION_FAILED", 3, "run"),
            (LoaderPolicyInvalid(), "LOADER_POLICY_INVALID", 3, "run"),
        )
        for failure, expected_code, expected_exit, stage in cases:
            stdout = io.StringIO()
            stderr = io.StringIO()
            patches = [
                mock.patch("brerc_loader.cli.load_loader_config", return_value=FakeConfig()),
                mock.patch(
                    "brerc_loader.cli._load_coordinator",
                    return_value=types.SimpleNamespace(
                        run_load=mock.Mock(side_effect=failure) if stage == "run" else None
                    ),
                ),
            ]
            if stage == "configuration":
                patches[0] = mock.patch(
                    "brerc_loader.cli.load_loader_config",
                    side_effect=failure,
                )
            elif stage == "import":
                patches[1] = mock.patch(
                    "brerc_loader.cli._load_coordinator",
                    side_effect=failure,
                )
            with (
                patches[0],
                patches[1],
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = main(["initial", "--config", "/private/loader.yaml"])
            with self.subTest(expected_code=expected_code, stage=stage):
                self.assertEqual(code, expected_exit)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(
                    json.loads(stderr.getvalue()),
                    {"status": "failed", "code": expected_code},
                )
                for sensitive_fragment in ("private", "adapter", "SELECT", "grid_ref"):
                    self.assertNotIn(sensitive_fragment, stderr.getvalue())

    def test_unexpected_config_exception_is_also_redacted(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "brerc_loader.cli.load_loader_config",
                side_effect=RuntimeError("postgresql://user:secret@internal/private"),
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(["initial", "--config", "/private/loader.yaml"])
        self.assertEqual(code, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"status": "failed", "code": "LOADER_EXECUTION_FAILED"},
        )
        self.assertNotIn("secret", stderr.getvalue())

    def test_invalid_or_mismatched_artifact_stops_before_coordinator_import(self) -> None:
        coordinator_loader = mock.Mock(side_effect=AssertionError("must not import DB code"))
        stderr = io.StringIO()
        with (
            mock.patch(
                "brerc_loader.cli.load_loader_config",
                side_effect=LoaderConfigurationError(),
            ),
            mock.patch("brerc_loader.cli._load_coordinator", coordinator_loader),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(["initial", "--config", "/private/loader.yaml"])
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"status": "failed", "code": "LOADER_CONFIGURATION_INVALID"},
        )
        coordinator_loader.assert_not_called()

    def test_wrong_coordinator_report_type_or_mode_cannot_claim_success(self) -> None:
        reports = (
            object(),
            successful_report(LoadMode.INCREMENTAL),
        )
        for report in reports:
            with self.subTest(report=type(report).__name__):
                code, stdout, stderr = run_initial(mock.Mock(return_value=report))
                self.assertEqual(code, 3)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    json.loads(stderr),
                    {"status": "failed", "code": "LOADER_EXECUTION_FAILED"},
                )


class TestRefreshCommand(unittest.TestCase):
    def test_success_is_one_fixed_refresh_json_document(self) -> None:
        code, stdout, stderr = run_refresh()
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("\n"), 1)
        self.assertEqual(
            json.loads(stdout),
            {
                "status": "ok",
                "mode": "refresh",
                "state": "succeeded",
                "runId": "11111111-1111-4111-8111-111111111111",
                "releaseId": "22222222-2222-4222-8222-222222222222",
                "sourceRows": 10,
                "publicRecords": 8,
                "distributionCells": 3,
                "candidateSha256": "a" * 64,
                "activated": True,
                "reusedActiveRelease": False,
            },
        )

    def test_no_change_refresh_reports_reused_active_release(self) -> None:
        operation = mock.Mock(
            return_value=successful_report(
                LoadMode.REFRESH,
                reused_active_release=True,
            )
        )
        code, stdout, stderr = run_refresh(operation)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIs(json.loads(stdout)["reusedActiveRelease"], True)

    def test_coordinator_receives_refresh_mode_and_must_return_refresh_report(self) -> None:
        operation = mock.Mock(return_value=successful_report(LoadMode.REFRESH))
        code, _stdout, _stderr = run_refresh(operation)
        self.assertEqual(code, 0)
        config, mode = operation.call_args.args
        self.assertIsInstance(config, FakeConfig)
        self.assertIs(mode, LoadMode.REFRESH)

        code, stdout, stderr = run_refresh(
            mock.Mock(return_value=successful_report(LoadMode.INITIAL))
        )
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {"status": "failed", "code": "LOADER_EXECUTION_FAILED"},
        )


class TestIncrementalCommand(unittest.TestCase):
    def test_current_contract_blocks_before_config_or_database_import(self) -> None:
        config_loader = mock.Mock(side_effect=AssertionError("must not parse config"))
        coordinator_loader = mock.Mock(side_effect=AssertionError("must not import DB code"))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch("brerc_loader.cli.load_loader_config", config_loader),
            mock.patch("brerc_loader.cli._load_coordinator", coordinator_loader),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(
                [
                    "incremental",
                    "--config",
                    "/private/path-containing-a-secret/loader.yaml",
                ]
            )
        self.assertEqual(code, 3)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"status": "failed", "code": "INCREMENTAL_SOURCE_CONTRACT_BLOCKED"},
        )
        config_loader.assert_not_called()
        coordinator_loader.assert_not_called()
        self.assertNotIn("path-containing", stderr.getvalue())


class TestCliSurface(unittest.TestCase):
    def test_help_exposes_only_explicit_modes_and_config(self) -> None:
        help_text = _parser().format_help()
        self.assertIn("initial", help_text)
        self.assertIn("refresh", help_text)
        self.assertIn("incremental", help_text)
        subcommand_help = " ".join(
            _parser().parse_args([mode, "--config", "/x"]).command
            for mode in ("initial", "refresh", "incremental")
        )
        self.assertEqual(subcommand_help, "initial refresh incremental")
        for forbidden in (
            "--dsn",
            "--password",
            "--sql",
            "--query",
            "--force",
            "--skip",
        ):
            self.assertNotIn(forbidden, help_text)

    def test_unsafe_or_unknown_arguments_do_not_echo_their_values(self) -> None:
        for flag in ("--dsn", "--password", "--sql", "--force", "--skip-validation"):
            sensitive_value = "postgresql://user:secret@internal/private"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                self.subTest(flag=flag),
                self.assertRaises(SystemExit) as raised,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                main(["initial", flag, sensitive_value])
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"status": "failed", "code": "LOADER_CLI_USAGE_INVALID"},
            )
            self.assertNotIn(sensitive_value, stderr.getvalue())


class TestReportValidation(unittest.TestCase):
    def test_success_envelope_rejects_invalid_ids_counts_digest_and_activation(self) -> None:
        base = successful_report()
        mutations = (
            {"run_id": "not-a-uuid"},
            {"release_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
            {"source_rows": -1},
            {"public_records": True},
            {"candidate_sha256": "A" * 64},
            {"activated": False},
            {"reused_active_release": 1},
            {"reused_active_release": True},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                values = {
                    "run_id": base.run_id,
                    "release_id": base.release_id,
                    "mode": base.mode,
                    "state": base.state,
                    "source_rows": base.source_rows,
                    "public_records": base.public_records,
                    "distribution_cells": base.distribution_cells,
                    "candidate_sha256": base.candidate_sha256,
                    "activated": base.activated,
                    "reused_active_release": base.reused_active_release,
                    **changes,
                }
                LoaderRunReport(**values)


if __name__ == "__main__":
    unittest.main()

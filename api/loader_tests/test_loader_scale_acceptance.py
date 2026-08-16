"""Fast contract tests for the manual five-million-row acceptance harness."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from etl.source_contract import BRERC_MAIN_DATA_DASH

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "api/scripts/run_loader_scale_acceptance.py"
SOURCE_FIXTURE = REPO_ROOT / "api/loader_tests/postgres16_scale_source_fixture.sql"
WORKFLOW = REPO_ROOT / ".github/workflows/loader-scale-acceptance.yml"
RUNBOOK = REPO_ROOT / "docs/POSTGRES_LOADER_SCALE_ACCEPTANCE.md"


def _load_runner():
    spec = importlib.util.spec_from_file_location("brerc_loader_scale_acceptance", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("scale runner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestScaleSourceFixture(unittest.TestCase):
    def test_fixture_is_exactly_five_million_and_matches_the_39_column_contract(self) -> None:
        text = SOURCE_FIXTURE.read_text(encoding="utf-8")
        self.assertIn("generate_series(1, 5000000)", text)
        table_block = text.split("CREATE TABLE dashboard.synthetic_records (", 1)[1].split(");", 1)[
            0
        ]
        actual_columns = tuple(
            line.strip().split(maxsplit=1)[0].rstrip(",")
            for line in table_block.splitlines()
            if line.strip()
        )
        self.assertEqual(
            actual_columns,
            tuple(column.name for column in BRERC_MAIN_DATA_DASH.columns),
        )

    def test_fixture_has_independent_safety_cohorts_and_no_client_claim(self) -> None:
        text = SOURCE_FIXTURE.read_text(encoding="utf-8")
        for evidence in (
            "SYNTH-SCALE-SPARSE",
            "SYNTH-SCALE-UNLIC",
            "SYNTH-SCALE-SENS",
            "SYNTH-SCALE-ORDINARY",
            "CASE WHEN sequence_no = 3 THEN 'n' ELSE 'y' END",
            "CASE WHEN sequence_no BETWEEN 4 AND 6 THEN 'Yes' ELSE 'No' END",
            "SYNTHETIC-PRIVATE-SCALE-PLACE-MUST-NOT-CROSS",
            "SYNTHETIC-PRIVATE-SCALE-COMMENT-MUST-NOT-CROSS",
            "WHEN sequence_no <= 6 THEN 'ST587721'",
            "WHEN sequence_no <= 9 THEN 'ST597721'",
        ):
            self.assertIn(evidence, text)
        self.assertIn("Synthetic-only", text)
        self.assertNotIn("BRERC client data", text)


class TestScaleRunnerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner()

    @staticmethod
    def _valid_arguments(output: Path) -> list[str]:
        return [
            "--confirm",
            "RUN_EXACTLY_5000000_SYNTHETIC_ROWS",
            "--evidence-out",
            str(output),
            "--max-total-seconds",
            "7200",
            "--max-finalize-seconds",
            "1800",
            "--max-activate-seconds",
            "300",
            "--max-cleanup-seconds",
            "900",
            "--max-rss-mib",
            "2048",
            "--max-source-temp-mib",
            "8192",
            "--max-target-temp-mib",
            "8192",
            "--max-target-wal-mib",
            "16384",
            "--max-target-db-growth-mib",
            "16384",
            "--min-free-disk-mib",
            "1024",
        ]

    def test_all_budgets_are_explicit_positive_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            parsed_output, budgets = self.runner._arguments(self._valid_arguments(output))
        self.assertEqual(parsed_output, output)
        self.assertEqual(
            set(budgets.as_document()),
            {
                "maxActivateSeconds",
                "maxCleanupSeconds",
                "maxFinalizeSeconds",
                "maxProcessRssMiB",
                "maxSourceTempMiB",
                "maxTargetDatabaseGrowthMiB",
                "maxTargetTempMiB",
                "maxTargetWalMiB",
                "maxTotalSeconds",
                "minFreeDiskMiB",
            },
        )
        for value in budgets.as_document().values():
            self.assertGreater(value, 0)

    def test_missing_wrong_or_nonfinite_budget_fails_before_database_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            valid = self._valid_arguments(output)
            cases = (
                valid[:-2],
                ["--confirm", "wrong", *valid[2:]],
                [*valid[:-2], "--min-free-disk-mib", "0"],
                [*valid[:-2], "--min-free-disk-mib", "nan"],
            )
            for arguments in cases:
                with (
                    self.subTest(arguments=arguments[-2:]),
                    self.assertRaises(self.runner.ScaleAcceptanceError),
                ):
                    self.runner._arguments(arguments)

    def test_total_budget_cap_and_existing_evidence_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            too_long = self._valid_arguments(output)
            total_index = too_long.index("--max-total-seconds") + 1
            too_long[total_index] = "18001"
            with self.assertRaises(self.runner.ScaleAcceptanceError):
                self.runner._arguments(too_long)
            output.write_text('{"status":"passed"}\n', encoding="utf-8")
            with self.assertRaises(self.runner.ScaleAcceptanceError):
                self.runner._arguments(self._valid_arguments(output))

    def test_cli_error_is_fixed_and_does_not_echo_unknown_input(self) -> None:
        secret = "postgresql://user:PRIVATE-SCALE-PASSWORD@example.invalid/db"  # noqa: S105
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = self.runner.main(["--unknown", secret])
        rendered = stdout.getvalue()
        self.assertEqual(status, 1)
        self.assertEqual(
            json.loads(rendered),
            {"code": "SCALE_ACCEPTANCE_FAILED", "status": "failed"},
        )
        self.assertNotIn(secret, rendered)

    def test_evidence_writer_is_canonical_and_newline_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            rendered = self.runner._write_evidence(
                path,
                {"status": "passed", "counts": {"sourceRows": 5_000_000}},
            )
            stored = path.read_text(encoding="utf-8")
        self.assertEqual(
            rendered,
            '{"counts":{"sourceRows":5000000},"status":"passed"}',
        )
        self.assertEqual(stored, rendered + "\n")

    def test_expected_count_equations_are_complete(self) -> None:
        counts = self.runner.EXPECTED_COUNTS
        self.assertEqual(counts["sourceRows"], 5_000_000)
        self.assertEqual(
            counts["transformWithheld"] + counts["suppressionWithheld"] + counts["publishedBasis"],
            counts["sourceRows"],
        )
        self.assertEqual(counts["publicRecords"], 0)
        self.assertEqual(counts["distributionCells"], 102)

    def test_budget_comparison_uses_unrounded_measurements(self) -> None:
        with self.assertRaises(self.runner.ScaleAcceptanceError):
            self.runner._require_budget(1.0004, 1.0)

    def test_runtime_oracles_are_observed_not_literal_claims(self) -> None:
        text = RUNNER_PATH.read_text(encoding="utf-8")
        for evidence in (
            "candidate_staged",
            'visibility["staged_empty"] > 0',
            "source_inventory_count",
            "delta_row_count",
            "published_place_values",
            "published_abundance_values",
            "published_record_types",
            "published_verification",
            "'publication', 'serve'",
            "individual_records_available",
            "record_verification_available",
            "stage_batch_sizes",
            "target_database_peak_bytes",
            "minimum_free_disk_bytes",
            "manifestDigests",
        ):
            self.assertIn(evidence, text)
        self.assertNotIn('"candidateInvisibleBeforeActivation": True', text)


class TestScaleWorkflowAndRunbook(unittest.TestCase):
    def test_workflow_is_manual_global_non_cancelling_and_fully_pinned(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", event_block)
        self.assertNotIn("push:", event_block)
        self.assertNotIn("pull_request:", event_block)
        self.assertIn("group: brerc-loader-scale-acceptance-global", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("environment: brerc-scale-acceptance", text)
        self.assertIn("timeout-minutes: 360", text)
        self.assertIn("needs: validate", text)
        self.assertNotIn("if: ${{ inputs.confirm", text)
        self.assertIn("SCALE_INPUT_INVALID", text)
        self.assertIn("github.run_attempt", text)
        self.assertIn("if-no-files-found: error", text)
        for mutable in ("actions/checkout@v", "actions/setup-python@v", "upload-artifact@v"):
            self.assertNotIn(mutable, text)
        self.assertIn("actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955", text)
        self.assertIn("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", text)
        self.assertIn("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", text)
        self.assertIn(self._source_image(), text)
        self.assertIn(self._target_image(), text)

    @staticmethod
    def _source_image() -> str:
        return (
            "postgres:16.10-bookworm@sha256:"
            "38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74"
        )

    @staticmethod
    def _target_image() -> str:
        return (
            "postgis/postgis:16-3.5@sha256:"
            "cfbd2d2a5ecded5af7afaad719fa2117096f59ac8d0d9430e157eeffcd82da2e"
        )

    def test_workflow_requires_every_runner_budget_and_exact_confirmation(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        for value in (
            "RUN_EXACTLY_5000000_SYNTHETIC_ROWS",
            "--max-total-seconds",
            "--max-finalize-seconds",
            "--max-activate-seconds",
            "--max-cleanup-seconds",
            "--max-rss-mib",
            "--max-source-temp-mib",
            "--max-target-temp-mib",
            "--max-target-wal-mib",
            "--max-target-db-growth-mib",
            "--min-free-disk-mib",
        ):
            self.assertIn(value, text)

    def test_runbook_does_not_claim_unexecuted_or_replacement_evidence(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("has **not been executed", text)
        self.assertIn("cannot prove", text)
        self.assertIn("old-release-to-new-release replacement", text)
        self.assertIn("missing metric", text)
        self.assertIn("no real brerc data", text.casefold())
        self.assertIn("cleanup_pending=true", text)


if __name__ == "__main__":
    unittest.main()

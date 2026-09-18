"""Tests for invocation-scoped release evidence reconciliation."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deploy" / "validation" / "verify_release_evidence.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_release_evidence", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - repository invariant
        raise RuntimeError("unable to load evidence verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load_script()

INVOCATION_ID = "0123456789abcdef0123456789abcdef"
RUN_ID = "00112233-4455-4677-8899-aabbccddeeff"
RELEASE_ID = "10213243-5465-4767-98a9-bacbdcedfe0f"
DATASET_VERSION = "a" * 64
CANDIDATE_SHA256 = "b" * 64


class ReleaseEvidenceVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.unit_properties = self.directory / "unit.properties"
        self.journal = self.directory / "journal.json"
        self.database = self.directory / "database.json"
        self.summary = self.directory / "summary.json"
        self.provenance = self.directory / "provenance.json"
        self.loader_result = {
            "status": "ok",
            "mode": "initial",
            "state": "succeeded",
            "runId": RUN_ID,
            "releaseId": RELEASE_ID,
            "candidateSha256": CANDIDATE_SHA256,
            "activated": True,
            "reusedActiveRelease": False,
            "sourceRows": 19,
            "publicRecords": 11,
            "distributionCells": 7,
        }
        self.database_result = {
            "runId": RUN_ID,
            "releaseId": RELEASE_ID,
            "activeReleaseId": RELEASE_ID,
            "datasetVersion": DATASET_VERSION,
            "candidateSha256": CANDIDATE_SHA256,
            "baseReleaseId": None,
            "reusedActiveRelease": False,
            "sourceRows": 19,
            "publicRecords": 11,
            "distributionCells": 7,
            "loadMode": "initial",
            "status": "succeeded",
        }
        self.summary_result = {
            "releaseId": RELEASE_ID,
            "datasetVersion": DATASET_VERSION,
        }
        self.provenance_result = {
            "releaseId": RELEASE_ID,
            "datasetVersion": DATASET_VERSION,
        }
        self._write_valid_evidence()

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _write_journal(
        self,
        *messages: str,
        invocation_id: str = INVOCATION_ID,
    ) -> None:
        rows = [
            {
                "_SYSTEMD_INVOCATION_ID": invocation_id,
                "MESSAGE": message,
            }
            for message in messages
        ]
        self.journal.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _write_valid_evidence(self) -> None:
        self.unit_properties.write_text(
            "\n".join(
                (
                    f"InvocationID={INVOCATION_ID}",
                    "Result=success",
                    "ExecMainCode=1",
                    "ExecMainStatus=0",
                    "ActiveState=inactive",
                    "SubState=dead",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        self._write_journal(
            "starting loader",
            json.dumps(self.loader_result, separators=(",", ":")),
        )
        self._write_json(self.database, self.database_result)
        self._write_json(self.summary, self.summary_result)
        self._write_json(self.provenance, self.provenance_result)

    def _verify(self, *, invocation_id: str = INVOCATION_ID, mode: str = "initial"):
        return evidence.verify(
            invocation_id=invocation_id,
            expected_mode=mode,
            unit_properties_path=self.unit_properties,
            journal_path=self.journal,
            database_path=self.database,
            summary_path=self.summary,
            provenance_path=self.provenance,
        )

    def assert_invalid(self, *, invocation_id: str = INVOCATION_ID, mode: str = "initial") -> None:
        with self.assertRaises(evidence.EvidenceInvalid):
            self._verify(invocation_id=invocation_id, mode=mode)

    def test_one_coherent_invocation_database_and_api_release_is_verified(self) -> None:
        self.assertEqual(
            self._verify(),
            {
                "status": "verified",
                "mode": "initial",
                "runId": RUN_ID,
                "releaseId": RELEASE_ID,
                "datasetVersion": DATASET_VERSION,
                "candidateSha256": CANDIDATE_SHA256,
                "invocationId": INVOCATION_ID,
            },
        )

    def test_invalid_or_stale_invocation_id_is_refused(self) -> None:
        self.assert_invalid(invocation_id="not-an-invocation")

        stale = "f" * 32
        self.assert_invalid(invocation_id=stale)

    def test_unsuccessful_or_stale_unit_state_is_refused(self) -> None:
        original = self.unit_properties.read_text(encoding="utf-8")
        for before, after in (
            ("Result=success", "Result=exit-code"),
            ("ExecMainStatus=0", "ExecMainStatus=1"),
            (f"InvocationID={INVOCATION_ID}", f"InvocationID={'f' * 32}"),
        ):
            with self.subTest(after=after):
                self.unit_properties.write_text(original.replace(before, after), encoding="utf-8")
                self.assert_invalid()
        self.unit_properties.write_text(original, encoding="utf-8")

    def test_any_journal_row_from_another_invocation_is_refused(self) -> None:
        rows = [
            {
                "_SYSTEMD_INVOCATION_ID": INVOCATION_ID,
                "MESSAGE": json.dumps(self.loader_result),
            },
            {
                "_SYSTEMD_INVOCATION_ID": "f" * 32,
                "MESSAGE": "unrelated stale message",
            },
        ]
        self.journal.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

        self.assert_invalid()

    def test_zero_or_multiple_terminal_loader_results_are_refused(self) -> None:
        with self.subTest(results=0):
            self._write_journal("loader produced no terminal document")
            self.assert_invalid()

        with self.subTest(results=2):
            result = json.dumps(self.loader_result)
            self._write_journal(result, result)
            self.assert_invalid()

    def test_unsuccessful_or_unactivated_loader_result_is_refused(self) -> None:
        for field, value in (
            ("status", "failed"),
            ("state", "failed"),
            ("mode", "refresh"),
            ("activated", False),
        ):
            with self.subTest(field=field, value=value):
                changed = {**self.loader_result, field: value}
                self._write_journal(json.dumps(changed))
                self.assert_invalid()

    def test_database_identity_or_state_mismatch_is_refused(self) -> None:
        checks = (
            ("runId", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
            ("releaseId", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
            ("activeReleaseId", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
            ("loadMode", "refresh"),
            ("status", "failed"),
            ("candidateSha256", "c" * 64),
            ("reusedActiveRelease", True),
            ("sourceRows", 20),
            ("publicRecords", 12),
            ("distributionCells", 8),
        )
        for field, value in checks:
            with self.subTest(field=field):
                changed = {**self.database_result, field: value}
                self._write_json(self.database, changed)
                self.assert_invalid()
                self._write_json(self.database, self.database_result)

    def test_api_release_or_dataset_mismatch_is_refused(self) -> None:
        other_release = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        for path, document, field, value in (
            (self.summary, self.summary_result, "releaseId", other_release),
            (self.provenance, self.provenance_result, "releaseId", other_release),
            (self.summary, self.summary_result, "datasetVersion", "other-version"),
            (self.provenance, self.provenance_result, "datasetVersion", "other-version"),
        ):
            with self.subTest(path=path.name, field=field):
                self._write_json(path, {**document, field: value})
                self.assert_invalid()
                self._write_json(path, document)

    def test_changed_and_unchanged_refresh_shapes_are_verified(self) -> None:
        base_release = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        for reused, result_release, expected_base in (
            (False, RELEASE_ID, base_release),
            (True, RELEASE_ID, RELEASE_ID),
        ):
            with self.subTest(reused=reused):
                self.loader_result.update({"mode": "refresh", "reusedActiveRelease": reused})
                self.database_result.update(
                    {
                        "loadMode": "refresh",
                        "baseReleaseId": expected_base,
                        "reusedActiveRelease": reused,
                        "releaseId": result_release,
                        "activeReleaseId": result_release,
                    }
                )
                self._write_valid_evidence()
                self.assertEqual(self._verify(mode="refresh")["releaseId"], result_release)

    def test_malformed_or_incomplete_files_are_refused(self) -> None:
        for path, content in (
            (self.journal, "not json\n"),
            (self.database, "[]"),
            (self.summary, "{}"),
            (self.provenance, "not json"),
            (self.unit_properties, "Result=success\n"),
        ):
            with self.subTest(path=path.name):
                original = path.read_text(encoding="utf-8")
                path.write_text(content, encoding="utf-8")
                self.assert_invalid()
                path.write_text(original, encoding="utf-8")

    def test_command_failure_is_bounded_and_does_not_disclose_evidence(self) -> None:
        self.journal.write_text("not-json\n", encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "--invocation-id",
            INVOCATION_ID,
            "--mode",
            "initial",
            "--unit-properties",
            str(self.unit_properties),
            "--journal-json",
            str(self.journal),
            "--database-json",
            str(self.database),
            "--api-summary-json",
            str(self.summary),
            "--api-provenance-json",
            str(self.provenance),
        ]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = evidence.main(argv)

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            '{"code":"RELEASE_EVIDENCE_INVALID","status":"failed"}\n',
        )
        self.assertNotIn(str(self.journal), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

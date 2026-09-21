"""Tests for bounded failed-attempt database evidence validation."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deploy" / "validation" / "verify_failed_attempt_evidence.py"
RUN_ID = "00112233-4455-4677-8899-aabbccddeeff"
RELEASE_ID = "10213243-5465-4767-98a9-bacbdcedfe0f"
ENVIRONMENT_ID = "20314253-6475-4867-a8b9-cadbecfd0e1f"
DATABASE_NAME = "brerc_ui"
MONITOR_ROLE = "brerc_monitor_login"
WINDOW_START = "2026-09-18T20:00:00+00:00"
WINDOW_END = "2026-09-18T20:03:00+00:00"
INVOCATION_ID = "0123456789abcdef0123456789abcdef"
JOURNAL_REALTIME_USEC = "1789761720000000"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_failed_attempt_evidence", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - repository invariant
        raise RuntimeError("unable to load failed-attempt evidence verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load_script()


class FailedAttemptEvidenceVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "database-failure.json"
        self.unit = Path(self.temporary.name) / "unit.properties"
        self.journal = Path(self.temporary.name) / "journal.json"
        self.window = Path(self.temporary.name) / "database-window.json"
        self.job = {
            "runId": RUN_ID,
            "status": "failed",
            "failureCode": "LOADER_EXECUTION_FAILED",
            "startedAt": "2026-09-18T20:01:00+00:00",
            "finishedAt": "2026-09-18T20:02:00+00:00",
            "sourceRows": 19,
            "candidateRows": 11,
            "rowsWithheld": 8,
            "releaseId": RELEASE_ID,
            "releaseStatus": "failed",
            "cleanupPending": False,
        }
        self.document = {
            "environmentId": ENVIRONMENT_ID,
            "databaseName": DATABASE_NAME,
            "loginRole": MONITOR_ROLE,
            "sessionRole": MONITOR_ROLE,
            "readOnly": "on",
            "isSuperuser": False,
            "canLogin": True,
            "canCreateDb": False,
            "canCreateRole": False,
            "canReplicate": False,
            "canBypassRls": False,
            "effectiveRoles": ["brerc_monitor"],
            "directRoles": ["brerc_monitor"],
            "windowStart": WINDOW_START,
            "windowEnd": WINDOW_END,
            "loadMode": "initial",
            "jobCount": 1,
            "jobs": [self.job],
        }
        self._write(self.document)
        self.unit.write_text(
            "\n".join(
                (
                    f"InvocationID={INVOCATION_ID}",
                    "Result=exit-code",
                    "ExecMainCode=1",
                    "ExecMainStatus=1",
                    "ActiveState=failed",
                    "SubState=failed",
                    "InactiveExitTimestamp=@1789761600",
                    "StateChangeTimestamp=@1789761750",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        self.journal.write_text(
            json.dumps(
                {
                    "_SYSTEMD_INVOCATION_ID": INVOCATION_ID,
                    "__REALTIME_TIMESTAMP": JOURNAL_REALTIME_USEC,
                    "MESSAGE": "loader attempt failed",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.window.write_text(
            json.dumps(
                {
                    "invocationId": INVOCATION_ID,
                    "mode": "initial",
                    "windowStart": WINDOW_START,
                    "windowEnd": WINDOW_END,
                }
            ),
            encoding="utf-8",
        )

    def _write(self, value: object) -> None:
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def _verify(self, mode: str = "initial"):
        return evidence.verify(
            self.path,
            invocation_id=INVOCATION_ID,
            expected_mode=mode,
            expected_window_start=WINDOW_START,
            expected_window_end=WINDOW_END,
            expected_environment_id=ENVIRONMENT_ID,
            expected_database=DATABASE_NAME,
            expected_role=MONITOR_ROLE,
            unit_properties_path=self.unit,
            journal_path=self.journal,
            window_path=self.window,
        )

    def assert_invalid(self, mode: str = "initial") -> None:
        with self.assertRaises(evidence.FailedAttemptEvidenceInvalid):
            self._verify(mode)

    def test_one_terminal_failed_job_is_verified(self) -> None:
        self.assertEqual(
            self._verify(),
            {
                "status": "verified",
                "mode": "initial",
                "invocationId": INVOCATION_ID,
                "environmentId": ENVIRONMENT_ID,
                "jobCount": 1,
                "runId": RUN_ID,
                "databaseState": "terminal-failed",
            },
        )

    def test_zero_jobs_is_distinct_verified_database_state(self) -> None:
        self._write({**self.document, "jobCount": 0, "jobs": []})
        self.assertEqual(self._verify()["databaseState"], "no-matching-job")

    def test_systemd_invocation_journal_and_window_are_bound(self) -> None:
        original_unit = self.unit.read_text(encoding="utf-8")
        original_journal = self.journal.read_text(encoding="utf-8")
        original_window = self.window.read_text(encoding="utf-8")
        for path, content in (
            (self.unit, original_unit.replace("Result=exit-code", "Result=success")),
            (self.unit, original_unit.replace("ActiveState=failed", "ActiveState=inactive")),
            (
                self.unit,
                original_unit.replace(f"InvocationID={INVOCATION_ID}", f"InvocationID={'f' * 32}"),
            ),
            (
                self.journal,
                original_journal.replace(INVOCATION_ID, "f" * 32),
            ),
            (
                self.window,
                original_window.replace(INVOCATION_ID, "f" * 32),
            ),
            (
                self.window,
                original_window.replace('"mode": "initial"', '"mode": "refresh"'),
            ),
        ):
            with self.subTest(path=path.name, content=content):
                path.write_text(content, encoding="utf-8")
                self.assert_invalid()
                path.write_text(
                    {
                        self.unit: original_unit,
                        self.journal: original_journal,
                        self.window: original_window,
                    }[path],
                    encoding="utf-8",
                )

    def test_journal_realtime_must_match_the_database_clock_window(self) -> None:
        original = json.loads(self.journal.read_text(encoding="utf-8"))
        for timestamp in (
            "not-a-microsecond-timestamp",
            "1789761539000000",
            "1789761841000000",
            "4070908800000000",
        ):
            with self.subTest(timestamp=timestamp):
                self.journal.write_text(
                    json.dumps({**original, "__REALTIME_TIMESTAMP": timestamp}) + "\n",
                    encoding="utf-8",
                )
                self.assert_invalid()
        self.journal.write_text(json.dumps(original) + "\n", encoding="utf-8")

    def test_systemd_manager_lifecycle_must_match_the_database_window(self) -> None:
        original = self.unit.read_text(encoding="utf-8")
        for before, after in (
            ("InactiveExitTimestamp=@1789761600", "InactiveExitTimestamp=@4070908800"),
            ("StateChangeTimestamp=@1789761750", "StateChangeTimestamp=@1789761539"),
            ("StateChangeTimestamp=@1789761750", "StateChangeTimestamp=not-a-time"),
        ):
            with self.subTest(after=after):
                self.unit.write_text(original.replace(before, after), encoding="utf-8")
                self.assert_invalid()
        self.unit.write_text(original, encoding="utf-8")

    def test_one_cancelled_job_without_release_is_verified(self) -> None:
        cancelled = {
            **self.job,
            "status": "cancelled",
            "failureCode": None,
            "releaseId": None,
            "releaseStatus": None,
            "cleanupPending": None,
            "sourceRows": None,
            "candidateRows": None,
            "rowsWithheld": None,
        }
        self._write({**self.document, "jobs": [cancelled]})
        self.assertEqual(self._verify()["databaseState"], "terminal-cancelled")

    def test_ambiguous_count_or_multiple_jobs_is_refused(self) -> None:
        for count, jobs in ((0, [self.job]), (2, [self.job, self.job])):
            with self.subTest(count=count):
                self._write({**self.document, "jobCount": count, "jobs": jobs})
                self.assert_invalid()

    def test_nonterminal_successful_or_cleanup_pending_job_is_refused(self) -> None:
        for changed in (
            {**self.job, "status": "activating", "failureCode": None},
            {**self.job, "status": "succeeded", "failureCode": None},
            {**self.job, "cleanupPending": True},
            {**self.job, "releaseStatus": "active"},
        ):
            self._write({**self.document, "jobs": [changed]})
            self.assert_invalid()

    def test_invalid_mode_window_or_timestamp_is_refused(self) -> None:
        changes = (
            {"loadMode": "refesh"},
            {"windowStart": "2026-09-18T20:03:00+00:00"},
            {"windowEnd": "2026-09-19T00:00:01+00:00"},
            {"windowStart": "2026-09-18T20:00:00"},
        )
        for change in changes:
            with self.subTest(change=change):
                self._write({**self.document, **change})
                self.assert_invalid()

    def test_target_session_and_expected_window_are_bound(self) -> None:
        changes = (
            {"environmentId": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"},
            {"databaseName": "wrong_database"},
            {"loginRole": "wrong_role"},
            {"sessionRole": "wrong_role"},
            {"readOnly": "off"},
            {"isSuperuser": True},
            {"canLogin": False},
            {"canCreateDb": True},
            {"canCreateRole": True},
            {"canReplicate": True},
            {"canBypassRls": True},
            {"effectiveRoles": []},
            {"directRoles": ["brerc_monitor", "extra_role"]},
        )
        for change in changes:
            with self.subTest(change=change):
                self._write({**self.document, **change})
                self.assert_invalid()
        self._write(self.document)
        with self.assertRaises(evidence.FailedAttemptEvidenceInvalid):
            evidence.verify(
                self.path,
                invocation_id=INVOCATION_ID,
                expected_mode="initial",
                expected_window_start="2026-09-18T20:00:01+00:00",
                expected_window_end=WINDOW_END,
                expected_environment_id=ENVIRONMENT_ID,
                expected_database=DATABASE_NAME,
                expected_role=MONITOR_ROLE,
                unit_properties_path=self.unit,
                journal_path=self.journal,
                window_path=self.window,
            )

    def test_equivalent_window_offsets_are_compared_as_instants(self) -> None:
        self._write(
            {
                **self.document,
                "windowStart": "2026-09-18T21:00:00+01:00",
                "windowEnd": "2026-09-18T21:03:00+01:00",
            }
        )
        self.assertEqual(self._verify()["databaseState"], "terminal-failed")

    def test_job_times_counts_ids_and_exact_shapes_are_enforced(self) -> None:
        changes = (
            {"runId": "not-a-uuid"},
            {"startedAt": "2026-09-18T19:59:59+00:00"},
            {"finishedAt": "2026-09-18T20:03:01+00:00"},
            {"sourceRows": -1},
            {"candidateRows": True},
            {"unexpected": "field"},
        )
        for change in changes:
            with self.subTest(change=change):
                self._write({**self.document, "jobs": [{**self.job, **change}]})
                self.assert_invalid()
        self._write({**self.document, "unexpected": "field"})
        self.assert_invalid()

    def test_duplicate_json_keys_and_cli_failure_are_fail_closed(self) -> None:
        self.path.write_text(
            '{"windowStart":"2026-09-18T20:00:00Z","windowStart":"2026-09-18T20:00:01Z"}',
            encoding="utf-8",
        )
        self.assert_invalid()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = evidence.main(
                [
                    "--database-json",
                    str(self.path),
                    "--database-window-json",
                    str(self.window),
                    "--unit-properties",
                    str(self.unit),
                    "--journal-json",
                    str(self.journal),
                    "--invocation-id",
                    INVOCATION_ID,
                    "--mode",
                    "initial",
                    "--expected-window-start",
                    WINDOW_START,
                    "--expected-window-end",
                    WINDOW_END,
                    "--expected-environment-id",
                    ENVIRONMENT_ID,
                    "--expected-database",
                    DATABASE_NAME,
                    "--expected-role",
                    MONITOR_ROLE,
                ]
            )
        self.assertEqual(result, 2)
        self.assertEqual(
            errors.getvalue(),
            '{"code":"FAILED_ATTEMPT_EVIDENCE_INVALID","status":"failed"}\n',
        )


if __name__ == "__main__":
    unittest.main()

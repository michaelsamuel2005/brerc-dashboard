"""Unit tests for the root-owned, single-use initial approval marker."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deploy" / "initial" / "consume_initial_approval.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("consume_initial_approval", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - repository invariant
        raise RuntimeError("unable to load approval consumer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


approval = _load_script()
ARTIFACT_ID = "release-0123456789abcdef"
NOW = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)


class InitialApprovalConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "refresh"
        self.directory.mkdir(mode=0o700)
        self.marker = self.directory / "APPROVED_TO_INITIAL"

    def _write_marker(self, content: bytes | None = None) -> None:
        if content is None:
            content = (
                b'{"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123",'
                b'"artifactId":"release-0123456789abcdef",'
                b'"validFromUtc":"2026-09-18T19:55:00Z",'
                b'"expiresAtUtc":"2026-09-18T22:55:00Z"}'
            )
        self.marker.write_bytes(content)
        self.marker.chmod(0o400)

    def _consume(self) -> None:
        approval.consume_marker(
            self.marker,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            expected_artifact_id=ARTIFACT_ID,
            now_utc=NOW,
        )

    def assert_refused(self) -> None:
        with self.assertRaises(approval.ApprovalRefused):
            self._consume()

    def test_valid_marker_is_consumed_exactly_once(self) -> None:
        self._write_marker()

        self._consume()

        self.assertFalse(os.path.lexists(self.marker))
        self.assert_refused()

    def test_missing_marker_is_refused(self) -> None:
        self.assert_refused()

    def test_empty_or_whitespace_only_marker_is_refused_and_retained(self) -> None:
        for content in (b"", b" \t\n"):
            with self.subTest(content=content):
                self.marker.unlink(missing_ok=True)
                self._write_marker(content)
                self.assert_refused()
                self.assertTrue(self.marker.is_file())

    def test_oversized_marker_is_refused_and_retained(self) -> None:
        self._write_marker(b"x" * (approval.MAX_MARKER_BYTES + 1))

        self.assert_refused()

        self.assertTrue(self.marker.is_file())

    def test_unstructured_duplicate_or_extra_fields_are_refused(self) -> None:
        documents = (
            b"approval-reference-2026-09-18\n",
            b'{"schemaVersion":1,"schemaVersion":1}',
            (
                b'{"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123",'
                b'"artifactId":"release-0123456789abcdef",'
                b'"validFromUtc":"2026-09-18T19:55:00Z",'
                b'"expiresAtUtc":"2026-09-18T22:55:00Z","unexpected":true}'
            ),
        )
        for document in documents:
            with self.subTest(document=document):
                self.marker.unlink(missing_ok=True)
                self._write_marker(document)
                self.assert_refused()
                self.assertTrue(self.marker.is_file())

    def test_wrong_artifact_expired_future_or_overlong_approval_is_refused(self) -> None:
        templates = (
            '{"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123",'
            '"artifactId":"wrong-release","validFromUtc":"2026-09-18T19:55:00Z",'
            '"expiresAtUtc":"2026-09-18T22:55:00Z"}',
            '{"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123",'
            '"artifactId":"release-0123456789abcdef",'
            '"validFromUtc":"2026-09-18T15:00:00Z",'
            '"expiresAtUtc":"2026-09-18T19:00:00Z"}',
            '{"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123",'
            '"artifactId":"release-0123456789abcdef",'
            '"validFromUtc":"2026-09-18T20:05:00Z",'
            '"expiresAtUtc":"2026-09-18T21:00:00Z"}',
            '{"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123",'
            '"artifactId":"release-0123456789abcdef",'
            '"validFromUtc":"2026-09-18T19:00:00Z",'
            '"expiresAtUtc":"2026-09-19T00:00:01Z"}',
        )
        for document in templates:
            with self.subTest(document=document):
                self.marker.unlink(missing_ok=True)
                self._write_marker(document.encode())
                self.assert_refused()
                self.assertTrue(self.marker.is_file())

    def test_marker_with_wrong_mode_is_refused_and_retained(self) -> None:
        self._write_marker()
        self.marker.chmod(0o440)

        self.assert_refused()

        self.assertTrue(self.marker.is_file())

    def test_symlink_marker_is_refused_without_touching_target(self) -> None:
        target = self.directory / "approval-target"
        target.write_text("approval-reference\n", encoding="utf-8")
        target.chmod(0o400)
        self.marker.symlink_to(target)

        self.assert_refused()

        self.assertTrue(self.marker.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "approval-reference\n")

    def test_hard_linked_marker_is_refused_without_unlinking_it(self) -> None:
        self._write_marker()
        second_name = self.directory / "second-name"
        os.link(self.marker, second_name)

        self.assert_refused()

        self.assertTrue(self.marker.is_file())
        self.assertTrue(second_name.is_file())

    def test_group_or_world_writable_parent_is_refused(self) -> None:
        self._write_marker()
        for mode in (0o720, 0o702):
            with self.subTest(mode=oct(mode)):
                self.directory.chmod(mode)
                self.assert_refused()
                self.assertTrue(self.marker.is_file())

    def test_command_failure_is_bounded_and_does_not_disclose_marker_details(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(approval.os, "geteuid", return_value=1000),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = approval.main(["--expected-artifact-id", ARTIFACT_ID])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            '{"code":"INITIAL_APPROVAL_INVALID","status":"refused"}\n',
        )
        self.assertNotIn(str(self.marker), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

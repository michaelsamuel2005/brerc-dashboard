#!/usr/bin/env python3
"""Consume the single-use production-initial approval before loader execution.

The systemd unit runs this fixed helper as root in ``ExecStartPre``.  It emits
only a bounded status document: approval contents and filesystem details never
enter the journal.  The parent directory is expected to be root-controlled, so
the checks and unlink cannot be raced by the unprivileged loader account.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MARKER = Path("/etc/brerc/initial-approval/APPROVED_TO_INITIAL")
MAX_MARKER_BYTES = 4096
MAX_APPROVAL_WINDOW = timedelta(hours=4)
_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_APPROVAL_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_APPROVAL_KEYS = {
    "schemaVersion",
    "approvalReference",
    "artifactId",
    "validFromUtc",
    "expiresAtUtc",
}


class ApprovalRefused(RuntimeError):
    """The marker was absent or did not satisfy the fixed approval contract."""


def _mode(value: int) -> int:
    return stat.S_IMODE(value)


def _approval_document(content: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for name, value in pairs:
            if name in document:
                raise ApprovalRefused
            document[name] = value
        return document

    try:
        decoded = content.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError, ApprovalRefused):
        raise ApprovalRefused from None
    if not isinstance(value, dict) or set(value) != _APPROVAL_KEYS:
        raise ApprovalRefused
    return value


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ApprovalRefused
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        raise ApprovalRefused from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ApprovalRefused
    return parsed


def _validate_approval(
    document: dict[str, Any],
    *,
    expected_artifact_id: str,
    now_utc: datetime,
) -> None:
    if _ARTIFACT_ID.fullmatch(expected_artifact_id) is None:
        raise ApprovalRefused
    if type(document.get("schemaVersion")) is not int or document["schemaVersion"] != 1:
        raise ApprovalRefused
    reference = document.get("approvalReference")
    artifact_id = document.get("artifactId")
    if (
        not isinstance(reference, str)
        or _APPROVAL_REFERENCE.fullmatch(reference) is None
        or artifact_id != expected_artifact_id
    ):
        raise ApprovalRefused
    valid_from = _utc_timestamp(document.get("validFromUtc"))
    expires_at = _utc_timestamp(document.get("expiresAtUtc"))
    if now_utc.tzinfo is None or now_utc.utcoffset() != timedelta(0):
        raise ApprovalRefused
    if not valid_from <= now_utc < expires_at:
        raise ApprovalRefused
    if not timedelta(0) < expires_at - valid_from <= MAX_APPROVAL_WINDOW:
        raise ApprovalRefused


def consume_marker(
    marker: Path,
    *,
    expected_uid: int,
    expected_gid: int,
    expected_artifact_id: str,
    now_utc: datetime | None = None,
) -> None:
    """Validate and durably unlink one scoped root-controlled approval marker."""

    try:
        parent = os.lstat(marker.parent)
        candidate = os.lstat(marker)
    except OSError:
        raise ApprovalRefused from None

    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != expected_uid
        or _mode(parent.st_mode) & 0o022
    ):
        raise ApprovalRefused

    if (
        not stat.S_ISREG(candidate.st_mode)
        or candidate.st_uid != expected_uid
        or candidate.st_gid != expected_gid
        or _mode(candidate.st_mode) != 0o400
        or candidate.st_nlink != 1
        or not 1 <= candidate.st_size <= MAX_MARKER_BYTES
    ):
        raise ApprovalRefused

    try:
        # The directory is root-controlled, so a non-following lstat followed
        # by this bounded read cannot be replaced by the service identity.
        content = marker.read_bytes()
        if not content.strip() or len(content) > MAX_MARKER_BYTES:
            raise ApprovalRefused
        document = _approval_document(content)
        _validate_approval(
            document,
            expected_artifact_id=expected_artifact_id,
            now_utc=now_utc or datetime.now(timezone.utc),
        )
        marker.unlink()
        directory_fd = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if os.path.lexists(marker):
            raise ApprovalRefused
    except ApprovalRefused:
        raise
    except OSError:
        raise ApprovalRefused from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consume one time- and artifact-bound production-initial approval."
    )
    parser.add_argument("--expected-artifact-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise ApprovalRefused
        consume_marker(
            MARKER,
            expected_uid=0,
            expected_gid=0,
            expected_artifact_id=args.expected_artifact_id,
        )
    except ApprovalRefused:
        sys.stderr.write(
            json.dumps(
                {"status": "refused", "code": "INITIAL_APPROVAL_INVALID"},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2

    sys.stdout.write(
        json.dumps(
            {"status": "ok", "approval": "consumed"},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

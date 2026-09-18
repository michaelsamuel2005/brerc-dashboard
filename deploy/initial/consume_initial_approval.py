#!/usr/bin/env python3
"""Consume the single-use production-initial approval before loader execution.

The systemd unit runs this fixed helper as root in ``ExecStartPre``.  It emits
only a bounded status document: approval contents and filesystem details never
enter the journal.  The parent directory is expected to be root-controlled, so
the checks and unlink cannot be raced by the unprivileged loader account.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

MARKER = Path("/etc/brerc/initial-approval/APPROVED_TO_INITIAL")
MAX_MARKER_BYTES = 4096


class ApprovalRefused(RuntimeError):
    """The marker was absent or did not satisfy the fixed approval contract."""


def _mode(value: int) -> int:
    return stat.S_IMODE(value)


def consume_marker(
    marker: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    """Validate and durably unlink one root-controlled approval marker."""

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


def main() -> int:
    try:
        if os.geteuid() != 0:
            raise ApprovalRefused
        consume_marker(MARKER, expected_uid=0, expected_gid=0)
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

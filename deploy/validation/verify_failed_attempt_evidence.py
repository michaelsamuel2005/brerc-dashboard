#!/usr/bin/env python3
"""Validate one bounded, privacy-safe failed-loader database evidence result."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_INVOCATION_ID = re.compile(r"^[0-9a-f]{32}$")
_SYSTEMD_UNIX_TIMESTAMP = re.compile(r"^@(?P<seconds>[0-9]+)(?:\.(?P<fraction>[0-9]{1,6}))?$")
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_UNIT_KEYS = {
    "InvocationID",
    "Result",
    "ExecMainCode",
    "ExecMainStatus",
    "ActiveState",
    "SubState",
    "InactiveExitTimestamp",
    "StateChangeTimestamp",
}
_FAILURE_RESULTS = {
    "exit-code",
    "signal",
    "core-dump",
    "watchdog",
    "start-limit-hit",
    "resources",
    "timeout",
    "oom-kill",
    "protocol",
}
_MAXIMUM_CLOCK_SKEW = timedelta(seconds=60)
_WINDOW_KEYS = {"invocationId", "mode", "windowStart", "windowEnd"}
_ROOT_KEYS = {
    "environmentId",
    "databaseName",
    "loginRole",
    "sessionRole",
    "readOnly",
    "isSuperuser",
    "canLogin",
    "canCreateDb",
    "canCreateRole",
    "canReplicate",
    "canBypassRls",
    "effectiveRoles",
    "directRoles",
    "windowStart",
    "windowEnd",
    "loadMode",
    "jobCount",
    "jobs",
}
_JOB_KEYS = {
    "runId",
    "status",
    "failureCode",
    "startedAt",
    "finishedAt",
    "sourceRows",
    "candidateRows",
    "rowsWithheld",
    "releaseId",
    "releaseStatus",
    "cleanupPending",
}


class FailedAttemptEvidenceInvalid(RuntimeError):
    """The bounded failure evidence cannot support a safe retry decision."""


def _json_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                raise FailedAttemptEvidenceInvalid
            result[name] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, FailedAttemptEvidenceInvalid):
        raise FailedAttemptEvidenceInvalid from None
    if not isinstance(value, dict):
        raise FailedAttemptEvidenceInvalid
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise FailedAttemptEvidenceInvalid
    try:
        rendered = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(rendered)
    except ValueError:
        raise FailedAttemptEvidenceInvalid from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FailedAttemptEvidenceInvalid
    return parsed.astimezone(timezone.utc)


def _optional_count(value: object) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise FailedAttemptEvidenceInvalid


def _systemd_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise FailedAttemptEvidenceInvalid
    matched = _SYSTEMD_UNIX_TIMESTAMP.fullmatch(value)
    if matched is None:
        raise FailedAttemptEvidenceInvalid
    fraction = (matched.group("fraction") or "").ljust(6, "0")
    try:
        return datetime.fromtimestamp(
            int(matched.group("seconds")) + int(fraction or "0") / 1_000_000,
            timezone.utc,
        )
    except (OverflowError, OSError, ValueError):
        raise FailedAttemptEvidenceInvalid from None


def _unit_properties(
    path: Path,
    invocation_id: str,
) -> tuple[datetime, datetime]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise FailedAttemptEvidenceInvalid from None
    for line in lines:
        if "=" not in line:
            raise FailedAttemptEvidenceInvalid
        name, value = line.split("=", 1)
        if name in result:
            raise FailedAttemptEvidenceInvalid
        result[name] = value
    if (
        set(result) != _UNIT_KEYS
        or result.get("InvocationID") != invocation_id
        or result.get("Result") not in _FAILURE_RESULTS
        or result.get("ActiveState") != "failed"
        or result.get("SubState") != "failed"
        or not (
            str(result.get("ExecMainCode", "")).isdigit()
            or result.get("ExecMainCode") in {"exited", "killed", "dumped"}
        )
        or not str(result.get("ExecMainStatus", "")).isdigit()
    ):
        raise FailedAttemptEvidenceInvalid
    manager_start = _systemd_timestamp(result.get("InactiveExitTimestamp"))
    manager_end = _systemd_timestamp(result.get("StateChangeTimestamp"))
    if manager_start > manager_end:
        raise FailedAttemptEvidenceInvalid
    return manager_start, manager_end


def _journal_realtime(value: object) -> datetime:
    if not isinstance(value, str) or not value.isdecimal():
        raise FailedAttemptEvidenceInvalid
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise FailedAttemptEvidenceInvalid from None


def _journal_invocation(
    path: Path,
    invocation_id: str,
) -> tuple[datetime, datetime]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                raise FailedAttemptEvidenceInvalid
            result[name] = value
        return result

    line_count = 0
    realtime: list[datetime] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise FailedAttemptEvidenceInvalid from None
    for raw in lines:
        if not raw.strip():
            continue
        line_count += 1
        try:
            row = json.loads(raw, object_pairs_hook=reject_duplicates)
        except (json.JSONDecodeError, FailedAttemptEvidenceInvalid):
            raise FailedAttemptEvidenceInvalid from None
        if not isinstance(row, dict) or row.get("_SYSTEMD_INVOCATION_ID") != invocation_id:
            raise FailedAttemptEvidenceInvalid
        realtime.append(_journal_realtime(row.get("__REALTIME_TIMESTAMP")))
    if line_count == 0:
        raise FailedAttemptEvidenceInvalid
    return min(realtime), max(realtime)


def _window_context(
    path: Path,
    *,
    invocation_id: str,
    expected_mode: str,
    expected_window_start: datetime,
    expected_window_end: datetime,
) -> None:
    document = _json_object(path)
    if (
        set(document) != _WINDOW_KEYS
        or document.get("invocationId") != invocation_id
        or document.get("mode") != expected_mode
        or _timestamp(document.get("windowStart")) != expected_window_start
        or _timestamp(document.get("windowEnd")) != expected_window_end
    ):
        raise FailedAttemptEvidenceInvalid


def verify(
    path: Path,
    *,
    invocation_id: str,
    expected_mode: str,
    expected_window_start: str,
    expected_window_end: str,
    expected_environment_id: str,
    expected_database: str,
    expected_role: str,
    unit_properties_path: Path,
    journal_path: Path,
    window_path: Path,
) -> dict[str, object]:
    if expected_mode not in {"initial", "refresh"}:
        raise FailedAttemptEvidenceInvalid
    if (
        _INVOCATION_ID.fullmatch(invocation_id) is None
        or _UUID.fullmatch(expected_environment_id) is None
        or not expected_database
        or len(expected_database) > 63
        or any(character.isspace() or ord(character) < 32 for character in expected_database)
        or not expected_role
        or len(expected_role) > 63
        or any(character.isspace() or ord(character) < 32 for character in expected_role)
    ):
        raise FailedAttemptEvidenceInvalid
    approved_window_start = _timestamp(expected_window_start)
    approved_window_end = _timestamp(expected_window_end)
    if (
        not approved_window_start
        < approved_window_end
        <= approved_window_start + timedelta(hours=4)
    ):
        raise FailedAttemptEvidenceInvalid

    manager_start, manager_end = _unit_properties(unit_properties_path, invocation_id)
    journal_start, journal_end = _journal_invocation(journal_path, invocation_id)
    _window_context(
        window_path,
        invocation_id=invocation_id,
        expected_mode=expected_mode,
        expected_window_start=approved_window_start,
        expected_window_end=approved_window_end,
    )

    document = _json_object(path)
    if set(document) != _ROOT_KEYS or document.get("loadMode") != expected_mode:
        raise FailedAttemptEvidenceInvalid

    if (
        document.get("environmentId") != expected_environment_id
        or document.get("databaseName") != expected_database
        or document.get("loginRole") != expected_role
        or document.get("sessionRole") != expected_role
        or document.get("readOnly") != "on"
        or document.get("isSuperuser") is not False
        or document.get("canLogin") is not True
        or document.get("canCreateDb") is not False
        or document.get("canCreateRole") is not False
        or document.get("canReplicate") is not False
        or document.get("canBypassRls") is not False
        or document.get("effectiveRoles") != ["brerc_monitor"]
        or document.get("directRoles") != ["brerc_monitor"]
    ):
        raise FailedAttemptEvidenceInvalid

    window_start = _timestamp(document.get("windowStart"))
    window_end = _timestamp(document.get("windowEnd"))
    if (
        window_start != approved_window_start
        or window_end != approved_window_end
        or not window_start < window_end <= window_start + timedelta(hours=4)
        or journal_start < window_start - _MAXIMUM_CLOCK_SKEW
        or journal_end > window_end + _MAXIMUM_CLOCK_SKEW
        or manager_start < window_start - _MAXIMUM_CLOCK_SKEW
        or manager_end > window_end + _MAXIMUM_CLOCK_SKEW
    ):
        raise FailedAttemptEvidenceInvalid

    jobs = document.get("jobs")
    job_count = document.get("jobCount")
    if (
        not isinstance(jobs, list)
        or type(job_count) is not int
        or job_count != len(jobs)
        or job_count not in {0, 1}
    ):
        raise FailedAttemptEvidenceInvalid
    if not jobs:
        return {
            "status": "verified",
            "mode": expected_mode,
            "invocationId": invocation_id,
            "environmentId": expected_environment_id,
            "jobCount": 0,
            "databaseState": "no-matching-job",
        }

    job = jobs[0]
    if not isinstance(job, dict) or set(job) != _JOB_KEYS:
        raise FailedAttemptEvidenceInvalid
    status = job.get("status")
    failure_code = job.get("failureCode")
    if status == "failed":
        if not isinstance(failure_code, str) or _FAILURE_CODE.fullmatch(failure_code) is None:
            raise FailedAttemptEvidenceInvalid
    elif status == "cancelled":
        if failure_code is not None:
            raise FailedAttemptEvidenceInvalid
    else:
        raise FailedAttemptEvidenceInvalid

    run_id = job.get("runId")
    if not isinstance(run_id, str) or _UUID.fullmatch(run_id) is None:
        raise FailedAttemptEvidenceInvalid
    started_at = _timestamp(job.get("startedAt"))
    finished_at = _timestamp(job.get("finishedAt"))
    if not window_start <= started_at <= finished_at <= window_end:
        raise FailedAttemptEvidenceInvalid
    for field in ("sourceRows", "candidateRows", "rowsWithheld"):
        _optional_count(job.get(field))

    release_id = job.get("releaseId")
    release_status = job.get("releaseStatus")
    cleanup_pending = job.get("cleanupPending")
    no_release = release_id is None and release_status is None and cleanup_pending is None
    terminal_release = (
        isinstance(release_id, str)
        and _UUID.fullmatch(release_id) is not None
        and release_status in {"failed", "discarded"}
        and cleanup_pending is False
    )
    if not (no_release or terminal_release):
        raise FailedAttemptEvidenceInvalid

    return {
        "status": "verified",
        "mode": expected_mode,
        "invocationId": invocation_id,
        "environmentId": expected_environment_id,
        "jobCount": 1,
        "runId": run_id,
        "databaseState": f"terminal-{status}",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-json", type=Path, required=True)
    parser.add_argument("--database-window-json", type=Path, required=True)
    parser.add_argument("--unit-properties", type=Path, required=True)
    parser.add_argument("--journal-json", type=Path, required=True)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--mode", choices=("initial", "refresh"), required=True)
    parser.add_argument("--expected-window-start", required=True)
    parser.add_argument("--expected-window-end", required=True)
    parser.add_argument("--expected-environment-id", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-role", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify(
            args.database_json,
            invocation_id=args.invocation_id,
            expected_mode=args.mode,
            expected_window_start=args.expected_window_start,
            expected_window_end=args.expected_window_end,
            expected_environment_id=args.expected_environment_id,
            expected_database=args.expected_database,
            expected_role=args.expected_role,
            unit_properties_path=args.unit_properties,
            journal_path=args.journal_json,
            window_path=args.database_window_json,
        )
    except FailedAttemptEvidenceInvalid:
        sys.stderr.write('{"code":"FAILED_ATTEMPT_EVIDENCE_INVALID","status":"failed"}\n')
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

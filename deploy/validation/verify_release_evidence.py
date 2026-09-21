#!/usr/bin/env python3
"""Fail closed unless one systemd invocation, DB and API name one release."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_INVOCATION_ID = re.compile(r"^[0-9a-f]{32}$")
_SYSTEMD_UNIX_TIMESTAMP = re.compile(r"^@(?P<seconds>[0-9]+)(?:\.(?P<fraction>[0-9]{1,6}))?$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATABASE_KEYS = {
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
    "runId",
    "releaseId",
    "activeReleaseId",
    "datasetVersion",
    "sourceDataAsOf",
    "candidateSha256",
    "baseReleaseId",
    "reusedActiveRelease",
    "sourceRows",
    "publicRecords",
    "distributionCells",
    "loadMode",
    "status",
    "startedAt",
    "finishedAt",
}
_WINDOW_KEYS = {"invocationId", "mode", "windowStart", "windowEnd"}
_MAXIMUM_CLOCK_SKEW = timedelta(seconds=60)


class EvidenceInvalid(RuntimeError):
    """The supplied evidence is incomplete, stale or internally inconsistent."""


def _json(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                raise EvidenceInvalid
            result[name] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, EvidenceInvalid):
        raise EvidenceInvalid from None


def _object(path: Path) -> dict[str, Any]:
    try:
        value = _json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, EvidenceInvalid):
        raise EvidenceInvalid from None
    if not isinstance(value, dict):
        raise EvidenceInvalid
    return value


def _unit_properties(path: Path) -> dict[str, str]:
    """Read the deliberately small ``systemctl show`` evidence file."""

    required = {
        "InvocationID",
        "Result",
        "ExecMainCode",
        "ExecMainStatus",
        "ActiveState",
        "SubState",
        "InactiveExitTimestamp",
        "StateChangeTimestamp",
    }
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise EvidenceInvalid from None
    for line in lines:
        if "=" not in line:
            raise EvidenceInvalid
        name, value = line.split("=", 1)
        if name in result:
            raise EvidenceInvalid
        result[name] = value
    if set(result) != required:
        raise EvidenceInvalid
    return result


def _systemd_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise EvidenceInvalid
    matched = _SYSTEMD_UNIX_TIMESTAMP.fullmatch(value)
    if matched is None:
        raise EvidenceInvalid
    fraction = (matched.group("fraction") or "").ljust(6, "0")
    try:
        return datetime.fromtimestamp(
            int(matched.group("seconds")) + int(fraction or "0") / 1_000_000,
            timezone.utc,
        )
    except (OverflowError, OSError, ValueError):
        raise EvidenceInvalid from None


def _journal_realtime(value: object) -> datetime:
    if not isinstance(value, str) or not value.isdecimal():
        raise EvidenceInvalid
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise EvidenceInvalid from None


def _journal_result(
    path: Path,
    invocation_id: str,
) -> tuple[dict[str, Any], datetime, datetime]:
    results: list[dict[str, Any]] = []
    realtime: list[datetime] = []
    line_count = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise EvidenceInvalid from None
    for raw in lines:
        if not raw.strip():
            continue
        line_count += 1
        try:
            row = _json(raw)
        except EvidenceInvalid:
            raise EvidenceInvalid from None
        if not isinstance(row, dict):
            raise EvidenceInvalid
        if row.get("_SYSTEMD_INVOCATION_ID") != invocation_id:
            raise EvidenceInvalid
        realtime.append(_journal_realtime(row.get("__REALTIME_TIMESTAMP")))
        message = row.get("MESSAGE")
        if not isinstance(message, str) or not message.startswith("{"):
            continue
        try:
            candidate = _json(message)
        except EvidenceInvalid:
            raise EvidenceInvalid from None
        if isinstance(candidate, dict) and {
            "status",
            "mode",
            "state",
            "runId",
            "releaseId",
            "candidateSha256",
            "activated",
            "reusedActiveRelease",
            "sourceRows",
            "publicRecords",
            "distributionCells",
        }.issubset(candidate):
            results.append(candidate)
    if line_count == 0 or len(results) != 1:
        raise EvidenceInvalid
    return results[0], min(realtime), max(realtime)


def _required_text(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceInvalid
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise EvidenceInvalid
    try:
        rendered = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(rendered)
    except ValueError:
        raise EvidenceInvalid from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceInvalid
    return parsed.astimezone(timezone.utc)


def _approved_name(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 63
        and not any(character.isspace() or ord(character) < 32 for character in value)
    )


def _window_context(
    path: Path,
    *,
    invocation_id: str,
    expected_mode: str,
) -> tuple[datetime, datetime]:
    context = _object(path)
    if (
        set(context) != _WINDOW_KEYS
        or context.get("invocationId") != invocation_id
        or context.get("mode") != expected_mode
    ):
        raise EvidenceInvalid
    window_start = _timestamp(context.get("windowStart"))
    window_end = _timestamp(context.get("windowEnd"))
    if not window_start < window_end <= window_start + timedelta(hours=4):
        raise EvidenceInvalid
    return window_start, window_end


def verify(
    *,
    invocation_id: str,
    expected_mode: str,
    expected_environment_id: str,
    expected_database: str,
    expected_role: str,
    unit_properties_path: Path,
    journal_path: Path,
    window_path: Path,
    database_path: Path,
    summary_path: Path,
    provenance_path: Path,
) -> dict[str, str]:
    if (
        _INVOCATION_ID.fullmatch(invocation_id) is None
        or _UUID.fullmatch(expected_environment_id) is None
        or not _approved_name(expected_database)
        or not _approved_name(expected_role)
    ):
        raise EvidenceInvalid
    if expected_mode not in {"initial", "refresh"}:
        raise EvidenceInvalid

    unit = _unit_properties(unit_properties_path)
    manager_start = _systemd_timestamp(unit.get("InactiveExitTimestamp"))
    manager_end = _systemd_timestamp(unit.get("StateChangeTimestamp"))
    loader, journal_start, journal_end = _journal_result(journal_path, invocation_id)
    window_start, window_end = _window_context(
        window_path,
        invocation_id=invocation_id,
        expected_mode=expected_mode,
    )
    database = _object(database_path)
    summary = _object(summary_path)
    provenance = _object(provenance_path)

    if set(database) != _DATABASE_KEYS:
        raise EvidenceInvalid
    run_id = _required_text(loader, "runId")
    release_id = _required_text(loader, "releaseId")
    dataset_version = _required_text(database, "datasetVersion")
    source_data_as_of = _required_text(database, "sourceDataAsOf")
    source_data_instant = _timestamp(source_data_as_of)
    provenance_data_instant = _timestamp(provenance.get("lastUpdated"))
    started_at = _timestamp(database.get("startedAt"))
    finished_at = _timestamp(database.get("finishedAt"))
    candidate_sha256 = _required_text(loader, "candidateSha256")
    if (
        _UUID.fullmatch(run_id) is None
        or _UUID.fullmatch(release_id) is None
        or _SHA256.fullmatch(candidate_sha256) is None
        or _SHA256.fullmatch(dataset_version) is None
        or not window_start <= started_at <= finished_at <= window_end
        or journal_start < window_start - _MAXIMUM_CLOCK_SKEW
        or journal_end > window_end + _MAXIMUM_CLOCK_SKEW
        or not manager_start <= manager_end
        or manager_start < window_start - _MAXIMUM_CLOCK_SKEW
        or manager_end > window_end + _MAXIMUM_CLOCK_SKEW
    ):
        raise EvidenceInvalid
    reused = loader.get("reusedActiveRelease")
    if type(reused) is not bool or database.get("reusedActiveRelease") is not reused:
        raise EvidenceInvalid
    base_release_id = database.get("baseReleaseId")
    if expected_mode == "initial":
        mode_shape_valid = reused is False and base_release_id is None
    else:
        mode_shape_valid = (
            isinstance(base_release_id, str)
            and _UUID.fullmatch(base_release_id) is not None
            and (
                (reused and base_release_id == release_id)
                or (not reused and base_release_id != release_id)
            )
        )

    for field in ("sourceRows", "publicRecords", "distributionCells"):
        value = loader.get(field)
        if type(value) is not int or value < 0 or database.get(field) != value:
            raise EvidenceInvalid

    expected_unit_state = (
        ("active", "exited") if expected_mode == "initial" else ("inactive", "dead")
    )
    if (
        unit.get("InvocationID") != invocation_id
        or unit.get("Result") != "success"
        or unit.get("ExecMainCode") not in {"1", "exited"}
        or unit.get("ExecMainStatus") != "0"
        or (unit.get("ActiveState"), unit.get("SubState")) != expected_unit_state
        or database.get("environmentId") != expected_environment_id
        or database.get("databaseName") != expected_database
        or database.get("loginRole") != expected_role
        or database.get("sessionRole") != expected_role
        or database.get("readOnly") != "on"
        or database.get("isSuperuser") is not False
        or database.get("canLogin") is not True
        or database.get("canCreateDb") is not False
        or database.get("canCreateRole") is not False
        or database.get("canReplicate") is not False
        or database.get("canBypassRls") is not False
        or database.get("effectiveRoles") != ["brerc_monitor"]
        or database.get("directRoles") != ["brerc_monitor"]
        or loader.get("status") != "ok"
        or loader.get("state") != "succeeded"
        or loader.get("mode") != expected_mode
        or loader.get("activated") is not True
        or not mode_shape_valid
        or database.get("runId") != run_id
        or database.get("releaseId") != release_id
        or database.get("activeReleaseId") != release_id
        or database.get("loadMode") != expected_mode
        or database.get("status") != "succeeded"
        or database.get("candidateSha256") != candidate_sha256
        or summary.get("releaseId") != release_id
        or provenance.get("releaseId") != release_id
        or summary.get("datasetVersion") != dataset_version
        or provenance.get("datasetVersion") != dataset_version
        or provenance_data_instant != source_data_instant
    ):
        raise EvidenceInvalid

    return {
        "status": "verified",
        "mode": expected_mode,
        "runId": run_id,
        "releaseId": release_id,
        "datasetVersion": dataset_version,
        "sourceDataAsOf": source_data_as_of,
        "candidateSha256": candidate_sha256,
        "invocationId": invocation_id,
        "environmentId": expected_environment_id,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile one systemd loader invocation with database and API evidence."
    )
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--mode", required=True, choices=("initial", "refresh"))
    parser.add_argument("--expected-environment-id", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-role", required=True)
    parser.add_argument("--unit-properties", type=Path, required=True)
    parser.add_argument("--journal-json", type=Path, required=True)
    parser.add_argument("--database-window-json", type=Path, required=True)
    parser.add_argument("--database-json", type=Path, required=True)
    parser.add_argument("--api-summary-json", type=Path, required=True)
    parser.add_argument("--api-provenance-json", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify(
            invocation_id=args.invocation_id,
            expected_mode=args.mode,
            expected_environment_id=args.expected_environment_id,
            expected_database=args.expected_database,
            expected_role=args.expected_role,
            unit_properties_path=args.unit_properties,
            journal_path=args.journal_json,
            window_path=args.database_window_json,
            database_path=args.database_json,
            summary_path=args.api_summary_json,
            provenance_path=args.api_provenance_json,
        )
    except EvidenceInvalid:
        sys.stderr.write('{"code":"RELEASE_EVIDENCE_INVALID","status":"failed"}\n')
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail closed unless one systemd invocation, DB and API name one release."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_INVOCATION_ID = re.compile(r"^[0-9a-f]{32}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _journal_result(path: Path, invocation_id: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
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
        if not isinstance(row, dict) or row.get("_SYSTEMD_INVOCATION_ID") != invocation_id:
            raise EvidenceInvalid
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
    return results[0]


def _required_text(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceInvalid
    return value


def verify(
    *,
    invocation_id: str,
    expected_mode: str,
    unit_properties_path: Path,
    journal_path: Path,
    database_path: Path,
    summary_path: Path,
    provenance_path: Path,
) -> dict[str, str]:
    if _INVOCATION_ID.fullmatch(invocation_id) is None:
        raise EvidenceInvalid
    if expected_mode not in {"initial", "refresh"}:
        raise EvidenceInvalid

    unit = _unit_properties(unit_properties_path)
    loader = _journal_result(journal_path, invocation_id)
    database = _object(database_path)
    summary = _object(summary_path)
    provenance = _object(provenance_path)

    run_id = _required_text(loader, "runId")
    release_id = _required_text(loader, "releaseId")
    dataset_version = _required_text(database, "datasetVersion")
    candidate_sha256 = _required_text(loader, "candidateSha256")
    if (
        _UUID.fullmatch(run_id) is None
        or _UUID.fullmatch(release_id) is None
        or _SHA256.fullmatch(candidate_sha256) is None
        or _SHA256.fullmatch(dataset_version) is None
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

    if (
        unit.get("InvocationID") != invocation_id
        or unit.get("Result") != "success"
        or unit.get("ExecMainCode") not in {"1", "exited"}
        or unit.get("ExecMainStatus") != "0"
        or unit.get("ActiveState") != "inactive"
        or unit.get("SubState") != "dead"
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
    ):
        raise EvidenceInvalid

    return {
        "status": "verified",
        "mode": expected_mode,
        "runId": run_id,
        "releaseId": release_id,
        "datasetVersion": dataset_version,
        "candidateSha256": candidate_sha256,
        "invocationId": invocation_id,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile one systemd loader invocation with database and API evidence."
    )
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--mode", required=True, choices=("initial", "refresh"))
    parser.add_argument("--unit-properties", type=Path, required=True)
    parser.add_argument("--journal-json", type=Path, required=True)
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
            unit_properties_path=args.unit_properties,
            journal_path=args.journal_json,
            database_path=args.database_json,
            summary_path=args.api_summary_json,
            provenance_path=args.api_provenance_json,
        )
    except EvidenceInvalid:
        sys.stderr.write(
            '{"code":"RELEASE_EVIDENCE_INVALID","status":"failed"}\n'
        )
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

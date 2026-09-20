"""Redacted operator CLI for full-snapshot and future incremental loads."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Sequence
from types import ModuleType

from etl.source_contract import (
    BRERC_MAIN_DATA_DASH,
    IncrementalLoadBlocked,
)
from etl.source_contract import (
    LoadMode as SourceLoadMode,
)

from .config import load_loader_config
from .errors import (
    IncrementalSourceContractBlocked,
    LoaderConfigurationError,
    LoaderCoordinatorUnavailable,
    LoaderError,
    LoaderExecutionFailed,
)
from .models import LoaderRunReport, LoadMode


def _safe_failure(code: str) -> str:
    return json.dumps(
        {"status": "failed", "code": code},
        sort_keys=True,
        separators=(",", ":"),
    )


class _SafeArgumentParser(argparse.ArgumentParser):
    """Reject a command without echoing its potentially sensitive value."""

    def error(self, _message: str) -> None:
        self.exit(2, _safe_failure("LOADER_CLI_USAGE_INVALID") + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="brerc-load",
        description="Build and atomically activate one validated BRERC public-data release.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("initial", "build a complete candidate from the reviewed source view"),
        (
            "refresh",
            "replace the active release from one complete reviewed source snapshot",
        ),
        ("incremental", "blocked until BRERC approves an incremental source contract"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--config",
            required=True,
            help="path to the credential-free loader configuration",
        )
    return parser


def _load_coordinator() -> ModuleType:
    """Private test seam and the only import of the future DB coordinator."""
    return importlib.import_module("brerc_loader.postgres")


def _run_coordinator(config: object, mode: LoadMode) -> LoaderRunReport:
    try:
        module = _load_coordinator()
    except ImportError:
        raise LoaderCoordinatorUnavailable() from None
    operation = getattr(module, "run_load", None)
    if not callable(operation):
        raise LoaderCoordinatorUnavailable()
    try:
        report = operation(config, mode)
    except LoaderError:
        raise
    except Exception:
        # Driver exceptions can include SQL, credentials or row values. Convert
        # them here rather than allowing argparse/shell logging to display them.
        raise LoaderExecutionFailed() from None
    if not isinstance(report, LoaderRunReport) or report.mode is not mode:
        raise LoaderExecutionFailed()
    return report


def _safe_success(report: LoaderRunReport) -> dict[str, object]:
    return {
        "status": "ok",
        "mode": report.mode.value,
        "state": report.state.value,
        "runId": report.run_id,
        "releaseId": report.release_id,
        "sourceRows": report.source_rows,
        "publicRecords": report.public_records,
        "distributionCells": report.distribution_cells,
        "candidateSha256": report.candidate_sha256,
        "activated": report.activated,
        "reusedActiveRelease": report.reused_active_release,
    }


def _assert_mode_available(mode: LoadMode) -> None:
    if mode is not LoadMode.INCREMENTAL:
        return
    try:
        # The source contract deliberately owns its own enum. Convert by value
        # rather than weakening either boundary's runtime type check.
        BRERC_MAIN_DATA_DASH.require_mode(SourceLoadMode(mode.value))
    except IncrementalLoadBlocked:
        raise IncrementalSourceContractBlocked() from None


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    mode = LoadMode(args.command)
    try:
        # This runs before config parsing and before the coordinator import. The
        # current 39-column BRERC contract can therefore never reach a source or
        # target connection through the incremental command.
        _assert_mode_available(mode)
        config = load_loader_config(args.config)
        report = _run_coordinator(config, mode)
    except LoaderConfigurationError as exc:
        sys.stderr.write(_safe_failure(exc.code) + "\n")
        return 2
    except LoaderError as exc:
        sys.stderr.write(_safe_failure(exc.code) + "\n")
        return 3
    except Exception:
        sys.stderr.write(_safe_failure("LOADER_EXECUTION_FAILED") + "\n")
        return 4

    sys.stdout.write(
        json.dumps(_safe_success(report), sort_keys=True, separators=(",", ":")) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

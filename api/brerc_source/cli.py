"""Minimal operator CLI for the trusted BRERC PostgreSQL source connector.

Only structural preflight is exposed. There are deliberately no options for a
DSN, password, SQL query, force mode, or skipping contract/identity checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from etl.source_contract import BRERC_MAIN_DATA_DASH

from .config import SourceConfigError, load_source_config
from .errors import TrustedSourceConnectorError
from .postgres import TrustedPostgreSQLSourceConnector


class _SafeArgumentParser(argparse.ArgumentParser):
    """Never echo a rejected command-line value into an operator log."""

    def error(self, _message: str) -> None:
        self.exit(2, _safe_failure("SOURCE_CLI_USAGE_INVALID") + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="brerc-source",
        description="Run a read-only structural preflight of BRERC's reviewed source view.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser(
        "preflight",
        help="verify the live source structure in one read-only snapshot",
    )
    preflight.add_argument(
        "--config",
        required=True,
        help="path to the credential-free connector configuration",
    )
    return parser


def _safe_success(report: object) -> dict[str, object]:
    """Copy only the explicitly approved, non-row preflight report fields."""
    return {
        "status": "ok",
        "contractVersion": report.contract_version,
        "contractSha256": report.contract_sha256,
        "observedDefinitionSha256": report.observed_definition_sha256,
        "observedIdentitySha256": report.observed_identity_sha256,
        "confirmedColumns": report.confirmed_columns,
        "resultColumns": list(report.result_columns),
        "releaseReady": report.release_ready,
    }


def _safe_failure(code: str) -> str:
    return json.dumps(
        {"status": "failed", "code": code},
        sort_keys=True,
        separators=(",", ":"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_source_config(args.config)
        connector = TrustedPostgreSQLSourceConnector.from_config(config)
        report = connector.preflight(
            source_contract=BRERC_MAIN_DATA_DASH,
            columns=config.column_map,
        )
    except SourceConfigError:
        print(_safe_failure("SOURCE_CONFIGURATION_INVALID"), file=sys.stderr)
        return 2
    except TrustedSourceConnectorError as exc:
        print(_safe_failure(exc.code), file=sys.stderr)
        return 3
    except Exception:
        # Database adapters may carry SQL, bound values or connection details
        # in their exception strings. Unexpected failures are intentionally
        # reduced to one stable code at this outermost boundary.
        print(_safe_failure("SOURCE_PREFLIGHT_FAILED"), file=sys.stderr)
        return 4

    print(json.dumps(_safe_success(report), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

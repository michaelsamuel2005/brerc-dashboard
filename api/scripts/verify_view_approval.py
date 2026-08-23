#!/usr/bin/env python3
"""Validate a completed BRERC view-approval envelope.

Structural validation proves that the approval is internally consistent and
matches this repository's source contract.  Supplying ``--capture`` additionally
proves that it matches one raw PostgreSQL capture.  Production still requires
the trusted connector to repeat this comparison in the extraction snapshot.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from etl.source_contract import BRERC_MAIN_DATA_DASH  # noqa: E402
from etl.view_identity import ViewDefinitionApproval, ViewIdentityError  # noqa: E402
from scripts.prepare_view_approval import read_json, validate_capture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("approval", type=Path, help="completed BRERC approval JSON")
    parser.add_argument("--capture", type=Path, help="optional matching raw capture JSON")
    parser.add_argument(
        "--expected-source-environment",
        required=True,
        help="environment name independently confirmed by BRERC",
    )
    args = parser.parse_args()
    try:
        document = read_json(args.approval)
        approval = ViewDefinitionApproval.from_document(document)
        approval.assert_current()
        dataclasses.replace(
            BRERC_MAIN_DATA_DASH,
            required_source_environment=args.expected_source_environment,
            view_approval=approval,
        )
        if args.capture is not None:
            evidence = validate_capture(read_json(args.capture))
            differences = approval.differences(evidence.observation)
            if approval.captured_at_utc != evidence.captured_at_utc:
                differences += ("captured timestamp differs from the approved capture",)
            if approval.capture_evidence_sha256 != evidence.capture_sha256:
                differences += ("capture-evidence digest differs",)
            if approval.catalog_columns_sha256 != evidence.catalog_columns_sha256:
                differences += ("catalogue-column digest differs",)
            if differences or approval.identity_sha256 != evidence.identity_sha256:
                rendered = "; ".join(differences) or "identity digest differs"
                raise ViewIdentityError(f"approval does not match capture: {rendered}")
        print("OK: approval envelope is current and matches the BRERC source contract.")
        print(f"    source version: {approval.source_version}")
        print(f"    definition SHA-256: {approval.definition_sha256}")
        print(f"    identity SHA-256: {approval.identity_sha256}")
        print(f"    approved by: {approval.approved_by} ({approval.approver_role})")
        if args.capture is None:
            print("    NOTE: no raw capture was supplied; live database equality was not checked.")
        return 0
    except (OSError, ViewIdentityError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

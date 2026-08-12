#!/usr/bin/env python3
"""Turn BRERC's raw catalogue capture into a sanitised pending approval.

This command never grants approval.  It verifies the captured view identity and
39-column contract, removes the raw SQL/database/role/OID from the output, and
creates a template that a named BRERC data owner must complete and return.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from etl.source_contract import (  # noqa: E402
    BRERC_MAIN_DATA_DASH,
    SourceColumn,
    SourceMetadata,
)
from etl.view_identity import ViewCaptureEvidence, ViewIdentityError  # noqa: E402

MAX_CAPTURE_BYTES = 10 * 1024 * 1024


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ViewIdentityError(f"JSON object contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ViewIdentityError(f"JSON contains non-finite number {value}")


def read_json(path: Path) -> object:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ViewIdentityError(f"cannot inspect evidence file: {exc}") from exc
    if size <= 0 or size > MAX_CAPTURE_BYTES:
        raise ViewIdentityError(
            f"evidence file size must be between 1 and {MAX_CAPTURE_BYTES} bytes"
        )
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ViewIdentityError) as exc:
        raise ViewIdentityError(f"evidence file is not valid strict UTF-8 JSON: {exc}") from exc


def validate_capture(document: object) -> ViewCaptureEvidence:
    evidence = ViewCaptureEvidence.from_document(document)
    metadata = SourceMetadata(
        schema=evidence.observation.schema,
        name=evidence.observation.name,
        object_type="view",
        columns=tuple(
            SourceColumn(
                name=str(column["name"]),
                data_type=str(column["type"]),
                character_maximum_length=column["length"],
                numeric_precision=column["precision"],
                numeric_scale=column["scale"],
            )
            for column in evidence.columns_document
        ),
        observed_view=evidence.observation,
        observed_catalog_columns_sha256=evidence.catalog_columns_sha256,
    )
    BRERC_MAIN_DATA_DASH.validate_initial(metadata)
    if evidence.columns_sha256 != BRERC_MAIN_DATA_DASH.columns_sha256():
        raise ViewIdentityError("captured column digest differs from the source contract")
    return evidence


def render_pending(evidence: ViewCaptureEvidence) -> str:
    document = evidence.pending_approval_document()
    document["clientReferenceDocumentSha256"] = (
        BRERC_MAIN_DATA_DASH.client_reference_document_sha256
    )
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="raw JSON emitted by the capture SQL")
    parser.add_argument(
        "--output",
        type=Path,
        help="write the sanitised pending approval here; defaults to stdout",
    )
    args = parser.parse_args()
    try:
        evidence = validate_capture(read_json(args.capture))
        rendered = render_pending(evidence)
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
            args.output.chmod(0o600)
            print(f"Wrote pending BRERC approval template to {args.output}.")
        print(
            "PENDING ONLY: a named BRERC data owner must review the captured SQL "
            "and complete the approval fields.",
            file=sys.stderr,
        )
        return 0
    except (OSError, ViewIdentityError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

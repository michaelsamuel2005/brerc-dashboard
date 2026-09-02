#!/usr/bin/env python3
"""Generate the synthetic ETL payload consumed by the browser contract test.

This is the executable seam between Python and TypeScript. Backend CI checks
that the committed JSON is byte-for-byte current; Vitest parses that same JSON
with the production Zod schemas. The rows below are entirely synthetic.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from etl.pipeline import ColumnMap, build_candidate_payloads, run_pipeline  # noqa: E402
from etl.policy import DEVELOPMENT_POLICY  # noqa: E402

COLUMNS = ColumnMap(
    record_id="record_id",
    species_id="species_id",
    scientific_name="scientific_name",
    grid_ref="grid_ref",
    year="year",
    common_name="common_name",
    abundance="abundance",
    record_type="record_type",
    verified="verified",
)


def synthetic_row(record_id: str, grid_ref: str, year: int, verified: str) -> dict[str, object]:
    return {
        "record_id": record_id,
        "species_id": "5088",
        "scientific_name": "Anguis fragilis",
        "common_name": "Slow-worm",
        "grid_ref": grid_ref,
        "year": year,
        "abundance": "1",
        "record_type": "field observation",
        "verified": verified,
    }


def scenario(*, verification_available: bool) -> dict[str, object]:
    columns = COLUMNS
    policy = DEVELOPMENT_POLICY
    rows = [
        synthetic_row("synthetic-1", "ST587721", 2023, "Accepted - correct"),
        synthetic_row("synthetic-2", "ST588722", 2024, "Not accepted"),
    ]
    if not verification_available:
        policy = replace(
            DEVELOPMENT_POLICY,
            verification_publication_mode="unavailable",
            publish_record_verification=False,
            accepted_verification_values=None,
        )
        columns = ColumnMap(
            record_id=COLUMNS.record_id,
            species_id=COLUMNS.species_id,
            scientific_name=COLUMNS.scientific_name,
            grid_ref=COLUMNS.grid_ref,
            year=COLUMNS.year,
            common_name=COLUMNS.common_name,
            abundance=COLUMNS.abundance,
            record_type=COLUMNS.record_type,
            verified=None,
        )
        rows = [{key: value for key, value in row.items() if key != "verified"} for row in rows]

    records, report = run_pipeline(rows, columns, policy=policy)
    preview = build_candidate_payloads(records, report, species_id="5088")
    return {
        "cells": preview["cells"],
        "records": preview["records"],
        "verificationAvailable": report.verification_available,
    }


def render() -> str:
    document = {
        "schemaVersion": 1,
        "verifiedAvailable": scenario(verification_available=True),
        "verifiedUnavailable": scenario(verification_available=False),
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        type=Path,
        help="fail unless this committed fixture exactly matches current ETL output",
    )
    args = parser.parse_args()
    expected = render()
    if args.check is None:
        sys.stdout.write(expected)
        return 0
    try:
        actual = args.check.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL: cannot read browser contract fixture: {exc}", file=sys.stderr)
        return 1
    if actual != expected:
        print(
            "FAIL: browser contract fixture is stale. Regenerate it with "
            "python api/scripts/generate_browser_contract_fixture.py and review the diff.",
            file=sys.stderr,
        )
        return 1
    print("OK: committed browser contract fixture matches current ETL output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

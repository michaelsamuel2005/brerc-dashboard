"""The sensitivity column is mandatory, and its absence must stop the run.

WHY THIS FILE EXISTS (decision D-023, 16 August 2026)
----------------------------------------------------
The superseded ETL path treated the source view's ``sensitive`` column as
optional.  ``classify_chunk()`` guarded it with ``if "sensitive" in df.columns``
and fell back to "no record is sensitive" otherwise, and the sensitive-species
list loader returned empty sets when its file was missing, commented as a "safe
fallback".  Executed against a record marked ``sensitive = 'Yes'``:

===============================================  ==================  ==============
input                                            resolution assigned  classified
===============================================  ==================  ==============
column present, value 'Yes'                      1000 m              sensitive
same record, column named 'Sensitive'             100 m              NOT sensitive
column absent entirely                            100 m              NOT sensitive
listed sensitive taxon, species file missing      100 m              NOT sensitive
===============================================  ==================  ==============

100 m is full precision.  No exception or warning was raised in any failing
case, so a protected location would have been published silently and the run
would have reported success.  This is the failure mode the whole safety
boundary exists to prevent, and the reason the canonical implementation was
adopted.

Column-shape rejection itself is already exercised by
``test_source_contract.TestConfirmedManifest`` — in particular
``test_missing_renamed_extra_and_wrongly_typed_columns_all_fail``, which uses
``sensitive`` as its worked example.  This file deliberately does NOT duplicate
that.  It records the specific comparison the decision rests on, so that the
protection is discoverable from the hazard rather than only from the schema
rules, and it asserts the two properties that matter operationally:

1. the run is refused BEFORE any record row is read, rather than degrading to a
   permissive default; and
2. the refusal is a hard failure, not a warning a caller could ignore.

If a future change makes any assertion here pass only because the column became
optional again, that change has reintroduced the D-023 defect.
"""

from __future__ import annotations

import dataclasses
import inspect
import unittest

from etl.source_contract import BRERC_MAIN_DATA_DASH, SourceContractError, SourceMetadata
from tests.test_source_contract import metadata_from_contract

#: The exact shapes that the superseded implementation accepted and published at
#: 100 m.  Naming them here keeps the hazard legible to a maintainer who has
#: never seen the old code.
SENSITIVITY_COLUMN = "sensitive"


def _without_sensitivity_column(metadata: SourceMetadata) -> SourceMetadata:
    """The source view stops supplying the column at all."""
    return dataclasses.replace(
        metadata,
        columns=tuple(column for column in metadata.columns if column.name != SENSITIVITY_COLUMN),
    )


def _sensitivity_column_renamed(metadata: SourceMetadata, new_name: str) -> SourceMetadata:
    """The column still exists but under a different name.

    This is not hypothetical: the live view's field naming was raised with the
    project advisor before D-023, and a case-different or reworded column is
    exactly what a schema migration produces.
    """
    return dataclasses.replace(
        metadata,
        columns=tuple(
            dataclasses.replace(column, name=new_name)
            if column.name == SENSITIVITY_COLUMN
            else column
            for column in metadata.columns
        ),
    )


class TestSensitivityColumnIsMandatory(unittest.TestCase):
    def test_the_reviewed_contract_actually_requires_the_column(self) -> None:
        """Guard the premise: the column must be in the contract to be enforced."""
        names = [column.name for column in BRERC_MAIN_DATA_DASH.columns]
        self.assertIn(SENSITIVITY_COLUMN, names)
        self.assertEqual(names.count(SENSITIVITY_COLUMN), 1)

    def test_a_source_without_the_column_is_refused(self) -> None:
        with self.assertRaises(SourceContractError) as refused:
            BRERC_MAIN_DATA_DASH.validate_initial(
                _without_sensitivity_column(metadata_from_contract())
            )
        # The failure must name the schema mismatch rather than surfacing as a
        # generic error a caller might retry past.
        self.assertIn("SOURCE_SCHEMA_MISMATCH", str(refused.exception))

    def test_a_renamed_column_is_refused_rather_than_ignored(self) -> None:
        """The superseded gate's worst case: present, readable, silently unused."""
        for replacement in ("Sensitive", "SENSITIVE", "sensitivity", "is_sensitive"):
            with (
                self.subTest(replacement=replacement),
                self.assertRaises(SourceContractError),
            ):
                BRERC_MAIN_DATA_DASH.validate_initial(
                    _sensitivity_column_renamed(metadata_from_contract(), replacement)
                )

    def test_refusal_happens_before_any_row_is_read(self) -> None:
        """``validate_initial`` takes metadata only — it cannot have seen a row.

        The operational property is that a source missing the column produces no
        published output at all.  That holds because the sole input to this
        check is catalogue metadata, so no record has been fetched at the point
        the run is refused.  Asserting the signature keeps that guarantee from
        being quietly weakened into a post-read check.
        """
        parameters = list(inspect.signature(BRERC_MAIN_DATA_DASH.validate_initial).parameters)
        self.assertEqual(parameters, ["metadata"])

    def test_the_matching_source_is_accepted_so_the_test_can_fail(self) -> None:
        """Negative control.

        Without this, every assertion above would still pass if
        ``validate_initial`` raised unconditionally, and the file would prove
        nothing.
        """
        report = BRERC_MAIN_DATA_DASH.validate_initial(metadata_from_contract())
        self.assertEqual(report.confirmed_columns, len(BRERC_MAIN_DATA_DASH.columns))


if __name__ == "__main__":
    unittest.main()

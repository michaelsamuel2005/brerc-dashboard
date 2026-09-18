"""Bounded-memory row transformation and geometry evidence."""

from __future__ import annotations

import dataclasses
import unittest

from etl.gridref import square_bounds
from etl.pipeline import ColumnMap
from etl.policy import PublicationPolicy
from etl.streaming import StreamingTransformError, begin_streaming_transform
from tests.test_source_contract import (
    RELEASE_READY_CONTRACT,
    VIEW_DICTIONARY,
    VIEW_POLICY,
    metadata_from_contract,
    view_row,
)

COLUMNS = ColumnMap(
    record_id="unique_no",
    species_id="species_no",
    scientific_name="scientific_name",
    grid_ref="grid_ref",
    year="year_end",
    common_name="common_name",
    abundance="abundance",
    record_type="record_type",
    licence="licence",
    sensitivity="sensitive",
)
SECRET = b"streaming-reconciliation-secret-32-bytes-minimum"


def session(*, policy: PublicationPolicy | None = None):
    return begin_streaming_transform(
        columns=COLUMNS,
        source_contract=RELEASE_READY_CONTRACT,
        source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
        source_result_columns=(*COLUMNS.required(), *COLUMNS.optional()),
        policy=policy or VIEW_POLICY,
        reconciliation_secret=SECRET,
        dictionary=VIEW_DICTIONARY,
    )


def source_row(**changes):
    return view_row(**changes)


class TestGridSquareBounds(unittest.TestCase):
    def test_public_bng_squares_have_exact_epsg27700_bounds(self):
        self.assertEqual(square_bounds("ST5872"), (358000, 172000, 359000, 173000))
        self.assertEqual(square_bounds("ST587721"), (358700, 172100, 358800, 172200))
        self.assertEqual(square_bounds("ST57"), (350000, 170000, 360000, 180000))

    def test_non_public_shapes_are_refused(self):
        for value in ("", "ST", "ST57A", "not-a-grid"):
            with self.subTest(value=value):
                self.assertIsNone(square_bounds(value))


class TestStreamingTransform(unittest.TestCase):
    def test_only_hmac_tokens_and_generalised_safe_fields_leave_the_row_call(self):
        transform = session()
        row = source_row(unique_no="123.00", grid_ref="ST587721", sensitive="Yes")
        disposition = transform.transform_batch((row,))[0]
        self.assertEqual(disposition.record.grid_ref, "ST5872")
        self.assertEqual(disposition.record.precision_metres, 1000)
        self.assertEqual(disposition.cell_id, "ST5872")
        rendered = repr(disposition)
        for private in ("123.00", "ST587721", "Yes"):
            self.assertNotIn(private, rendered)
        self.assertEqual(len(disposition.source_token), 64)
        self.assertEqual(len(disposition.source_fingerprint), 64)

    def test_batches_do_not_apply_global_suppression(self):
        policy = dataclasses.replace(
            VIEW_POLICY,
            suppression_mode="minimum-count",
            min_records_per_cell=3,
        ).with_approval(
            approved_by="Synthetic test approver",
            approver_role="Test data owner",
            approver_organisation="BRERC",
            evidence_reference="BRERC-TEST-STREAM-001",
            approved_on=VIEW_POLICY.approved_on or "2026-08-14",
            review_due=VIEW_POLICY.review_due or "2027-08-14",
        )
        transform = session(policy=policy)
        first = transform.transform_batch((source_row(unique_no="1"), source_row(unique_no="2")))
        second = transform.transform_batch((source_row(unique_no="3"),))
        self.assertEqual(len(first + second), 3)
        self.assertTrue(all(item.record is not None for item in first + second))
        report = transform.finish()
        self.assertEqual(report.rows_in, 3)
        self.assertEqual(report.records_public, 3)
        self.assertEqual(report.records_suppressed, 0)

    def test_withheld_rows_have_one_fixed_reason_and_no_safe_record(self):
        transform = session()
        disposition = transform.transform_batch((source_row(unique_no="1", year_end="bad"),))[0]
        self.assertIsNone(disposition.record)
        self.assertEqual(disposition.withheld_reason, "unusable-year")
        self.assertIsNone(disposition.cell_id)

    def test_source_tokens_are_canonical_and_domain_separated_from_fingerprints(self):
        first = session().transform_batch((source_row(unique_no="1"),))[0]
        second = session().transform_batch((source_row(unique_no="1.00"),))[0]
        self.assertEqual(first.source_token, second.source_token)
        self.assertNotEqual(first.source_token, first.source_fingerprint)

    def test_wrong_header_and_short_secret_fail_without_echoing_values(self):
        with self.assertRaises(StreamingTransformError):
            begin_streaming_transform(
                columns=COLUMNS,
                source_contract=RELEASE_READY_CONTRACT,
                source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
                source_result_columns=(*COLUMNS.required(), *COLUMNS.optional()),
                policy=VIEW_POLICY,
                reconciliation_secret=b"short",
                dictionary=VIEW_DICTIONARY,
            )
        transform = session()
        row = source_row(unique_no="PRIVATE-IDENTIFIER")
        row["unexpected"] = "PRIVATE-COMMENT"
        with self.assertRaisesRegex(Exception, "SOURCE_RESULT_ROW_MISMATCH") as caught:
            transform.transform_batch((row,))
        self.assertNotIn("PRIVATE-COMMENT", str(caught.exception))

    def test_finish_is_single_use(self):
        transform = session()
        transform.finish()
        with self.assertRaises(StreamingTransformError):
            transform.finish()
        with self.assertRaises(StreamingTransformError):
            transform.transform_batch(())


if __name__ == "__main__":
    unittest.main()

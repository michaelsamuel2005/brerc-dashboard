"""Deterministic release digest tests."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from brerc_loader.digest import PUBLIC_RELEASE_DIGEST_TABLES, DigestTable, ReleaseDigest
from brerc_loader.errors import LoaderCandidateInvalid

PROFILE = (
    DigestTable("records", ("id", "n", "amount", "day", "token")),
    DigestTable("empty_table", ("id",)),
)


def build(batch_size: int, *, run_metadata: object = None) -> str:
    # Candidate UUIDs/job timestamps are deliberately not columns in PROFILE.
    del run_metadata
    source = [
        ("a", 1, Decimal("1.00"), date(2024, 1, 1), b"\x01"),
        ("b", 2, Decimal("2.50"), date(2024, 1, 2), b"\x02"),
        ("c", 3, Decimal("3.00"), date(2024, 1, 3), b"\x03"),
    ]
    digest = ReleaseDigest(PROFILE)
    digest.begin("records", PROFILE[0].columns)
    for start in range(0, len(source), batch_size):
        digest.rows(source[start : start + batch_size])
    digest.end()
    digest.begin("empty_table", PROFILE[1].columns)
    digest.rows(())
    digest.end()
    return digest.hexdigest()


def build_public_release_digest(sensitive_record_action: str) -> str:
    digest = ReleaseDigest(PUBLIC_RELEASE_DIGEST_TABLES)
    release = PUBLIC_RELEASE_DIGEST_TABLES[0]
    digest.begin(release.name, release.columns)
    digest.rows(
        (
            (
                "safe-v1",
                "dataset-v1",
                sensitive_record_action,
                "none",
                1,
                False,
                False,
                False,
                False,
                False,
                False,
                "BRERC",
            ),
        )
    )
    digest.end()
    for table in PUBLIC_RELEASE_DIGEST_TABLES[1:]:
        digest.begin(table.name, table.columns)
        digest.rows(())
        digest.end()
    return digest.hexdigest()


class TestReleaseDigest(unittest.TestCase):
    def test_real_public_profile_excludes_run_and_snapshot_timestamps(self):
        columns = PUBLIC_RELEASE_DIGEST_TABLES[0].columns
        self.assertNotIn("release_id", columns)
        self.assertNotIn("source_data_as_of", columns)
        self.assertNotIn("created_at", columns)

    def test_real_public_profile_binds_the_sensitive_record_action(self):
        columns = PUBLIC_RELEASE_DIGEST_TABLES[0].columns
        self.assertEqual(columns[2], "sensitive_record_action")
        self.assertNotEqual(
            build_public_release_digest("generalise"),
            build_public_release_digest("withhold"),
        )

    def test_batch_boundaries_and_run_metadata_do_not_change_digest(self):
        self.assertEqual(build(1), build(2))
        self.assertEqual(build(2), build(5000))
        self.assertEqual(
            build(1, run_metadata=("candidate-a", datetime(2025, 1, 1, tzinfo=timezone.utc))),
            build(2, run_metadata=("candidate-b", datetime(2026, 1, 1, tzinfo=timezone.utc))),
        )

    def test_order_or_value_change_changes_the_digest(self):
        profile = (DigestTable("t", ("a",)),)
        normal = ReleaseDigest(profile)
        normal.begin("t", ("a",))
        normal.rows(((1,), (2,)))
        normal.end()

        reversed_rows = ReleaseDigest(profile)
        reversed_rows.begin("t", ("a",))
        reversed_rows.rows(((2,), (1,)))
        reversed_rows.end()
        self.assertNotEqual(normal.hexdigest(), reversed_rows.hexdigest())

    def test_unsupported_or_wrong_header_or_row_width_fails_closed(self):
        digest = ReleaseDigest((DigestTable("t", ("a", "b")),))
        with self.assertRaises(LoaderCandidateInvalid):
            digest.begin("t", ("a",))
        digest.begin("t", ("a", "b"))
        with self.assertRaises(LoaderCandidateInvalid):
            digest.rows(((object(), 1),))
        with self.assertRaises(LoaderCandidateInvalid):
            digest.rows(((1,),))

    def test_missing_extra_repeated_or_reordered_tables_fail_closed(self):
        with self.assertRaises(LoaderCandidateInvalid):
            ReleaseDigest(())
        with self.assertRaises(LoaderCandidateInvalid):
            ReleaseDigest((DigestTable("t", ("a",)), DigestTable("t", ("a",))))

        digest = ReleaseDigest(PROFILE)
        with self.assertRaises(LoaderCandidateInvalid):
            digest.begin("empty_table", PROFILE[1].columns)
        digest.begin("records", PROFILE[0].columns)
        digest.end()
        with self.assertRaises(LoaderCandidateInvalid):
            digest.begin("records", PROFILE[0].columns)

    def test_premature_or_open_table_finalization_fails_closed(self):
        digest = ReleaseDigest(PROFILE)
        with self.assertRaises(LoaderCandidateInvalid):
            digest.hexdigest()
        digest.begin("records", PROFILE[0].columns)
        with self.assertRaises(LoaderCandidateInvalid):
            digest.hexdigest()
        digest.end()
        with self.assertRaises(LoaderCandidateInvalid):
            digest.hexdigest()


if __name__ == "__main__":
    unittest.main()

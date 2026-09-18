"""Tests for private source-key canonicalisation used by future upserts."""

import unittest
from decimal import Decimal

from etl.identifiers import (
    DuplicateSourceIdentifier,
    InvalidSourceIdentifier,
    assert_unique_source_ids,
    canonical_unique_no,
)


class TestCanonicalUniqueNo(unittest.TestCase):
    def test_equivalent_postgresql_numerics_collapse_to_one_representation(self):
        for value in (123, "123", "123.0", "123.00", "1.23E+2", Decimal("123.00")):
            with self.subTest(value=value):
                self.assertEqual(canonical_unique_no(value), "123.00")

    def test_meaningful_scale_is_preserved(self):
        self.assertEqual(canonical_unique_no("123.10"), "123.10")
        self.assertEqual(canonical_unique_no("0.01"), "0.01")
        self.assertEqual(canonical_unique_no("-0.00"), "0.00")

    def test_numeric_13_2_boundaries_are_exact(self):
        self.assertEqual(canonical_unique_no("99999999999.99"), "99999999999.99")
        self.assertEqual(canonical_unique_no("-99999999999.99"), "-99999999999.99")
        for value in ("100000000000.00", "-100000000000.00"):
            with self.subTest(value=value), self.assertRaises(InvalidSourceIdentifier):
                canonical_unique_no(value)

    def test_missing_non_finite_malformed_and_over_scale_values_fail(self):
        values = (
            None,
            True,
            False,
            123.0,
            "",
            "   ",
            "not-a-number",
            "NaN",
            "Infinity",
            "-Infinity",
            "123.001",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(InvalidSourceIdentifier):
                canonical_unique_no(value)

    def test_errors_never_echo_the_private_identifier(self):
        private_value = "123.001"
        with self.assertRaises(InvalidSourceIdentifier) as ctx:
            canonical_unique_no(private_value)
        self.assertNotIn(private_value, str(ctx.exception))


class TestCanonicalDuplicateDetection(unittest.TestCase):
    def test_distinct_values_return_in_input_order(self):
        self.assertEqual(assert_unique_source_ids(["2", "1.5"]), ("2.00", "1.50"))

    def test_equivalent_spellings_are_a_duplicate(self):
        with self.assertRaises(DuplicateSourceIdentifier) as ctx:
            assert_unique_source_ids(["123", "123.00"])
        self.assertNotIn("123", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=1)

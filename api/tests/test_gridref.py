"""Tests for grid-reference generalisation.

The interleaved-halves test is the one that matters: a naive implementation that
truncates the digit string passes casual inspection and silently relocates every
generalised record.
"""

import json
import unittest
from pathlib import Path

from etl.gridref import (
    PUBLIC_RESOLUTIONS_METRES,
    coarsen,
    is_public_resolution,
    normalise,
    precision_metres,
    split,
)


class TestPrecision(unittest.TestCase):
    def test_shared_public_gridref_corpus_matches_the_browser(self):
        path = Path(__file__).resolve().parents[2] / "contracts/gridref-validation-corpus.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 19)
        for case in cases:
            actual = precision_metres(case["ref"])
            with self.subTest(ref=case["ref"]):
                expected = case["precisionMetres"]
                if expected is None:
                    # Python additionally recognises safe input-only forms
                    # (tetrads/letters-only); neither may cross the public tier.
                    self.assertFalse(is_public_resolution(actual))
                else:
                    self.assertEqual(actual, expected)

    def test_derived_from_digit_count(self):
        cases = {
            "ST": 100000,
            "ST57": 10000,
            "ST5872": 1000,
            "ST587721": 100,
            "ST58777216": 10,
            "ST5877972166": 1,
        }
        for ref, metres in cases.items():
            with self.subTest(ref=ref):
                self.assertEqual(precision_metres(ref), metres)

    def test_matches_the_frontend_table(self):
        # web/src/lib/geo/gridref.ts: {1:10000, 2:1000, 3:100, 4:10, 5:1}
        for pairs, metres in {1: 10000, 2: 1000, 3: 100, 4: 10, 5: 1}.items():
            ref = "ST" + "1" * (pairs * 2)
            self.assertEqual(precision_metres(ref), metres)

    def test_tetrad_is_two_kilometres(self):
        self.assertEqual(precision_metres("ST57A"), 2000)
        self.assertEqual(precision_metres("ST57Z"), 2000)

    def test_tetrad_excludes_the_letter_O(self):
        self.assertIsNone(precision_metres("ST57O"))

    def test_odd_digit_count_is_not_a_reference(self):
        for ref in ("ST5", "ST587", "ST58772"):
            with self.subTest(ref=ref):
                self.assertIsNone(precision_metres(ref))

    def test_rubbish_returns_none_rather_than_guessing(self):
        for ref in ("", "   ", "1234", "ST-5872", "STU5872", "ST 58 72 extra"):
            with self.subTest(ref=ref):
                self.assertIsNone(precision_metres(ref))

    def test_whitespace_and_case_are_tolerated(self):
        self.assertEqual(precision_metres("st 58 72"), 1000)
        self.assertEqual(normalise(" st 58 72 "), "ST5872")


class TestSplit(unittest.TestCase):
    def test_halves_are_easting_then_northing(self):
        self.assertEqual(split("ST587721"), ("ST", "587", "721"))
        self.assertEqual(split("ST5872"), ("ST", "58", "72"))
        self.assertEqual(split("ST"), ("ST", "", ""))

    def test_tetrad_has_no_positional_split(self):
        self.assertIsNone(split("ST57A"))


class TestCoarsen(unittest.TestCase):
    def test_truncates_each_axis_independently(self):
        # THE critical case. ST587721 is easting 587, northing 721.
        # Correct 1 km answer keeps 2 digits per axis: 58 and 72 -> ST5872.
        self.assertEqual(coarsen("ST587721", 1000), "ST5872")

    def test_naive_string_truncation_would_be_wrong(self):
        # Documents the bug this module exists to prevent.
        naive = "ST587721"[:6]
        self.assertEqual(naive, "ST5877")
        self.assertNotEqual(coarsen("ST587721", 1000), naive)

    def test_ten_metre_reference_to_one_kilometre(self):
        # ST 5877 7216 -> easting 5877, northing 7216 -> ST5872
        self.assertEqual(coarsen("ST58777216", 1000), "ST5872")

    def test_one_metre_reference_to_one_kilometre(self):
        # ST 58779 72166 -> ST5872
        self.assertEqual(coarsen("ST5877972166", 1000), "ST5872")

    def test_to_ten_kilometres(self):
        self.assertEqual(coarsen("ST587721", 10000), "ST57")
        self.assertEqual(coarsen("ST5872", 10000), "ST57")

    def test_to_hundred_kilometres_keeps_only_letters(self):
        self.assertEqual(coarsen("ST587721", 100000), "ST")

    def test_already_coarse_enough_is_returned_unchanged(self):
        self.assertEqual(coarsen("ST5872", 1000), "ST5872")
        self.assertEqual(coarsen("ST57", 10000), "ST57")

    def test_never_upsamples(self):
        # A 1 km record cannot become a 100 m record.
        self.assertIsNone(coarsen("ST5872", 100))
        self.assertIsNone(coarsen("ST57", 1000))

    def test_unparseable_input_fails_closed(self):
        for ref in ("", "nonsense", "ST587"):
            with self.subTest(ref=ref):
                self.assertIsNone(coarsen(ref, 1000))

    def test_unsupported_target_fails_closed(self):
        self.assertIsNone(coarsen("ST587721", 2500))
        self.assertIsNone(coarsen("ST587721", 0))

    def test_a_tetrad_is_never_sharpened(self):
        # 2 km is already coarser than 1 km and 100 m, so both are refused as
        # upsampling. A tetrad's axis split is not positional, so a truncation
        # answer here would be a fabricated location, not a coarser one.
        self.assertIsNone(coarsen("ST57A", 100))
        self.assertIsNone(coarsen("ST57A", 1000))

    def test_a_tetrad_coarsens_to_its_containing_squares(self):
        # A tetrad is exactly contained in its own 10 km square, so dropping the
        # letter is arithmetically exact. An earlier version returned None for
        # every tetrad, so a tetrad record was withheld as "cannot-generalise"
        # even though a safe 10 km square was sitting in the reference already.
        self.assertEqual(coarsen("ST57A", 10000), "ST57")
        self.assertEqual(coarsen("ST57A", 100000), "ST")
        self.assertEqual(coarsen("st57a", 10000), "ST57")
        self.assertEqual(coarsen("ST 57 A", 10000), "ST57")

    def test_a_coarsened_tetrad_is_at_its_stated_precision(self):
        self.assertEqual(precision_metres(coarsen("ST57A", 10000)), 10000)

    def test_every_tetrad_letter_lands_in_the_same_ten_kilometre_square(self):
        # A-Z excluding O. All 25 are inside ST57 by construction; if any letter
        # changed the digits, records would move between 10 km squares.
        for letter in "ABCDEFGHIJKLMNPQRSTUVWXYZ":
            with self.subTest(letter=letter):
                self.assertEqual(coarsen(f"ST57{letter}", 10000), "ST57")

    def test_output_precision_always_equals_the_target(self):
        for ref in ("ST587721", "ST58777216", "ST5877972166"):
            for target in (1000, 10000, 100000):
                with self.subTest(ref=ref, target=target):
                    out = coarsen(ref, target)
                    self.assertIsNotNone(out)
                    self.assertEqual(precision_metres(out), target)

    def test_coarsening_is_idempotent(self):
        once = coarsen("ST587721", 1000)
        self.assertEqual(coarsen(once, 1000), once)

    def test_coarsened_square_contains_the_original(self):
        # The 1 km square must be the one the finer reference sits inside.
        fine = "ST58777216"  # easting 5877, northing 7216
        coarse = coarsen(fine, 1000)  # expect easting 58, northing 72
        letters, e, n = split(fine)
        self.assertEqual(coarse, f"{letters}{e[:2]}{n[:2]}")


class TestPublicResolutions(unittest.TestCase):
    def test_only_permitted_resolutions_pass(self):
        for metres in PUBLIC_RESOLUTIONS_METRES:
            self.assertTrue(is_public_resolution(metres))

    def test_hundred_metres_is_publishable(self):
        # The records tier floor. Matches PUBLIC_MIN_PRECISION_METRES in
        # web/src/lib/api/schemas.ts, whose contract test rejects anything finer.
        self.assertTrue(is_public_resolution(100))

    def test_finer_than_the_records_floor_is_not_public(self):
        for metres in (1, 10, None):
            with self.subTest(metres=metres):
                self.assertFalse(is_public_resolution(metres))

    def test_matches_the_client_floor_constant(self):
        # If PUBLIC_MIN_PRECISION_METRES in schemas.ts ever changes, this must too.
        self.assertEqual(min(PUBLIC_RESOLUTIONS_METRES), 100)

    def test_tetrad_is_not_currently_emittable(self):
        # The frontend parser (web/src/lib/geo/gridref.ts) cannot read a tetrad,
        # so emitting one would produce a square the client cannot draw.
        self.assertFalse(is_public_resolution(2000))


if __name__ == "__main__":
    unittest.main(verbosity=2)

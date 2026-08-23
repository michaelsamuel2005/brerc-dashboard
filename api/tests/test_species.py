"""Tests for name -> species-number resolution."""

import unittest

from etl.sensitivity import is_sensitive
from etl.species import SpeciesDictionary, normalise_name

DICT_ROWS = [
    {
        "SPECIES_NO": "2028",
        "SCIENTIFIC": "Belonia calcicola",
        "COMMON_NAM": "a lichen",
        "SENSITIVE": "yes",
    },
    {
        "SPECIES_NO": "BRERC10469",
        "SCIENTIFIC": "Aceria myriadeum",
        "COMMON_NAM": "a mite",
        "SENSITIVE": None,
    },
    {
        "SPECIES_NO": "6973a",
        "SCIENTIFIC": "Cheilosia ranunculi",
        "COMMON_NAM": "a hoverfly",
        "SENSITIVE": None,
    },
    {
        "SPECIES_NO": "5088",
        "SCIENTIFIC": "Anguis fragilis",
        "COMMON_NAM": "Slow-worm",
        "SENSITIVE": None,
    },
]


class TestNormalisation(unittest.TestCase):
    def test_casefolds_and_collapses_whitespace(self):
        self.assertEqual(normalise_name("  Anguis   FRAGILIS "), "anguis fragilis")

    def test_handles_non_strings(self):
        self.assertEqual(normalise_name(None), "none")


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.d = SpeciesDictionary.from_rows(DICT_ROWS)

    def test_builds_every_usable_entry(self):
        self.assertEqual(len(self.d), 4)

    def test_resolves_regardless_of_case_and_spacing(self):
        for name in ("Anguis fragilis", "anguis fragilis", "  ANGUIS   FRAGILIS  "):
            with self.subTest(name=name):
                self.assertEqual(self.d.species_id_for(name), "5088")

    def test_preserves_alphanumeric_ids(self):
        self.assertEqual(self.d.species_id_for("Aceria myriadeum"), "BRERC10469")
        self.assertEqual(self.d.species_id_for("Cheilosia ranunculi"), "6973A")

    def test_an_unknown_name_resolves_to_none(self):
        self.assertIsNone(self.d.species_id_for("Nonexistent taxon"))

    def test_an_unresolved_name_fails_closed_in_the_gate(self):
        self.assertTrue(is_sensitive(self.d.species_id_for("Nonexistent taxon")))

    def test_sensitivity_flag_is_read(self):
        self.assertTrue(self.d.lookup("Belonia calcicola").sensitive)
        self.assertFalse(self.d.lookup("Anguis fragilis").sensitive)
        self.assertEqual(self.d.sensitive_count, 1)

    def test_dictionary_digest_is_deterministic_and_binds_sensitivity(self):
        same_reordered = SpeciesDictionary.from_rows(reversed(DICT_ROWS))
        changed_rows = [dict(row) for row in DICT_ROWS]
        changed_rows[-1]["SENSITIVE"] = "yes"
        changed = SpeciesDictionary.from_rows(changed_rows)
        self.assertEqual(self.d.digest(), same_reordered.digest())
        self.assertNotEqual(self.d.digest(), changed.digest())

    def test_a_resolved_sensitive_species_is_gated(self):
        self.assertTrue(is_sensitive(self.d.species_id_for("Belonia calcicola")))

    def test_a_resolved_ordinary_species_is_not_gated(self):
        # The regression that mattered: an alphanumeric id must not fail closed.
        self.assertFalse(is_sensitive(self.d.species_id_for("Aceria myriadeum")))
        self.assertFalse(is_sensitive(self.d.species_id_for("Cheilosia ranunculi")))


class TestSensitiveColumnParsing(unittest.TestCase):
    def test_blank_and_negative_markers_are_not_sensitive(self):
        for marker in (None, "", "   ", "nan", "no", "N", "false", "0"):
            d = SpeciesDictionary.from_rows(
                [{"SPECIES_NO": "1", "SCIENTIFIC": "X y", "COMMON_NAM": "", "SENSITIVE": marker}]
            )
            self.assertFalse(d.lookup("X y").sensitive, f"marker {marker!r}")

    def test_yes_markers_are_sensitive(self):
        for marker in ("yes", "Yes", "Y", "true", "1"):
            d = SpeciesDictionary.from_rows(
                [{"SPECIES_NO": "1", "SCIENTIFIC": "X y", "COMMON_NAM": "", "SENSITIVE": marker}]
            )
            self.assertTrue(d.lookup("X y").sensitive, f"marker {marker!r}")


class TestDataQuality(unittest.TestCase):
    def test_rows_without_a_usable_id_are_skipped(self):
        d = SpeciesDictionary.from_rows(
            [
                *DICT_ROWS,
                {
                    "SPECIES_NO": None,
                    "SCIENTIFIC": "Ghost taxon",
                    "COMMON_NAM": "",
                    "SENSITIVE": None,
                },
            ]
        )
        self.assertIsNone(d.species_id_for("Ghost taxon"))

    def test_conflicting_duplicate_names_are_ambiguous_not_first_row_wins(self):
        d = SpeciesDictionary.from_rows(
            [
                *DICT_ROWS,
                {
                    "SPECIES_NO": "9999",
                    "SCIENTIFIC": "Anguis fragilis",
                    "COMMON_NAM": "Slow-worm",
                    "SENSITIVE": None,
                },
            ]
        )
        self.assertIn("anguis fragilis", d.duplicate_names)
        self.assertIn("anguis fragilis", d.ambiguous_names)
        self.assertTrue(d.is_ambiguous("Anguis fragilis"))
        self.assertIsNone(d.lookup("Anguis fragilis"))
        self.assertIsNone(d.species_id_for("Anguis fragilis"))

    def test_an_exact_duplicate_id_is_not_identity_ambiguous(self):
        d = SpeciesDictionary.from_rows(
            [
                *DICT_ROWS,
                {
                    "SPECIES_NO": "5088",
                    "SCIENTIFIC": "  ANGUIS   FRAGILIS ",
                    "COMMON_NAM": "Slow-worm",
                    "SENSITIVE": None,
                },
            ]
        )
        self.assertIn("anguis fragilis", d.duplicate_names)
        self.assertNotIn("anguis fragilis", d.ambiguous_names)
        self.assertFalse(d.is_ambiguous("Anguis fragilis"))
        self.assertEqual(d.species_id_for("Anguis fragilis"), "5088")

    def test_duplicate_sensitivity_disagreement_fails_safe(self):
        d = SpeciesDictionary.from_rows(
            [
                {
                    "SPECIES_NO": "5088",
                    "SCIENTIFIC": "Anguis fragilis",
                    "COMMON_NAM": "Slow-worm",
                    "SENSITIVE": "no",
                },
                {
                    "SPECIES_NO": "5088",
                    "SCIENTIFIC": "Anguis fragilis",
                    "COMMON_NAM": "Slow-worm",
                    "SENSITIVE": "yes",
                },
            ]
        )
        self.assertFalse(d.is_ambiguous("Anguis fragilis"))
        self.assertTrue(d.lookup("Anguis fragilis").sensitive)

    def test_coverage_reports_what_will_fail_closed(self):
        d = SpeciesDictionary.from_rows(DICT_ROWS)
        resolved, total, unresolved = d.coverage(
            ["Anguis fragilis", "Vipera berus", "Belonia calcicola"]
        )
        self.assertEqual((resolved, total), (2, 3))
        self.assertEqual(unresolved, ["Vipera berus"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

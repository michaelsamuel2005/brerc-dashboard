"""Fail-closed tests for the loader-owned species-dictionary artifact."""

from __future__ import annotations

import unittest
from unittest import mock

from brerc_loader.errors import LoaderPolicyInvalid
from brerc_loader.species_dictionary import parse_species_dictionary_artifact
from etl.species import SpeciesDictionary

HEADER = b"SPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE"


class TestSpeciesDictionaryArtifact(unittest.TestCase):
    def assert_rejected(self, artifact: object) -> None:
        with self.assertRaises(LoaderPolicyInvalid) as raised:
            parse_species_dictionary_artifact(artifact)  # type: ignore[arg-type]
        self.assertNotIn("private", str(raised.exception))

    def test_bom_crlf_and_extra_columns_produce_the_semantic_dictionary(self) -> None:
        artifact = (
            b"\xef\xbb\xbfSPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE,PRIVATE_EXTRA\r\n"
            b"SYNTH-1,Synthetic alpha,Alpha,No,private-value\r\n"
            b"SYNTH-2,Synthetic beta,Beta,Yes,private-value\r\n"
        )
        parsed = parse_species_dictionary_artifact(artifact)
        expected = SpeciesDictionary.from_rows(
            [
                {
                    "SPECIES_NO": "SYNTH-1",
                    "SCIENTIFIC": "Synthetic alpha",
                    "COMMON_NAM": "Alpha",
                    "SENSITIVE": "No",
                },
                {
                    "SPECIES_NO": "SYNTH-2",
                    "SCIENTIFIC": "Synthetic beta",
                    "COMMON_NAM": "Beta",
                    "SENSITIVE": "Yes",
                },
            ]
        )
        self.assertEqual(parsed.digest(), expected.digest())
        self.assertEqual(parsed.lookup(" synthetic   ALPHA ").species_no, "SYNTH-1")
        self.assertTrue(parsed.lookup("Synthetic beta").sensitive)

    def test_ambiguous_scientific_name_remains_fail_closed(self) -> None:
        artifact = (
            HEADER
            + b"\nSYNTH-1,Synthetic alpha,Alpha,No"
            + b"\nSYNTH-2,Synthetic alpha,Alpha,Yes\n"
        )
        parsed = parse_species_dictionary_artifact(artifact)
        self.assertTrue(parsed.is_ambiguous("Synthetic alpha"))
        self.assertIsNone(parsed.lookup("Synthetic alpha"))

    def test_required_headers_are_exact_but_extra_headers_are_allowed(self) -> None:
        bad_headers = (
            b"SPECIES_NO,SCIENTIFIC,COMMON_NAM\n1,Synthetic alpha,Alpha\n",
            b"SPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE,SENSITIVE\n"
            b"1,Synthetic alpha,Alpha,No,No\n",
            b"SPECIES_NO,SCIENTIFIC,,COMMON_NAM,SENSITIVE\n1,Synthetic alpha,private,Alpha,No\n",
            b"SPECIES_NO, SCIENTIFIC,COMMON_NAM,SENSITIVE\n1,Synthetic alpha,Alpha,No\n",
        )
        for artifact in bad_headers:
            with self.subTest(artifact=artifact.splitlines()[0]):
                self.assert_rejected(artifact)

    def test_malformed_encoding_nul_and_row_shapes_are_rejected(self) -> None:
        bad_artifacts = (
            b"",
            b"\xff",
            HEADER + b"\n1,private\x00 name,Alpha,No\n",
            HEADER + b'\n1,"private unterminated,Alpha,No\n',
            HEADER + b"\n1,Synthetic alpha,Alpha,No,overflow\n",
            HEADER + b"\n1,Synthetic alpha,Alpha\n",
        )
        for artifact in bad_artifacts:
            with self.subTest(length=len(artifact)):
                self.assert_rejected(artifact)

    def test_zero_usable_rows_is_rejected(self) -> None:
        for artifact in (
            HEADER + b"\n",
            HEADER + b"\n,Synthetic alpha,Alpha,No\n",
            HEADER + b"\nSYNTH-1,,Alpha,No\n",
        ):
            with self.subTest(artifact=artifact):
                self.assert_rejected(artifact)

    def test_byte_and_row_limits_are_enforced_without_allocating_production_bounds(self) -> None:
        artifact = (
            HEADER + b"\nSYNTH-1,Synthetic alpha,Alpha,No" + b"\nSYNTH-2,Synthetic beta,Beta,No\n"
        )
        with mock.patch("brerc_loader.species_dictionary.MAX_SPECIES_DICTIONARY_ROWS", 1):
            self.assert_rejected(artifact)
        with mock.patch("brerc_loader.species_dictionary.MAX_SPECIES_DICTIONARY_BYTES", 4):
            self.assert_rejected(b"12345")


if __name__ == "__main__":
    unittest.main()

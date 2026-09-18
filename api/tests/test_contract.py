"""Tests for the public contract: verified-status parity and the PII allow-list."""

import dataclasses
import unittest

from etl.contract import (
    FORBIDDEN_FIELDS,
    PublicCell,
    PublicRecord,
    assert_no_forbidden_fields,
    normalise_field_name,
    normalise_verified,
)


class TestVerifiedParityWithTheClient(unittest.TestCase):
    """Must match normaliseVerified in web/src/lib/api/schemas.ts exactly."""

    def test_the_order_sensitive_case(self):
        # Contains BOTH "reject" and "accept". The client tests reject first, and
        # so must we, or rejected records inflate the verified count.
        self.assertEqual(normalise_verified("Rejected - not accepted"), "rejected")
        self.assertEqual(normalise_verified("Rejected – correct"), "rejected")

    def test_accepted(self):
        for raw in ("Accepted", "Accepted – correct", "ACCEPTED", "accepted by expert"):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), "accepted")

    def test_unconfirmed_variants(self):
        for raw in ("Unconfirmed", "pending review", "Unverified", "Not verified"):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), "unconfirmed")

    def test_unconfirmed_beats_accepted_when_both_appear(self):
        # Mirrors the client: the unconfirmed test runs before the accepted test.
        self.assertEqual(normalise_verified("accepted but unconfirmed"), "unconfirmed")

    def test_unknown_is_the_fallback_not_accepted(self):
        for raw in ("", "   ", "n/a", "considered", None, 42):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), "unknown")

    def test_case_insensitive(self):
        self.assertEqual(normalise_verified("REJECTED"), "rejected")
        self.assertEqual(normalise_verified("uNcOnFiRmEd"), "unconfirmed")


class TestAllowListStructure(unittest.TestCase):
    def test_public_record_has_no_slot_for_pii(self):
        fields = set(PublicRecord.__dataclass_fields__)
        for banned in (
            "recorder1",
            "recorder",
            "easting",
            "eastings",
            "northing",
            "northings",
            "comments",
            "sensitive",
            "sensitivity",
            "bliss",
        ):
            self.assertNotIn(banned, fields)

    def test_public_record_cannot_be_given_an_extra_field(self):
        with self.assertRaises(TypeError):
            PublicRecord(  # type: ignore[call-arg]
                record_id="1",
                species_id="5088",
                scientific_name="Anguis fragilis",
                common_name="Slow-worm",
                grid_ref="ST5872",
                precision_metres=1000,
                place=None,
                year=2020,
                abundance=None,
                record_type=None,
                verified="accepted",
                source="recorder",
                recorder1="A Person",
            )

    def test_public_record_is_immutable(self):
        # frozen=True, so a caller cannot quietly sharpen a generalised reference
        # after the gate has run. Asserting the specific exception, not Exception:
        # a blind assertRaises would also pass on a typo in the attribute name.
        rec = PublicRecord(
            "1",
            "5088",
            "Anguis fragilis",
            None,
            "ST5872",
            1000,
            None,
            2020,
            None,
            None,
            "accepted",
            "recorder",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rec.grid_ref = "ST587721"  # type: ignore[misc]

    def test_serialised_record_matches_the_client_key_names(self):
        rec = PublicRecord(
            "1",
            "5088",
            "Anguis fragilis",
            "Slow-worm",
            "ST585725",
            100,
            None,
            2000,
            "3",
            "field record",
            "accepted",
            "recorder",
        )
        self.assertEqual(
            set(rec.to_api()),
            {
                "id",
                "scientificName",
                "commonName",
                "gridRef",
                "precisionMetres",
                "place",
                "year",
                "abundance",
                "recordType",
                "verified",
                "source",
            },
        )

    def test_serialised_cell_matches_the_client_key_names(self):
        cell = PublicCell("5088", 2020, "ST5872", 1000, 5, 4)
        self.assertEqual(
            set(cell.to_api()),
            {
                "cellId",
                "precisionMetres",
                "recordCount",
                "verifiedCount",
            },
        )


class TestForbiddenFieldDetection(unittest.TestCase):
    def test_clean_payload_passes(self):
        rec = PublicRecord(
            "1",
            "5088",
            "Anguis fragilis",
            None,
            "ST5872",
            1000,
            None,
            2020,
            None,
            None,
            "accepted",
            "recorder",
        )
        self.assertEqual(assert_no_forbidden_fields(rec.to_api()), [])

    def test_detects_a_leaked_field_at_the_top_level(self):
        found = assert_no_forbidden_fields({"gridRef": "ST5872", "Recorder1": "A Person"})
        self.assertEqual(len(found), 1)
        self.assertIn("Recorder1", found[0])

    def test_detects_a_leak_nested_in_a_list(self):
        payload = {"items": [{"id": "1"}, {"id": "2", "comments": "note"}]}
        self.assertEqual(len(assert_no_forbidden_fields(payload)), 1)

    def test_detects_separator_and_case_variants(self):
        for key in ("recorder_1", "RECORDER1", "Recorder 1", "precise-grid-ref", "preciseGridRef"):
            with self.subTest(key=key):
                self.assertEqual(len(assert_no_forbidden_fields({key: "x"})), 1)

    def test_detects_the_live_view_names_and_their_safe_normalisation_variants(self):
        variants = (
            "easting",
            "Easting",
            "EASTING",
            "east_ing",
            "east-ing",
            "east ing",
            "eastings",
            "EAST_INGS",
            "northing",
            "Northing",
            "NORTH_ING",
            "north-ing",
            "northings",
            "NORTH INGS",
            "sensitive",
            "Sensitive",
            "SENSI_TIVE",
            "sensi-tive",
            "sensitivity",
            "SENSI_TIVITY",
            "sensi-tivity",
            "unique_no",
            "UniqueNo",
            "UNIQUE-NO",
            "RecordKey",
            "record_key",
            "RECORD-KEY",
        )
        for key in variants:
            with self.subTest(key=key):
                self.assertIn(normalise_field_name(key), FORBIDDEN_FIELDS)
                self.assertEqual(len(assert_no_forbidden_fields({key: "x"})), 1)

    def test_exact_matching_does_not_block_safe_derived_or_explanatory_keys(self):
        safe = {
            "gridRef": "ST5872",
            "precisionMetres": 1000,
            "sensitivityPolicy": {"appliesToProtectedTaxa": True},
            "eastingLabel": "derived-coordinate label",
            "northingLabel": "derived-coordinate label",
            "sensitiveSpeciesNote": "public explanation",
            "note": "The words easting, northing and sensitive in a value are harmless.",
        }
        self.assertEqual(assert_no_forbidden_fields(safe), [])

    def test_mirrors_the_client_forbidden_set(self):
        # web/src/lib/api/contract.test.ts FORBIDDEN
        self.assertEqual(
            FORBIDDEN_FIELDS,
            frozenset(
                {
                    "recorder1",
                    "bliss",
                    "easting",
                    "eastings",
                    "northing",
                    "northings",
                    "comments",
                    "uniqueno",
                    "recordkey",
                    "sensitive",
                    "sensitivity",
                    "precisegridref",
                    "precisedate",
                }
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)

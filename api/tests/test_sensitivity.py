"""Tests for the sensitive-species gate.

`Data_Governance_and_Compliance.md` requires "an automated test asserting no
finer-than-allowed geometry can be returned for a known sensitive taxon".
`TestTheGateHolds` is that test.

Every test names its policy explicitly. There is no default policy, deliberately:
a gate whose behaviour depends on an implicit default is a gate nobody can reason
about from the call site.
"""

import hashlib
import unittest

from etl.gridref import PUBLIC_RESOLUTIONS_METRES, precision_metres
from etl.policy import DEVELOPMENT_POLICY, UNAPPROVED_POLICY, PublicationPolicy
from etl.sensitivity import (
    SENSITIVE_SNAPSHOT_SHA256,
    SENSITIVE_SNAPSHOT_VERSION,
    SENSITIVE_SPECIES_IDS,
    generalise,
    is_sensitive,
    next_public_resolution,
    normalise_species_id,
)

KNOWN_SENSITIVE = "2028"  # flagged SENSITIVE="yes" in the BRERC dictionary
KNOWN_ORDINARY = "999999"  # not on the list

#: The working development policy: ordinary records at 100 m, sensitive at 10 km,
#: unresolved taxa withheld. Mirrors what the frontend contract can carry, which
#: is NOT the same as what BRERC has authorised - see PublicationPolicy.
DEV = DEVELOPMENT_POLICY

#: A policy that permits promoting an unpublishable resolution (2 km tetrad) to
#: the next square the client can draw.
DEV_PROMOTING = PublicationPolicy(
    version="test-promoting",
    development_only=True,
    ordinary_resolution_metres=100,
    default_sensitive_metres=10000,
    coarsen_unpublishable_resolutions=True,
    public_id_salt="test" * 8,
)


class TestSensitiveSnapshotEvidence(unittest.TestCase):
    def test_snapshot_version_and_digest_are_deterministic(self):
        self.assertTrue(SENSITIVE_SNAPSHOT_VERSION)
        self.assertEqual(len(SENSITIVE_SPECIES_IDS), 65)
        self.assertEqual(
            SENSITIVE_SNAPSHOT_SHA256,
            hashlib.sha256("\n".join(sorted(SENSITIVE_SPECIES_IDS)).encode("ascii")).hexdigest(),
        )


def gen(ref, sid, *, policy=DEV, **kw):
    """Shorthand: the gate always resolves the species unless told otherwise."""
    kw.setdefault("known", True)
    return generalise(ref, sid, policy=policy, **kw)


class TestClassification(unittest.TestCase):
    def test_listed_species_is_sensitive(self):
        self.assertTrue(is_sensitive(KNOWN_SENSITIVE))

    def test_unlisted_species_is_ordinary(self):
        self.assertFalse(is_sensitive(KNOWN_ORDINARY))

    def test_numeric_strings_and_ints_agree(self):
        for sid in ("2028", 2028, 2028.0, " 2028 "):
            with self.subTest(sid=sid):
                self.assertTrue(is_sensitive(sid))
        self.assertFalse(is_sensitive("999999"))

    def test_alphanumeric_brerc_ids_are_not_sensitive_by_accident(self):
        # 61,080 of the 96,824 dictionary entries look like these. An earlier
        # int() conversion raised on every one and fell through to fail-closed,
        # generalising 50 of 998 ordinary records to 10 km for no reason.
        for sid in ("BRERC10469", "BRERC62546", "6973a", "Z5567", "5519a", "25913A"):
            with self.subTest(sid=sid):
                self.assertFalse(is_sensitive(sid), f"{sid} must not be treated as sensitive")

    def test_id_normalisation(self):
        self.assertEqual(normalise_species_id(2028.0), "2028")  # spreadsheet float
        self.assertEqual(normalise_species_id(" 6973a "), "6973A")
        self.assertIsNone(normalise_species_id(float("nan")))
        self.assertIsNone(normalise_species_id(True))  # bool is not an id
        self.assertIsNone(normalise_species_id(2028.5))  # fractional is nonsense

    def test_unusable_species_id_fails_closed(self):
        for sid in (None, "", "   ", float("nan"), True):
            with self.subTest(sid=sid):
                self.assertTrue(is_sensitive(sid))


class TestDictionaryFlagIsUnionedNotSubstituted(unittest.TestCase):
    """BRERC maintains the list; our snapshot will drift. A union only ever
    over-protects, which is the safe direction."""

    def test_a_dictionary_flag_makes_an_unlisted_species_sensitive(self):
        # BRERC adds a taxon after our snapshot was taken.
        self.assertFalse(is_sensitive(KNOWN_ORDINARY))
        self.assertTrue(is_sensitive(KNOWN_ORDINARY, flagged=True))

    def test_an_unflagged_dictionary_entry_does_not_clear_the_snapshot(self):
        # A stale or partly-loaded dictionary must not silently UNprotect a taxon.
        self.assertTrue(is_sensitive(KNOWN_SENSITIVE, flagged=False))

    def test_the_flag_propagates_through_the_gate(self):
        rec = gen("ST5877972166", KNOWN_ORDINARY, flagged_sensitive=True)
        self.assertTrue(rec.is_sensitive)
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_policy_species_rule_is_itself_a_sensitivity_decision(self):
        policy = PublicationPolicy(
            version="t",
            development_only=True,
            ordinary_resolution_metres=100,
            default_sensitive_metres=1000,
            sensitive_resolution_metres={" 6973a ": 10000},
            public_id_salt="test" * 8,
        )
        rec = generalise(
            "ST5877972166",
            "6973A",
            policy=policy,
            known=True,
        )
        self.assertTrue(rec.is_sensitive)
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_policy_species_rule_does_not_make_an_unresolved_taxon_publishable(self):
        policy = PublicationPolicy(
            version="t",
            development_only=True,
            ordinary_resolution_metres=100,
            sensitive_resolution_metres={KNOWN_ORDINARY: 1000},
            public_id_salt="test" * 8,
        )
        rec = generalise(
            "ST5877972166",
            KNOWN_ORDINARY,
            policy=policy,
            known=False,
        )
        self.assertTrue(rec.is_sensitive)
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "species-not-permitted")


class TestPolicyIsRequired(unittest.TestCase):
    def test_omitting_the_policy_is_a_type_error_not_a_silent_withhold(self):
        # An earlier version defaulted to UNAPPROVED_POLICY, so a caller who
        # forgot it got a 100% withhold that read like a data problem.
        with self.assertRaises(TypeError):
            generalise("ST587721", KNOWN_ORDINARY)  # type: ignore[call-arg]


class TestUnknownSpeciesHandling(unittest.TestCase):
    """A well-formed id absent from the taxonomy is NOT ordinary."""

    def test_unresolved_species_is_withheld_under_the_default_action(self):
        rec = generalise("ST587721", KNOWN_ORDINARY, policy=DEV, known=False)
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "species-not-permitted")

    def test_unresolved_species_goes_to_the_coarsest_square_when_permitted(self):
        policy = PublicationPolicy(
            version="test-coarsest",
            development_only=True,
            ordinary_resolution_metres=100,
            unknown_species_action="coarsest",
            public_id_salt="test" * 8,
        )
        rec = generalise("ST5877972166", KNOWN_ORDINARY, policy=policy, known=False)
        self.assertTrue(rec.emit)
        self.assertEqual(rec.precision_metres, 10000)

    def test_unresolved_species_is_never_published_at_the_ordinary_resolution(self):
        for action in ("withhold", "coarsest"):
            with self.subTest(action=action):
                policy = PublicationPolicy(
                    version="t",
                    development_only=True,
                    ordinary_resolution_metres=100,
                    unknown_species_action=action,
                    public_id_salt="test" * 8,
                )
                rec = generalise("ST5877972166", KNOWN_ORDINARY, policy=policy, known=False)
                if rec.emit:
                    self.assertGreater(rec.precision_metres, 100)

    def test_the_unapproved_default_policy_publishes_nothing(self):
        rec = generalise("ST587721", KNOWN_ORDINARY, policy=UNAPPROVED_POLICY, known=False)
        self.assertFalse(rec.emit)


class TestTheGateHolds(unittest.TestCase):
    """No finer-than-allowed geometry for a sensitive taxon, from any input."""

    FINE_REFS = ("ST5877972166", "ST58777216", "ST587721", "ST5872", "ST57")

    def test_sensitive_records_never_emit_finer_than_required(self):
        for ref in self.FINE_REFS:
            with self.subTest(ref=ref):
                rec = gen(ref, KNOWN_SENSITIVE)
                if rec.emit:
                    self.assertIsNotNone(rec.precision_metres)
                    self.assertGreaterEqual(rec.precision_metres, DEV.default_sensitive_metres)

    def test_every_listed_species_is_gated(self):
        for sid in sorted(SENSITIVE_SPECIES_IDS):
            rec = gen("ST5877972166", sid)
            self.assertTrue(rec.is_sensitive, f"species {sid} not treated as sensitive")
            if rec.emit:
                self.assertGreaterEqual(rec.precision_metres, DEV.default_sensitive_metres)

    def test_ordinary_records_never_emit_finer_than_the_policy_allows(self):
        for ref in self.FINE_REFS:
            with self.subTest(ref=ref):
                rec = gen(ref, KNOWN_ORDINARY)
                if rec.emit:
                    self.assertGreaterEqual(rec.precision_metres, DEV.ordinary_resolution_metres)

    def test_a_metre_precision_sensitive_record_is_coarsened_not_leaked(self):
        rec = gen("ST5877972166", KNOWN_SENSITIVE)  # 1 m input
        self.assertTrue(rec.emit)
        self.assertEqual(rec.grid_ref, "ST57")  # 10 km
        self.assertEqual(rec.precision_metres, 10000)

    def test_emitted_reference_is_always_at_its_stated_precision(self):
        # GridCellSchema re-derives precision from the id and rejects a mismatch.
        for sid in (KNOWN_SENSITIVE, KNOWN_ORDINARY):
            for ref in self.FINE_REFS:
                rec = gen(ref, sid)
                if rec.emit:
                    self.assertEqual(precision_metres(rec.grid_ref), rec.precision_metres)

    def test_nothing_is_ever_emitted_at_an_undrawable_resolution(self):
        refs = [*self.FINE_REFS, "ST", "S", "ST57A", "ST58772", "junk", ""]
        for policy in (DEV, DEV_PROMOTING, UNAPPROVED_POLICY):
            for sid in (KNOWN_SENSITIVE, KNOWN_ORDINARY, None):
                for ref in refs:
                    rec = generalise(ref, sid, policy=policy, known=True)
                    if rec.emit:
                        self.assertIn(rec.precision_metres, PUBLIC_RESOLUTIONS_METRES)


class TestGeneralisationBehaviour(unittest.TestCase):
    def test_sensitive_species_are_generalised_not_dropped(self):
        # The behaviour change from the previous filtering.py: the record survives.
        rec = gen("ST587721", KNOWN_SENSITIVE)
        self.assertTrue(rec.emit)
        self.assertIsNotNone(rec.grid_ref)

    def test_ordinary_record_at_the_policy_resolution_keeps_its_precision(self):
        rec = gen("ST587721", KNOWN_ORDINARY)
        self.assertEqual(rec.grid_ref, "ST587721")
        self.assertEqual(rec.precision_metres, 100)

    def test_ordinary_record_finer_than_the_policy_is_coarsened_to_it(self):
        for ref, expected in (("ST58777216", "ST587721"), ("ST5877972166", "ST587721")):
            with self.subTest(ref=ref):
                rec = gen(ref, KNOWN_ORDINARY)
                self.assertEqual(rec.grid_ref, expected)
                self.assertEqual(rec.precision_metres, 100)

    def test_a_record_coarser_than_its_target_is_never_sharpened(self):
        # 10 km in, 10 km out - not pulled down to the 100 m ordinary resolution.
        rec = gen("ST57", KNOWN_ORDINARY)
        self.assertTrue(rec.emit)
        self.assertEqual(rec.grid_ref, "ST57")
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_coarse_policy_applies_to_every_input_finer_than_it(self):
        policy = PublicationPolicy(
            version="t",
            development_only=True,
            ordinary_resolution_metres=1000,
            public_id_salt="test" * 8,
        )
        for ref in ("ST5877972166", "ST58777216", "ST587721", "ST5872"):
            with self.subTest(ref=ref):
                rec = generalise(ref, KNOWN_ORDINARY, policy=policy, known=True)
                self.assertEqual(rec.grid_ref, "ST5872")
                self.assertEqual(rec.precision_metres, 1000)


class TestRowLevelSensitivity(unittest.TestCase):
    POLICY = PublicationPolicy(
        version="view-test",
        development_only=True,
        ordinary_resolution_metres=100,
        default_sensitive_metres=10000,
        row_sensitive_resolution_metres=1000,
        sensitive_record_type_metres={"bat roost": 10000},
        public_id_salt="test" * 8,
    )

    def test_a_row_flag_coarsens_an_ordinary_species_to_the_row_floor(self):
        rec = generalise(
            "ST587721",
            KNOWN_ORDINARY,
            policy=self.POLICY,
            known=True,
            row_sensitive=True,
        )
        self.assertTrue(rec.is_sensitive)
        self.assertEqual(rec.grid_ref, "ST5872")
        self.assertEqual(rec.precision_metres, 1000)

    def test_no_row_flag_leaves_an_ordinary_species_at_the_ordinary_floor(self):
        rec = generalise(
            "ST587721",
            KNOWN_ORDINARY,
            policy=self.POLICY,
            known=True,
            row_sensitive=False,
        )
        self.assertFalse(rec.is_sensitive)
        self.assertEqual(rec.precision_metres, 100)

    def test_a_row_flag_never_weakens_a_coarser_taxon_rule(self):
        rec = generalise(
            "ST5877972166",
            KNOWN_SENSITIVE,
            policy=self.POLICY,
            known=True,
            row_sensitive=True,
        )
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_row_flag_never_weakens_a_coarser_record_type_rule(self):
        rec = generalise(
            "ST5877972166",
            KNOWN_ORDINARY,
            policy=self.POLICY,
            known=True,
            row_sensitive=True,
            record_type="bat roost",
        )
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_coarse_input_is_never_sharpened(self):
        rec = generalise(
            "ST57",
            KNOWN_ORDINARY,
            policy=self.POLICY,
            known=True,
            row_sensitive=True,
        )
        self.assertEqual(rec.grid_ref, "ST57")
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_row_flag_without_an_explicit_row_policy_fails_closed(self):
        rec = generalise(
            "ST587721",
            KNOWN_ORDINARY,
            policy=DEV,
            known=True,
            row_sensitive=True,
        )
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "row-sensitivity-policy-missing")


class TestHundredKilometreReferencesAreNeverEmitted(unittest.TestCase):
    """A letters-only reference is a legitimate 100 km square that the client
    parser cannot read: ^[A-Z]{1,2}(\\d+)$ requires digits, so "ST" resolves to
    null and fails GridCellSchema. Emitting one would break the map."""

    def test_a_letters_only_reference_is_withheld(self):
        for sid in (KNOWN_ORDINARY, KNOWN_SENSITIVE):
            with self.subTest(sid=sid):
                rec = gen("ST", sid)
                self.assertFalse(rec.emit)
                self.assertEqual(rec.withheld_reason, "resolution-not-public")

    def test_it_is_still_withheld_when_promotion_is_permitted(self):
        # There is no square coarser than 10 km that the client can draw, so
        # there is nothing to promote a 100 km reference to.
        rec = gen("ST", KNOWN_ORDINARY, policy=DEV_PROMOTING)
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "resolution-not-public")

    def test_one_hundred_kilometres_is_not_a_drawable_resolution(self):
        self.assertNotIn(100000, PUBLIC_RESOLUTIONS_METRES)


class TestTetrads(unittest.TestCase):
    """A 2 km tetrad ("ST57A") is standard in UK botanical recording - and 54 of
    the 65 taxa on BRERC's sensitive list are plants."""

    def test_a_tetrad_is_withheld_by_default_because_the_client_cannot_draw_it(self):
        rec = gen("ST57A", KNOWN_ORDINARY)
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "resolution-not-public")

    def test_a_tetrad_is_promoted_to_ten_kilometres_when_the_policy_permits(self):
        rec = gen("ST57A", KNOWN_ORDINARY, policy=DEV_PROMOTING)
        self.assertTrue(rec.emit)
        self.assertEqual(rec.grid_ref, "ST57")
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_sensitive_tetrad_reaches_its_ten_kilometre_square(self):
        # Previously this was withheld as "cannot-generalise": `coarsen` refused
        # every tetrad, so a sensitive tetrad record was silently lost even
        # though its own 10 km square was already the required answer.
        rec = gen("ST57A", KNOWN_SENSITIVE)
        self.assertTrue(rec.emit)
        self.assertEqual(rec.grid_ref, "ST57")
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_tetrad_is_never_sharpened_to_a_finer_square(self):
        for policy in (DEV, DEV_PROMOTING):
            with self.subTest(policy=policy.version):
                rec = gen("ST57A", KNOWN_ORDINARY, policy=policy)
                if rec.emit:
                    self.assertGreaterEqual(rec.precision_metres, 10000)

    def test_next_public_resolution(self):
        self.assertEqual(next_public_resolution(2000), 10000)
        self.assertEqual(next_public_resolution(100), 1000)
        self.assertIsNone(next_public_resolution(100000))
        self.assertIsNone(next_public_resolution(10000))


class TestSensitiveRecordTypes(unittest.TestCase):
    """Record type is an independent safety axis. These synthetic rules test
    the mechanism; they are not a production interpretation of the incomplete
    client workbook."""

    POLICY = PublicationPolicy(
        version="test-record-types",
        development_only=True,
        ordinary_resolution_metres=100,
        default_sensitive_metres=10000,
        sensitive_record_type_metres={"bat roost": 10000, "field record": 1000},
        public_id_salt="test" * 8,
    )

    def test_a_sensitive_record_type_coarsens_an_ordinary_species(self):
        rec = generalise(
            "ST5877972166", KNOWN_ORDINARY, policy=self.POLICY, known=True, record_type="bat roost"
        )
        self.assertTrue(rec.emit)
        self.assertEqual(rec.precision_metres, 10000)
        self.assertTrue(rec.is_sensitive)

    def test_matching_is_case_and_whitespace_insensitive(self):
        rec = generalise(
            "ST5877972166",
            KNOWN_ORDINARY,
            policy=self.POLICY,
            known=True,
            record_type="  Bat Roost  ",
        )
        self.assertEqual(rec.precision_metres, 10000)

    def test_policy_keys_are_normalised_as_well_as_source_values(self):
        policy = PublicationPolicy(
            version="t",
            development_only=True,
            ordinary_resolution_metres=100,
            sensitive_record_type_metres={"  Bat Roost  ": 10000},
            public_id_salt="test" * 8,
        )
        rec = generalise(
            "ST5877972166",
            KNOWN_ORDINARY,
            policy=policy,
            known=True,
            record_type="bat roost",
        )
        self.assertTrue(rec.is_sensitive)
        self.assertEqual(rec.precision_metres, 10000)

    def test_an_unlisted_record_type_changes_nothing(self):
        rec = generalise(
            "ST5877972166",
            KNOWN_ORDINARY,
            policy=self.POLICY,
            known=True,
            record_type="casual observation",
        )
        self.assertEqual(rec.precision_metres, 100)
        self.assertFalse(rec.is_sensitive)

    def test_a_listed_type_marks_the_record_sensitive_even_when_not_coarser(self):
        # "field record" demands 1 km; the species already requires 10 km. The
        # resolution does not change, but the record is still sensitive.
        rec = generalise(
            "ST5877972166",
            KNOWN_SENSITIVE,
            policy=self.POLICY,
            known=True,
            record_type="field record",
        )
        self.assertTrue(rec.is_sensitive)
        self.assertEqual(rec.precision_metres, 10000)

    def test_the_coarser_of_species_and_record_type_wins(self):
        rec = generalise(
            "ST5877972166", KNOWN_SENSITIVE, policy=self.POLICY, known=True, record_type="bat roost"
        )
        self.assertEqual(rec.precision_metres, 10000)

    def test_a_missing_record_type_is_not_an_error(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                rec = generalise(
                    "ST587721", KNOWN_ORDINARY, policy=self.POLICY, known=True, record_type=value
                )
                self.assertTrue(rec.emit)


class TestFailClosed(unittest.TestCase):
    def test_missing_reference_is_withheld(self):
        for ref in (None, "", "   "):
            with self.subTest(ref=ref):
                rec = gen(ref, KNOWN_ORDINARY)
                self.assertFalse(rec.emit)
                self.assertEqual(rec.withheld_reason, "missing-grid-ref")

    def test_unparseable_reference_is_withheld(self):
        rec = gen("not-a-grid-ref", KNOWN_ORDINARY)
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "unparseable-grid-ref")

    def test_odd_digit_reference_is_withheld(self):
        rec = gen("ST58772", KNOWN_ORDINARY)
        self.assertFalse(rec.emit)
        self.assertEqual(rec.withheld_reason, "unparseable-grid-ref")

    def test_unknown_species_with_a_fine_reference_is_still_gated(self):
        rec = gen("ST5877972166", None)
        self.assertTrue(rec.is_sensitive)
        if rec.emit:
            self.assertGreaterEqual(rec.precision_metres, DEV.default_sensitive_metres)

    def test_withheld_records_carry_a_reason(self):
        for ref in (None, "junk", "ST58772", "ST57A", "ST"):
            with self.subTest(ref=ref):
                rec = gen(ref, KNOWN_ORDINARY)
                if not rec.emit:
                    self.assertIsNotNone(rec.withheld_reason)

    def test_a_withheld_record_carries_no_geometry_at_all(self):
        for ref in (None, "junk", "ST58772", "ST57A", "ST"):
            with self.subTest(ref=ref):
                rec = gen(ref, KNOWN_ORDINARY)
                if not rec.emit:
                    self.assertIsNone(rec.grid_ref)
                    self.assertIsNone(rec.precision_metres)


if __name__ == "__main__":
    unittest.main(verbosity=1)

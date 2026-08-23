"""`verified` verdict classification - the shared corpus.

This table is duplicated, case for case, in web/src/lib/api/verified.test.ts.
The server normalises before sending and the client normalises again, so the two
implementations must agree exactly or the same record reads differently depending
on which side you ask. If you change one table, change the other.

The distinction both must get right:

    negating ACCEPTANCE   -> a rejection      ("not accepted", "unaccepted")
    negating VERIFICATION -> not yet done     ("not verified", "unconfirmed")

A substring search reverses the first case: "Not accepted" contains "accept".
"""

import re
import unittest

from etl.contract import normalise_verified

#: Negating ACCEPTANCE is a rejection. This is the case a substring search inverts.
NEGATED_ACCEPTANCE = [
    ("Not accepted", "rejected"),
    ("not accepted", "rejected"),
    ("NOT ACCEPTED", "rejected"),
    ("un-accepted", "rejected"),
    ("unaccepted", "rejected"),
    ("never accepted", "rejected"),
    ("has not been accepted", "rejected"),
    ("non-accepted", "rejected"),
    ("disaccepted", "rejected"),
    ("verified - not accepted", "rejected"),
]

REJECTED = [
    ("Rejected", "rejected"),
    ("Rejected – not accepted", "rejected"),
    ("rejected (was accepted in error)", "rejected"),
    ("REJECTED - incorrect determination", "rejected"),
    ("Refused", "rejected"),
    ("Declined", "rejected"),
    ("Incorrect", "rejected"),
    ("Invalid record", "rejected"),
    ("Erroneous", "rejected"),
    ("Accepted then rejected", "rejected"),
]

#: Negating VERIFICATION means it has not been done yet - not that it failed.
UNCONFIRMED = [
    ("Unconfirmed", "unconfirmed"),
    ("unconfirmed record", "unconfirmed"),
    ("Not verified", "unconfirmed"),
    ("not verified", "unconfirmed"),
    ("unverified", "unconfirmed"),
    ("Un-verified", "unconfirmed"),
    ("never verified", "unconfirmed"),
    ("has not been verified", "unconfirmed"),
    ("Not confirmed", "unconfirmed"),
    ("unconfirmed", "unconfirmed"),
    ("Not checked", "unconfirmed"),
    ("unchecked", "unconfirmed"),
    ("Provisional", "unconfirmed"),
    ("Uncertain", "unconfirmed"),
    ("Pending", "unconfirmed"),
    ("Pending review", "unconfirmed"),
    ("Awaiting verification", "unconfirmed"),
    ("awaiting determination", "unconfirmed"),
    ("Needs verification", "unconfirmed"),
    ("needs confirmation", "unconfirmed"),
    ("need checking", "unconfirmed"),
    ("to be verified", "unconfirmed"),
    ("to be confirmed", "unconfirmed"),
    ("unconfirmed but accepted", "unconfirmed"),
]

ACCEPTED = [
    ("Accepted", "accepted"),
    ("Accepted - correct", "accepted"),
    ("Accepted – considered correct", "accepted"),
    ("accepted (BRERC)", "accepted"),
    ("Verified", "accepted"),
    ("verified by expert", "accepted"),
    ("Confirmed", "accepted"),
    ("Correct", "accepted"),
    ("Valid", "accepted"),
    ("Determined", "accepted"),
]

#: Real BRERC data contains values a parser cannot read. They must not count.
UNKNOWN = [
    ("BRERC (1)", "unknown"),
    ("", "unknown"),
    ("   ", "unknown"),
    ("1", "unknown"),
    ("yes", "unknown"),
    ("no", "unknown"),
    ("n/a", "unknown"),
    ("?", "unknown"),
    ("unknown", "unknown"),
]

ALL = NEGATED_ACCEPTANCE + REJECTED + UNCONFIRMED + ACCEPTED + UNKNOWN

_NEGATED = re.compile(r"\b(?:not|non|never|un|dis)[\s-]*(?:been[\s-]+)?accept", re.IGNORECASE)


class TestVerifiedCorpus(unittest.TestCase):
    def test_a_negated_acceptance_is_a_rejection(self):
        for raw, want in NEGATED_ACCEPTANCE:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), want)

    def test_an_active_negative_determination_is_a_rejection(self):
        for raw, want in REJECTED:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), want)

    def test_incomplete_verification_is_unconfirmed_not_rejected(self):
        for raw, want in UNCONFIRMED:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), want)

    def test_a_positive_determination_is_accepted(self):
        for raw, want in ACCEPTED:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), want)

    def test_an_unreadable_verdict_is_unknown_never_accepted(self):
        for raw, want in UNKNOWN:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_verified(raw), want)

    def test_the_corpus_is_the_size_the_client_table_declares(self):
        self.assertEqual(len(ALL), 63)

    def test_nothing_carrying_a_negated_acceptance_is_ever_accepted(self):
        # The single property that matters: a public map claims a verified record
        # has been checked by somebody. Reading a turned-down record as verified
        # breaks that claim, so it is asserted as a property, not case by case.
        for raw, _ in ALL:
            if _NEGATED.search(raw):
                with self.subTest(raw=raw):
                    self.assertNotEqual(normalise_verified(raw), "accepted")

    def test_non_string_values_degrade_rather_than_raising(self):
        for value in (None, 42, 3.5, True, [], {}):
            with self.subTest(value=value):
                self.assertIn(
                    normalise_verified(value), {"accepted", "unconfirmed", "rejected", "unknown"}
                )


class TestThePolicyVocabularyIsAuthoritativeForAcceptance(unittest.TestCase):
    """`PublicationPolicy.accepted_verification_values` is BRERC's own exhaustive
    list. Once supplied, nothing outside it may be read as accepted."""

    VOCABULARY = frozenset({"brerc verified", "accepted - correct"})

    def test_a_listed_value_is_accepted(self):
        for raw in ("BRERC verified", "  brerc verified  ", "Accepted - correct"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    normalise_verified(raw, accepted_values=self.VOCABULARY), "accepted"
                )

    def test_an_unlisted_value_can_never_be_accepted(self):
        for raw, _ in ALL:
            if raw.strip().lower() in self.VOCABULARY:
                continue
            with self.subTest(raw=raw):
                self.assertNotEqual(
                    normalise_verified(raw, accepted_values=self.VOCABULARY), "accepted"
                )

    def test_rejection_and_unconfirmed_still_classify(self):
        self.assertEqual(
            normalise_verified("Rejected", accepted_values=self.VOCABULARY), "rejected"
        )
        self.assertEqual(
            normalise_verified("Unconfirmed", accepted_values=self.VOCABULARY), "unconfirmed"
        )

    def test_a_heuristic_acceptance_outside_the_vocabulary_becomes_unknown(self):
        # "Verified" reads as accepted to the heuristic, but BRERC did not list
        # it, so it must not inflate the verified count.
        self.assertEqual(normalise_verified("Verified", accepted_values=self.VOCABULARY), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=1)

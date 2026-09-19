"""`verified` verdict classification - the shared corpus.

The full-dashboard web port that follows this PR adds
web/src/lib/api/verified.test.ts, which must duplicate this table case for case
against a normaliseVerified() that mirrors etl.contract. On this branch
web/src/lib/api/schemas.ts still classifies with a plain substring check, so
there is no client twin to keep in step with YET.
Once it lands, the server normalises before sending and the client normalises
again, so the two implementations must agree exactly or the same record reads
differently depending on which side you ask. If you change one table, change
the other.

The distinction both must get right:

    negating a determination's OUTCOME     -> a rejection   ("not accepted", "not valid")
    negating that a determination HAPPENED -> not yet done  ("not verified", "not determined")

A substring search reverses the first case: "Not accepted" contains "accept",
"Not valid" contains "valid", "never correct" contains "correct".
"""

import re
import unittest

from etl.contract import normalise_verified

#: Negating an OUTCOME word (accept*, correct, valid) is a rejection. This is the
#: case a substring search inverts - for every one of those words, not only
#: "accept".
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
    # The other outcome words, raised in review: these used to read as accepted.
    ("Not valid", "rejected"),
    ("NOT VALID", "rejected"),
    ("not correct", "rejected"),
    ("never correct", "rejected"),
    ("non-valid", "rejected"),
    ("un–accepted", "rejected"),  # en dash
    ("not a valid record", "rejected"),
    ("not considered correct", "rejected"),
    ("has never been correct", "rejected"),
    ("hasn't been accepted", "rejected"),
    ("wasn’t valid", "rejected"),  # curly apostrophe
    ("not correct determination", "rejected"),  # binds to "correct", not "determination"
    ("Accepted but not correct", "rejected"),
    # Negations other than "not"/"never": these used to read as accepted too.
    ("cannot be accepted", "rejected"),  # one word - \bnot\b never sees it
    ("Cannot accept", "rejected"),
    ("can't accept", "rejected"),
    ("No accepted determination", "rejected"),
    ("no valid determination", "rejected"),
    ("no acceptance", "rejected"),
    ("None accepted", "rejected"),
    # The adverb is the same word: the negation binds to it, not to "determined".
    ("Not correctly determined", "rejected"),
    ("not validly determined", "rejected"),
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
    ("not correct - rejected", "rejected"),
    ("not correct – rejected", "rejected"),
    ("in-valid", "rejected"),
    ("incorrectly determined", "rejected"),
    ("Incorrectly identified", "rejected"),
]

#: Negating that a determination HAPPENED means it has not been done yet - not
#: that it failed. "not determined" belongs here, not with the rejections.
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
    # A negated determination, raised in review: "determined" used to read as accepted.
    ("not determined", "unconfirmed"),
    ("Not determined", "unconfirmed"),
    ("undetermined", "unconfirmed"),
    ("Undetermined", "unconfirmed"),
    ("un-determined", "unconfirmed"),
    ("never determined", "unconfirmed"),
    ("has not been determined", "unconfirmed"),
    ("not yet determined", "unconfirmed"),
    ("not yet accepted", "unconfirmed"),
    ("hasn't yet been verified", "unconfirmed"),
    ("Indeterminate", "unconfirmed"),
    ("disconfirmed", "unconfirmed"),
    ("non-verified", "unconfirmed"),
    ("Not valid – awaiting verification", "unconfirmed"),
    ("not verified but accepted", "unconfirmed"),
    # Negations other than "not"/"never" in front of a PROCESS word.
    ("cannot be verified", "unconfirmed"),
    ("cannot be confirmed", "unconfirmed"),
    ("Cannot be determined", "unconfirmed"),
    ("no confirmed identification", "unconfirmed"),
    ("None verified", "unconfirmed"),
    ("without being verified", "unconfirmed"),
    ("without verification", "unconfirmed"),
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
    # A negation of something that is not a determination word negates nothing.
    ("Accepted – not a duplicate", "accepted"),
    ("Accepted – no comment", "accepted"),
    ("Accepted without comment", "accepted"),
    ("Determined by expert", "accepted"),
    ("Correctly determined", "accepted"),
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
    ("not a duplicate", "unknown"),
    ("none", "unknown"),
    ("Cannot say", "unknown"),
    ("no further action", "unknown"),
]

ALL = NEGATED_ACCEPTANCE + REJECTED + UNCONFIRMED + ACCEPTED + UNKNOWN

#: Deliberately independent of, and laxer than, the patterns in etl.contract:
#: ANY negation within two words of ANY word that reads as a determination.
#: If the implementation ever lets one of these through as "accepted", this
#: net catches it whatever the per-list expectation says.
_STEM = r"(?:accept|correct|valid|verif|confirm|check|determin)"
_NEGATED = re.compile(
    r"(?:\b(?:not|never|no|none|cannot|without)\b|n['’]t)[\s\-–—]*(?:\w+\s+){0,2}"
    + _STEM
    + r"|\b(?:un|non|dis|in)[\s\-–—]*"
    + _STEM,
    re.IGNORECASE,
)


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

    def test_the_corpus_size_is_pinned(self):
        # The client twin (web/src/lib/api/verified.test.ts, arriving with the
        # web port) must declare the same length. Update both together.
        self.assertEqual(len(ALL), 121)

    def test_nothing_carrying_a_negation_is_ever_accepted(self):
        # The single property that matters: a public map claims a verified record
        # has been checked by somebody. Reading a turned-down record as verified
        # breaks that claim, so it is asserted as a property, not case by case.
        negated = [raw for raw, _ in ALL if _NEGATED.search(raw)]
        self.assertGreater(len(negated), 40, "the net is not catching the corpus")
        for raw in negated:
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

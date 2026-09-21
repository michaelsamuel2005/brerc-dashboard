"""The public output contract, and the fields that may never cross it.

DESIGN: ALLOW-LIST, NOT DENY-LIST
---------------------------------
`PublicRecord` and `PublicCell` below carry only fields the public tier is allowed
to publish. Output is CONSTRUCTED from those fields, never by passing an input row
through a filter. A deny-list misses the column nobody thought of - a new export
adds `Recorder2`, or a supplier renames `Comments` to `Notes`, and it flows
straight through. An allow-list cannot leak a field it has no slot for.

`FORBIDDEN_FIELDS` therefore exists only as a belt-and-braces assertion, mirroring
the FORBIDDEN set in web/src/lib/api/contract.test.ts. If it ever fires, the
allow-list has been bypassed and that is the bug to fix.

VERIFIED STATUS
---------------
`normalise_verified` is the reference implementation that `normaliseVerified` in
web/src/lib/api/schemas.ts is to mirror EXACTLY, including the order of tests
(see CLIENT PARITY below for where the client stands). The order is
load-bearing: a verdict of "Rejected - not accepted" contains both "reject" and
"accept", and reading it as accepted would inflate the verified count with
rejected records.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Mirrors FORBIDDEN in web/src/lib/api/contract.test.ts. Lower-case, no separators.
FORBIDDEN_FIELDS: frozenset[str] = frozenset(
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
)


def normalise_field_name(key: object) -> str:
    """Normalise a field name for exact privacy-alias matching.

    Matching remains exact after normalisation. Substring matching would reject
    legitimate public keys such as ``sensitivityPolicy`` and
    ``sensitiveSpeciesNote``.
    """
    text = unicodedata.normalize("NFKC", str(key)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


VerifiedStatus = str  # "accepted" | "unconfirmed" | "rejected" | "unknown"

# Verdict classification. Order is load-bearing.
#
# The distinction that matters, and that a naive implementation gets wrong:
#
#   negating a determination's OUTCOME     -> a rejection
#       "not accepted", "unaccepted", "not valid", "never correct", "not a valid record"
#   negating that a determination HAPPENED -> not yet done
#       "not verified", "unconfirmed", "not determined", "undetermined", "not yet accepted"
#
# A plain substring search reverses the first case entirely - "Not accepted"
# contains "accept" and is read as ACCEPTED. The same trap exists for every
# other word that reads as acceptance: "Not valid" contains "valid" and "not
# determined" contains "determined". The negation patterns below are therefore
# built from the SAME word list as the acceptance pattern (_POSITIVE), so the
# two vocabularies cannot drift apart: a negation from _NOT (or a bound
# prefix) in front of any word from _POSITIVE is classified at step 2 or 3 of
# _classify, before step 4 can see it. That guarantee is structural for the
# negation vocabulary listed here and no wider - English has other ways to
# say no ("fails to be accepted", "lacks verification"), and a verdict
# phrased that way reads as its positive word says. This heuristic is a
# fallback: in production `accepted_verification_values` is mandatory and
# authoritative (see normalise_verified), so only the rejected / unconfirmed
# / unknown split rests on the patterns below.
#
# Which negated forms mean what:
#
#   * A negated OUTCOME word (accept*, correct, valid - adverbs "correctly"
#     and "validly" included) is a REJECTION: the determiner looked and turned
#     the record down. "not correctly determined" negates "correctly", so it
#     is a rejection, not an unfinished determination.
#   * A negated PROCESS word (verif*, confirm*, check*, determin*) is
#     UNCONFIRMED: nobody has established a verdict. "undetermined" and "not
#     determined" belong here and must not be read as rejections. The rare
#     "dis-"/"non-" forms ("disconfirmed", "non-verified") are read the same
#     way; the fail-safe direction is identical either way - not accepted.
#     An idiom that negates the NEED for the process ("no further
#     verification needed") lands here as well and reads as unconfirmed: the
#     patterns read words, not intent, and unconfirmed is the safe side.
#   * "not yet <anything>" is UNCONFIRMED, whatever follows "yet" and whether
#     or not it is a determination word: "yet" says the process is still open.
#   * "in-" is only a negation where it forms a word ("incorrect", "invalid",
#     "incorrectly"), so it is spelled out in _REJECTED rather than added to
#     the generic prefixes ("in accepted form" negates nothing).
#   * The free-standing negations are "not", "never", "no", "none", "cannot",
#     "without" and a contracted "n't" (_NOT). One binds to the NEAREST
#     following determination word, at most two words away ("has not been
#     accepted", "not a valid record", "cannot be determined"), so that "not
#     correct determination" negates "correct" (rejected) rather than
#     "determination", and "Accepted - not a duplicate" negates nothing that
#     reads as acceptance and stays accepted. The two-word reach is
#     deliberate: any further and a negation starts claiming words of a later
#     clause. The binding is textual, not grammatical - punctuation between
#     the negation and the word ("not, accepted") and a gap of more than two
#     words ("not been able to be accepted") are not bridged.
#   * Bound prefixes ("un", "non", "dis") must be glued or dash-joined
#     ("unaccepted", "non-valid", "un–accepted"), otherwise every word
#     beginning with "un" would act as a negation.
#
# CLIENT PARITY. On this branch web/src/lib/api/schemas.ts still classifies
# with a plain substring check (`s.includes("accept")`) and has the defect
# described above. The full-dashboard web port that follows this PR replaces
# it with a negation-aware normaliseVerified() and adds
# web/src/lib/api/verified.test.ts; that port must be brought into parity with
# the patterns here and the corpus in api/tests/test_verified_parity.py before
# it merges. Until then the server is the only side that classifies correctly
# and there is no parity to preserve. Once it has landed: if you change one
# side, change both - the server normalises before sending and the client
# normalises again, so a divergence makes the same record read differently
# depending on which side you ask.

#: Separator allowed between a negation and the word it negates: whitespace,
#: hyphen, en dash, em dash ("un-accepted", "non–valid").
_SEP = r"[\s\-\u2013\u2014]"

#: Every word a verdict can be read as acceptance by. "correct" and "valid"
#: take their adverbs too, so "correctly determined" and "not correctly
#: determined" turn on the same word. Used by _ACCEPTED and by the negation
#: patterns, so that both always cover the same vocabulary.
_POSITIVE = r"(?:accept\w*|verified|confirmed|correct(?:ly)?|valid(?:ly)?|determined)"

#: The words that describe the verification PROCESS rather than its outcome.
_PROCESS = r"(?:verif\w*|confirm\w*|check\w*|determin\w*)"

#: The stems of both lists. A free-standing negation may not skip over one of
#: these on its way to the word it negates.
_DETERMINATION_STEM = r"(?:accept|correct|valid|verif|confirm|check|determin)"

#: A free-standing negation. This list is the whole vocabulary the guarantee
#: above rests on; anything outside it is not a negation to these patterns.
#: "cannot" is one word, so \bnot\b alone would never see it.
_NOT = r"(?:\b(?:not|never|no|none|cannot|without)\b|n['\u2019]t)"

#: A negation in front of a word, with the binding rules described above. Up to
#: two words may sit between a free-standing negation and the word it negates
#: ("has not been accepted", "not a valid record", "not considered correct").
_NEGATED = (
    r"(?:"
    + _NOT
    + _SEP
    + r"*(?:(?!"
    + _DETERMINATION_STEM
    + r")\w+"
    + _SEP
    + r"+){0,2}"
    + r"|\b(?:un|non|dis)"
    + _SEP
    + r"*)"
)

#: An active negative determination.
_REJECTED = re.compile(
    r"\b(?:reject\w*|refus\w*|declin\w*|in[\-\u2013\u2014]?(?:correct|valid)(?:ly)?|erroneous)\b",
    re.IGNORECASE,
)

#: Verification not completed. Checked BEFORE negated acceptance so that a
#: negated PROCESS word ("unconfirmed", "not verified", "not determined") is
#: not misread as a rejection.
_UNCONFIRMED = re.compile(
    r"\b(?:indetermin\w*|provisional|uncertain|pending|await\w*|"
    r"needs?" + _SEP + r"+(?:verification|confirmation|checking|approval)|"
    r"to" + _SEP + r"+be" + _SEP + r"+(?:verified|confirmed|checked))\b"
    r"|" + _NOT + _SEP + r"+yet\b"
    r"|" + _NEGATED + _PROCESS + r"\b",
    re.IGNORECASE,
)

#: A negated OUTCOME word - and, as a backstop, any negated word from _POSITIVE
#: that the unconfirmed patterns did not claim. Only reached once those have
#: not matched.
_NEGATED_ACCEPT = re.compile(_NEGATED + _POSITIVE + r"\b", re.IGNORECASE)

#: A positive determination. The ONLY path to "accepted".
_ACCEPTED = re.compile(r"\b" + _POSITIVE + r"\b", re.IGNORECASE)


def _classify(text: str) -> VerifiedStatus:
    """Heuristic classification of a free-text verdict. Order is load-bearing.

        1. explicit rejection                 -> "rejected"
        2. verification not completed         -> "unconfirmed"
        3. negated acceptance                 -> "rejected"
        4. explicit acceptance                -> "accepted"
        5. anything else                      -> "unknown"

    Only step 4 yields "accepted", and only when no negation matched first.
    """
    if _REJECTED.search(text):
        return "rejected"
    if _UNCONFIRMED.search(text):
        return "unconfirmed"
    if _NEGATED_ACCEPT.search(text):
        return "rejected"
    if _ACCEPTED.search(text):
        return "accepted"
    return "unknown"


def normalise_verified(
    raw: object, *, accepted_values: frozenset[str] | None = None
) -> VerifiedStatus:
    """Normalise a raw verification verdict. Fail-safe on anything ambiguous.

    Anything unrecognised is "unknown", never "accepted" - an unreadable verdict
    must not inflate a verified count. The real BRERC samples contain values such
    as "BRERC (1)" that mean nothing to a parser; those become "unknown", which
    is the honest answer.

    `accepted_values` is `PublicationPolicy.accepted_verification_values`: BRERC's
    own exhaustive list of verdicts that count as accepted, lower-cased. When
    supplied it is AUTHORITATIVE for that verdict - a value outside it can never
    be read as accepted, whatever the heuristic thinks. The heuristic still runs,
    but only to distinguish "rejected" from "unconfirmed" from "unknown", which
    are presentational rather than a claim about data quality.
    """
    if raw is None:
        return "unknown"
    text = str(raw).strip()
    if not text:
        return "unknown"

    if accepted_values is None:
        return _classify(text)

    if text.casefold() in accepted_values:
        return "accepted"
    status = _classify(text)
    return "unknown" if status == "accepted" else status


@dataclass(frozen=True)
class PublicRecord:
    """One record as the public tier may see it.

    There is deliberately no field for a recorder name, precise coordinate,
    comment or sensitivity marker. If one is needed, that is a governance decision,
    not a code change made in passing.
    """

    record_id: str
    #: Internal aggregation/join key. It is deliberately omitted by ``to_api``
    #: because the records endpoint is scoped to one species.
    species_id: str
    scientific_name: str
    common_name: str | None
    grid_ref: str
    precision_metres: int
    place: str | None
    year: int
    abundance: str | None
    record_type: str | None
    verified: VerifiedStatus
    source: str

    def to_api(self) -> dict[str, object]:
        """Serialise to the RecordRowSchema shape in web/src/lib/api/schemas.ts."""
        return {
            "id": self.record_id,
            "scientificName": self.scientific_name,
            "commonName": self.common_name,
            "gridRef": self.grid_ref,
            "precisionMetres": self.precision_metres,
            "place": self.place,
            "year": self.year,
            "abundance": self.abundance,
            "recordType": self.record_type,
            "verified": self.verified,
            "source": self.source,
        }


@dataclass(frozen=True)
class PublicCell:
    """One aggregated map square, matching GridCellSchema."""

    #: Internal parent key. The public cell response is species-scoped, so this
    #: is not serialized into GridCellSchema.
    species_id: str
    #: Internal filter cohort. The API omits it because one response is scoped
    #: to a selected year (or combines already-safe yearly cohorts).
    year: int
    cell_id: str
    precision_metres: int
    record_count: int
    verified_count: int

    def to_api(self) -> dict[str, object]:
        return {
            "cellId": self.cell_id,
            "precisionMetres": self.precision_metres,
            "recordCount": self.record_count,
            "verifiedCount": self.verified_count,
        }


def assert_no_forbidden_fields(payload: object, path: str = "$") -> list[str]:
    """Walk a payload and return the paths of any forbidden key.

    Belt and braces. An empty list is the only acceptable result; anything else
    means the allow-list was bypassed upstream.
    """
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            flat = normalise_field_name(key)
            if flat in FORBIDDEN_FIELDS:
                found.append(f"{path}.{key}")
            found.extend(assert_no_forbidden_fields(value, f"{path}.{key}"))
    elif isinstance(payload, list | tuple):
        for i, item in enumerate(payload):
            found.extend(assert_no_forbidden_fields(item, f"{path}[{i}]"))
    return found

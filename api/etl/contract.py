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
`normalise_verified` mirrors `normaliseVerified` in web/src/lib/api/schemas.ts
EXACTLY, including the order of tests. The order is load-bearing: a verdict of
"Rejected - not accepted" contains both "reject" and "accept", and reading it as
accepted would inflate the verified count with rejected records.
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
#   negating ACCEPTANCE   -> a rejection      ("not accepted", "unaccepted")
#   negating VERIFICATION -> not yet done     ("not verified", "unconfirmed")
#
# A plain substring search reverses the first case entirely - "Not accepted"
# contains "accept" and is read as ACCEPTED.
#
# The same defect was present in normaliseVerified() in
# web/src/lib/api/schemas.ts and was corrected on 28 Jul 2026. The two
# implementations are now in exact parity over a shared 63-case corpus, pinned
# by test_verified_parity.py here and web/src/lib/api/verified.test.ts there.
# If you change one, change both - the server normalises before sending and the
# client normalises again, so a divergence makes the same record read
# differently depending on which side you ask.

#: An active negative determination.
_REJECTED = re.compile(
    r"\b(?:reject\w*|refus\w*|declin\w*|incorrect|invalid|erroneous)\b",
    re.IGNORECASE,
)

#: Verification not completed. Checked BEFORE negated-acceptance so that
#: "unconfirmed" and "not verified" are not misread as rejections.
_UNCONFIRMED = re.compile(
    r"\b(?:unconfirm\w*|unverif\w*|provisional|uncertain|pending|await\w*|"
    r"(?:not|never|un)[\s\-]*(?:been[\s\-]+)?(?:verif\w*|confirm\w*|check\w*)|"
    r"needs?[\s\-]+(?:verification|confirmation|checking|approval)|"
    r"to[\s\-]+be[\s\-]+(?:verified|confirmed|checked))\b",
    re.IGNORECASE,
)

#: A negated acceptance. Only reached once the unconfirmed patterns have not matched.
_NEGATED_ACCEPT = re.compile(
    r"\b(?:not|non|never|un|dis)[\s\-]*(?:been[\s\-]+)?accept\w*",
    re.IGNORECASE,
)

#: A positive determination.
_ACCEPTED = re.compile(
    r"\b(?:accept\w*|verified|confirmed|correct|valid|determined)\b",
    re.IGNORECASE,
)


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

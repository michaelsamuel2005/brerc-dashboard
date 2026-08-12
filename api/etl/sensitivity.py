"""The sensitive-species gate: generalise, never silently drop.

WHAT CHANGED AND WHY
--------------------
The previous `filtering.py` REMOVED sensitive species from the public dataset:

    return df[~df["species_id"].isin(SENSITIVE_SPECIES_IDS)].copy()

That is safe from a disclosure standpoint, but it contradicts the project's own
governance rule and quietly destroys data. `Data_Governance_and_Compliance.md`
says, of sensitive records:

    "Generalise, do not randomise - present as presence-in-a-coarser-square"

Dropping is not generalising. A records centre whose public map silently omits
protected species shows a false distribution, with no indication anything is
missing - and it removes exactly the records BRERC most often needs to show at
coarse resolution. This module generalises instead.

WHERE THE DECISIONS LIVE
------------------------
This module owns the MECHANISM. It does not own the POLICY. What resolution a
taxon requires, what happens to an unresolved name, and whether a place name may
be published are BRERC's decisions and live on `policy.PublicationPolicy`, which
must be passed in explicitly - there is deliberately no default, so a caller who
forgets it gets a TypeError rather than a silently over- or under-protected run.

FAIL-CLOSED
-----------
Anything not positively confirmed as safe is treated as sensitive. That covers a
missing species id, an unparseable one, an id absent from the taxonomy, and any
id the dictionary or the retained snapshot flags.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .gridref import (
    PUBLIC_RESOLUTIONS_METRES,
    coarsen,
    is_public_resolution,
    normalise,
    precision_metres,
)
from .policy import PublicationPolicy

#: Species flagged sensitive in the BRERC species dictionary, as NORMALISED
#: STRING ids.
#:
#: PROVENANCE (confirmed 28 Jul 2026): these are the 65 taxa flagged
#: `SENSITIVE = "yes"` in the BRERC species dictionary ("Full BRERC species
#: dictionary", 96,824 rows), and they match the separate "brerc sensitive
#: species list" export exactly - same 65 SPECIES_No values.
#:
#: THIS IS A SNAPSHOT, NOT THE SOURCE OF TRUTH. BRERC maintains the list; ours
#: is a copy taken on the date above and it WILL drift. `is_sensitive` therefore
#: takes the UNION of this snapshot and the flag carried by the loaded species
#: dictionary. A union can only ever over-protect: a taxon BRERC has since added
#: is caught by the live dictionary, and one BRERC has since removed stays
#: protected here until someone updates this constant deliberately.
#:
#: STILL OUTSTANDING: neither source carries a per-taxon resolution column. BRERC
#: must confirm the required public resolution for each taxon (NBN assigns these
#: individually: 1/2/10/50/100 km) plus the list's version and review date. Until
#: then `PublicationPolicy.default_sensitive_metres` applies to all of them.
#:
#: STRINGS, NOT INTEGERS. A BRERC species number is not numeric: 61,080 of the
#: 96,824 dictionary entries are alphanumeric - "BRERC10469", "6973a", "Z5567",
#: "5519a", "25913A". An earlier version did int(species_id), which raised on all
#: of those and fell through to fail-closed, needlessly generalising 50 of 998
#: ordinary records to 10 km. Safe, but it silently destroyed the precision of
#: most invertebrate records. Ids are therefore compared as normalised strings.
# fmt: off
# The grid layout is deliberate: 65 ids, readable and countable at a glance,
# so a reviewer can check them against BRERC's list without scrolling.
SENSITIVE_SPECIES_IDS: frozenset[str] = frozenset(str(_i) for _i in {
    16957, 2028, 2169, 2724, 2991, 33009, 3685, 5262, 5865, 6058, 6499,
    2195, 2319, 2404, 2720, 2891, 2975, 3012, 3439, 3637, 4106, 4173,
    4435, 4519, 4521, 4582, 2183, 2285, 2288, 2292, 2293, 2306, 2313,
    2320, 2343, 2345, 2374, 2525, 2622, 2648, 2746, 2840, 3073, 3103,
    3166, 3262, 3306, 3337, 33430, 33996, 3530, 3928, 39527, 4015, 4105,
    4213, 4220, 4226, 4266, 4289, 5107, 5192, 5699, 5745, 6470,
})
# fmt: on

# Bound into every production precision approval. The digest is derived rather
# than hand-copied, so adding/removing one id changes the runtime evidence and a
# release approved against the previous snapshot fails before reading a row.
SENSITIVE_SNAPSHOT_VERSION = "brerc-sensitive-species-2026-07-28"
SENSITIVE_SNAPSHOT_SHA256 = hashlib.sha256(
    "\n".join(sorted(SENSITIVE_SPECIES_IDS)).encode("ascii")
).hexdigest()


@dataclass(frozen=True)
class GeneralisedRecord:
    """One record after the gate. `grid_ref` is None when it must be withheld."""

    grid_ref: str | None
    precision_metres: int | None
    is_sensitive: bool
    withheld_reason: str | None

    @property
    def emit(self) -> bool:
        """True only when this record may appear on the public tier."""
        return self.grid_ref is not None and is_public_resolution(self.precision_metres)


def normalise_species_id(species_id: object) -> str | None:
    """Normalise a BRERC species number for comparison, or None if unusable.

    Handles the shapes a real export produces: "2028", "BRERC10469", "6973a",
    and the 2028.0 that a spreadsheet reader yields for an integer column that
    contains blanks. Case and surrounding whitespace are not significant.
    """
    if species_id is None:
        return None
    if isinstance(species_id, bool):
        return None
    if isinstance(species_id, float):
        if species_id != species_id:  # NaN
            return None
        if species_id.is_integer():
            return str(int(species_id))
        return None  # a fractional species number is nonsense
    text = str(species_id).strip().upper()
    if not text or text in {"NAN", "NONE", "NULL"}:
        return None
    return text


def is_sensitive(species_id: object, *, flagged: bool | None = None) -> bool:
    """True when the species must be treated as sensitive, including on error.

    `flagged` is the sensitivity flag from the loaded BRERC species dictionary,
    where one is available. It is UNIONED with the retained snapshot rather than
    replacing it: either source saying "sensitive" is enough. Passing
    `flagged=False` therefore does not clear a snapshot entry - deliberately, so
    that a stale or partially-loaded dictionary cannot silently unprotect a taxon.
    """
    if flagged:
        return True
    sid = normalise_species_id(species_id)
    if sid is None:
        return True  # fail closed on an unusable id
    return sid in SENSITIVE_SPECIES_IDS


def next_public_resolution(metres: int) -> int | None:
    """The finest drawable resolution strictly coarser than `metres`, if any."""
    coarser = [m for m in PUBLIC_RESOLUTIONS_METRES if m > metres]
    return min(coarser) if coarser else None


def generalise(
    grid_ref: object,
    species_id: object,
    *,
    policy: PublicationPolicy,
    known: bool = False,
    record_type: object = None,
    flagged_sensitive: bool | None = None,
    row_sensitive: bool = False,
) -> GeneralisedRecord:
    """Apply the gate to a single record, under an explicit policy.

    `policy` is REQUIRED. An earlier version defaulted it, which meant a caller
    who forgot it silently got the unapproved policy's behaviour - in practice a
    100% withhold that reads in the report like a data problem.

    `known` must be True only when the species resolved against the BRERC
    taxonomy. A species id that is well-formed but absent from the dictionary is
    NOT known, and must not be treated as ordinary - that was a fail-open path:
    any unrecognised numeric id was published at the ordinary resolution.

    `record_type` carries a second sensitivity axis, independently of the taxon.
    The supplied drop-down workbook is not yet an approved rule source: 47 of
    155 named types have an aligned ``sensitive=yes`` flag, one flag has no type,
    and one explicitly sensitive-looking type has no flag. A release must use a
    corrected, versioned BRERC classification. Where an approved type demands a
    coarser square than the species does, the coarser one wins.

    `flagged_sensitive` is the species dictionary's own flag - see
    `is_sensitive`. `row_sensitive` is the occurrence row's own sensitivity
    control. These are unioned: any one sensitivity axis is sufficient.

    Withholds rather than emits whenever the safe answer cannot be computed.
    Every withheld record carries a reason, so a run reconciles exactly.
    """
    normalised_id = normalise_species_id(species_id)
    # A policy entry is itself an authoritative sensitivity decision. Earlier,
    # the override was consulted only after the snapshot/dictionary had already
    # classified the taxon as sensitive. A newly added taxon present only in the
    # approved policy therefore fell through to the ordinary resolution.
    taxon_sensitive = is_sensitive(
        species_id, flagged=flagged_sensitive
    ) or policy.has_sensitive_species_rule(normalised_id)
    sensitive = taxon_sensitive or row_sensitive
    target = policy.resolution_for(normalised_id, sensitive=taxon_sensitive, known=known)
    if target is None:
        return GeneralisedRecord(None, None, sensitive, "species-not-permitted")

    if row_sensitive:
        # A row-level flag is an independent floor. It must not accidentally
        # select a taxon's fallback/override: the three axes (taxon, row and
        # record type) are distinct and the coarsest applicable result wins.
        row_floor = policy.row_sensitive_resolution_metres
        if row_floor is None:
            return GeneralisedRecord(None, None, True, "row-sensitivity-policy-missing")
        target = max(target, row_floor)

    by_type = policy.resolution_for_record_type(record_type)
    if by_type is not None:
        # The record type is on BRERC's sensitive list, so the record IS
        # sensitive even where the species is not and even where the species
        # target already satisfies it.
        sensitive = True
        target = max(target, by_type)

    if grid_ref is None or not str(grid_ref).strip():
        return GeneralisedRecord(None, None, sensitive, "missing-grid-ref")

    cleaned = normalise(str(grid_ref))
    current = precision_metres(cleaned)
    if current is None:
        return GeneralisedRecord(None, None, sensitive, "unparseable-grid-ref")

    # Never sharpen: a record coarser than its target keeps its own resolution.
    effective_target = max(target, current)

    # The resolution is real but the client cannot draw it - a 2 km tetrad, or a
    # letters-only 100 km reference. Publishing at that resolution is not an
    # option; the only question is whether the policy lets us coarsen further.
    if not is_public_resolution(effective_target):
        if not policy.coarsen_unpublishable_resolutions:
            return GeneralisedRecord(None, None, sensitive, "resolution-not-public")
        promoted = next_public_resolution(effective_target)
        if promoted is None:
            # Coarser than the coarsest square the client can draw. Nothing safe
            # to emit - a 100 km reference is the live case.
            return GeneralisedRecord(None, None, sensitive, "resolution-not-public")
        effective_target = promoted

    out = coarsen(cleaned, effective_target)
    if out is None:
        return GeneralisedRecord(None, None, sensitive, "cannot-generalise")

    out_precision = precision_metres(out)

    # Belt and braces. Neither branch should be reachable; both are cheap, and
    # the cost of being wrong here is publishing a protected location.
    if out_precision is None or not is_public_resolution(out_precision):
        return GeneralisedRecord(None, None, sensitive, "resolution-not-public")
    if out_precision < target:
        return GeneralisedRecord(None, None, sensitive, "finer-than-required")

    return GeneralisedRecord(out, out_precision, sensitive, None)

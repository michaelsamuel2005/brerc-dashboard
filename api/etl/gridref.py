"""British National Grid reference parsing and generalisation.

WHY THIS MODULE EXISTS, AND THE TRAP IT AVOIDS
----------------------------------------------
An OS grid reference such as "ST587721" is NOT a single number that can be
truncated. It is a 100 km square letter pair followed by *interleaved halves*:
the first half of the digits is the easting, the second half is the northing.

    ST 587 721   ->   easting 587, northing 721   (100 m resolution)

To generalise it to 1 km you must truncate EACH HALF independently:

    easting 587 -> 58 , northing 721 -> 72  =>  "ST5872"     CORRECT
    "ST587721"[:6]                          =>  "ST5877"     WRONG

The wrong version is easy to write, looks plausible, and would silently relocate
every generalised record - moving protected species to squares they were never
recorded in. It is tested explicitly below.

Precision is DERIVED from the reference string, never assumed. This mirrors
web/src/lib/geo/gridref.ts so the server and client agree on what a square means.
"""

from __future__ import annotations

import re

# Digit pairs -> metres per axis. Must stay identical to PER_AXIS_METRES in
# web/src/lib/geo/gridref.ts.
_PAIRS_TO_METRES: dict[int, int] = {1: 10000, 2: 1000, 3: 100, 4: 10, 5: 1}
_METRES_TO_PAIRS: dict[int, int] = {m: p for p, m in _PAIRS_TO_METRES.items()}

# A British National Grid square is exactly two OS letters, excludes I, and
# must resolve inside the 700 km x 1,300 km National Grid extent. Public numeric
# references then carry 1-5 digits per axis (2-10 total).
_NUMERIC_RE = re.compile(r"^([A-HJ-Z]{2})(\d{2,10})$")
# Tetrad: 10 km reference plus a letter A-Z excluding O  => 2 km resolution.
_TETRAD_RE = re.compile(r"^([A-HJ-Z]{2})(\d{2})([A-NP-Z])$")
_LETTERS_RE = re.compile(r"^[A-HJ-Z]{2}$")

#: Resolutions the client can actually PARSE AND DRAW, finest first.
#:
#: This is a CLIENT-CONTRACT fact, not a permission. It says what the browser can
#: render; it says nothing about what BRERC has agreed to publish. That decision
#: lives in policy.PublicationPolicy, which may only ever choose from this set.
#:
#: Two resolutions are deliberately ABSENT because web/src/lib/geo/gridref.ts
#: cannot parse them, so emitting either produces a square the client fails to draw:
#:   - 2 km (tetrad):     its trailing letter is rejected by ^[A-Z]{1,2}(\d+)$
#:   - 100 km (letters):  "ST" has no digits, so the same regex rejects it
PUBLIC_RESOLUTIONS_METRES: tuple[int, ...] = (100, 1000, 10000)

#: Mirrors PUBLIC_MIN_PRECISION_METRES in web/src/lib/api/schemas.ts. Same name in
#: both languages so a change on either side is greppable across the repository.
#:
#: !! A CONTRACT LIMIT, NOT AN AUTHORISATION. !!
#: That the frontend accepts 100 m does not mean BRERC has agreed to publish real
#: locations at 100 m. The operative resolution comes from the publication policy.
PUBLIC_MIN_PRECISION_METRES: int = PUBLIC_RESOLUTIONS_METRES[0]

#: The coarsest square the client can draw. A record that must be generalised
#: beyond this cannot be published at all.
PUBLIC_MAX_PRECISION_METRES: int = PUBLIC_RESOLUTIONS_METRES[-1]

#: Tetrad resolution. Recognised on input (it is standard in UK botanical
#: recording) but never emitted - see PUBLIC_RESOLUTIONS_METRES.
TETRAD_METRES: int = 2000

#: A letters-only reference. Recognised on input, never emitted.
HECTAD_LETTERS_METRES: int = 100000


def normalise(ref: str) -> str:
    """Upper-case and strip all whitespace. Does not validate."""
    return re.sub(r"\s+", "", str(ref)).upper()


def _truncating_mod(value: int, divisor: int) -> int:
    """Remainder with truncation toward zero, matching the OS/JavaScript formula."""
    return value - int(value / divisor) * divisor


def valid_100km_square(letters: str) -> bool:
    """Whether a two-letter pair denotes a square inside Great Britain's grid."""
    cleaned = normalise(letters)
    if not _LETTERS_RE.fullmatch(cleaned):
        return False
    first = ord(cleaned[0]) - ord("A")
    second = ord(cleaned[1]) - ord("A")
    if first > 7:  # I is omitted from OS lettering
        first -= 1
    if second > 7:
        second -= 1
    e100 = _truncating_mod(first - 2, 5) * 5 + _truncating_mod(second, 5)
    n100 = 19 - (first // 5) * 5 - (second // 5)
    return 0 <= e100 <= 6 and 0 <= n100 <= 12


def _hundred_km_origin(letters: str) -> tuple[int, int] | None:
    """Return the south-west BNG origin of a valid letter pair.

    The arithmetic is the same validation profile used by
    :func:`valid_100km_square`; keeping it here avoids teaching the database
    writer a second, subtly different OS-grid implementation.
    """
    cleaned = normalise(letters)
    if not _LETTERS_RE.fullmatch(cleaned):
        return None
    first = ord(cleaned[0]) - ord("A")
    second = ord(cleaned[1]) - ord("A")
    if first > 7:
        first -= 1
    if second > 7:
        second -= 1
    e100 = _truncating_mod(first - 2, 5) * 5 + _truncating_mod(second, 5)
    n100 = 19 - (first // 5) * 5 - (second // 5)
    if not 0 <= e100 <= 6 or not 0 <= n100 <= 12:
        return None
    return (e100 * 100000, n100 * 100000)


def precision_metres(ref: str) -> int | None:
    """Resolution in metres implied by a reference, or None if unparseable.

    Recognises letters-only (100 km), even-digit references, and tetrads (2 km).
    An odd digit count is not a valid reference and returns None rather than
    guessing - guessing here would fabricate precision.
    """
    cleaned = normalise(ref)
    if not cleaned:
        return None

    tetrad = _TETRAD_RE.match(cleaned)
    if tetrad and valid_100km_square(tetrad.group(1)):
        return TETRAD_METRES

    match = _NUMERIC_RE.match(cleaned)
    if match and valid_100km_square(match.group(1)):
        digits = match.group(2)
        if len(digits) % 2 != 0:
            return None
        return _PAIRS_TO_METRES.get(len(digits) // 2)

    # Letters alone identify a 100 km square.
    if _LETTERS_RE.fullmatch(cleaned) and valid_100km_square(cleaned):
        return HECTAD_LETTERS_METRES

    return None


def split(ref: str) -> tuple[str, str, str] | None:
    """Split into (letters, easting_digits, northing_digits).

    Returns None for anything not a plain numeric reference - tetrads are
    deliberately excluded because their letter suffix is not an axis split.
    """
    cleaned = normalise(ref)
    if _LETTERS_RE.fullmatch(cleaned) and valid_100km_square(cleaned):
        return (cleaned, "", "")
    match = _NUMERIC_RE.match(cleaned)
    if not match or not valid_100km_square(match.group(1)):
        return None
    letters, digits = match.group(1), match.group(2)
    if len(digits) % 2 != 0:
        return None
    half = len(digits) // 2
    return (letters, digits[:half], digits[half:])


def square_bounds(ref: str) -> tuple[int, int, int, int] | None:
    """Return ``(min_easting, min_northing, max_easting, max_northing)``.

    Only numeric public grid references are accepted.  Tetrads and
    letters-only squares are valid source inputs but are never emitted by the
    current public contract, so accepting them here would let the database
    layer invent a geometry the browser cannot reproduce.
    """
    metres = precision_metres(ref)
    if metres not in PUBLIC_RESOLUTIONS_METRES:
        return None
    parts = split(ref)
    if parts is None:
        return None
    letters, easting_digits, northing_digits = parts
    origin = _hundred_km_origin(letters)
    if origin is None or not easting_digits or not northing_digits:
        return None
    min_easting = origin[0] + int(easting_digits) * metres
    min_northing = origin[1] + int(northing_digits) * metres
    return (
        min_easting,
        min_northing,
        min_easting + metres,
        min_northing + metres,
    )


def coarsen(ref: str, target_metres: int) -> str | None:
    """Generalise a reference to `target_metres`, or None if impossible.

    Fail-closed by design:

    * an unparseable reference returns None (the caller must drop or escalate);
    * a target finer than the reference's own precision returns None - we never
      invent precision the record does not have;
    * a target that is not a recognised resolution returns None.

    A reference already at or coarser than the target is returned normalised and
    unchanged, which is the correct answer rather than an error.

    TETRADS
    -------
    A tetrad ("ST57A") is a 2 km square identified by a 10 km reference plus a
    letter. Its axis split is NOT positional, so it cannot go through `split()`.
    But it is exactly contained in its own 10 km square, so coarsening it to
    10 km or 100 km is arithmetically trivial and strictly safe - drop the
    letter. This is handled explicitly here rather than by teaching `split()`
    about tetrads, because a tetrad reaching the truncation path below would
    yield "ST57" labelled as 1 km when it is really 10 km: a fabricated
    precision, and the exact class of error this module exists to prevent.

    An earlier version returned None for every tetrad, so a tetrad record was
    withheld as "cannot-generalise" even when a perfectly safe 10 km square was
    available. That is silent data loss - the failure `sensitivity.py` exists to
    avoid - and it matters because tetrads are standard in UK botanical
    recording, which is 54 of the 65 taxa on BRERC's sensitive list.
    """
    current = precision_metres(ref)
    if current is None:
        return None
    if target_metres not in _METRES_TO_PAIRS and target_metres != HECTAD_LETTERS_METRES:
        return None
    if target_metres < current:
        return None  # never upsample
    if current >= target_metres:
        return normalise(ref)

    cleaned = normalise(ref)

    tetrad = _TETRAD_RE.match(cleaned)
    if tetrad:
        letters, digits = tetrad.group(1), tetrad.group(2)
        if target_metres == HECTAD_LETTERS_METRES:
            return letters
        if target_metres == 10000:
            return f"{letters}{digits}"
        # Unreachable: any finer target was rejected by `target_metres < current`
        # above. Explicit rather than implicit, so a future edit to the guards
        # cannot silently open a path that fabricates precision.
        return None

    parts = split(cleaned)
    if parts is None:
        return None
    letters, easting, northing = parts

    if target_metres == HECTAD_LETTERS_METRES:
        return letters

    keep = _METRES_TO_PAIRS[target_metres]
    # Truncate EACH AXIS independently. This is the whole point of the module.
    return f"{letters}{easting[:keep]}{northing[:keep]}"


def is_public_resolution(metres: int | None) -> bool:
    """True if a resolution may be emitted on the public tier."""
    return metres in PUBLIC_RESOLUTIONS_METRES

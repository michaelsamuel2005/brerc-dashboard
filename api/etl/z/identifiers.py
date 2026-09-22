"""Canonical handling for BRERC's private ``unique_no numeric(13,2)`` key.

The identifier is needed internally for deterministic upserts, but it is never
published directly. PostgreSQL considers ``123``, ``123.0`` and ``123.00`` the
same numeric value; canonicalising them before duplicate checks prevents one
logical source record from being inserted under several textual spellings.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, localcontext

NUMERIC_13_2_QUANTUM = Decimal("0.01")
NUMERIC_13_2_MAX = Decimal("99999999999.99")


class InvalidSourceIdentifier(ValueError):
    """A source identifier cannot be represented safely as numeric(13,2)."""


class DuplicateSourceIdentifier(ValueError):
    """Two source values collapse to the same canonical private identifier."""


def canonical_unique_no(raw: object) -> str:
    """Return the exact two-decimal representation accepted by numeric(13,2).

    Error messages deliberately do not echo the raw identifier; it is private
    source data and should not be copied into logs or CI output.
    """
    if raw is None or isinstance(raw, bool | float):
        raise InvalidSourceIdentifier("unique_no is missing or is not numeric")
    text = str(raw).strip()
    if not text:
        raise InvalidSourceIdentifier("unique_no is blank")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise InvalidSourceIdentifier("unique_no is not a valid decimal") from None
    if not value.is_finite():
        raise InvalidSourceIdentifier("unique_no must be finite")
    if abs(value) > NUMERIC_13_2_MAX:
        raise InvalidSourceIdentifier("unique_no exceeds numeric(13,2)")

    try:
        with localcontext() as context:
            context.prec = 32
            canonical = value.quantize(NUMERIC_13_2_QUANTUM)
    except InvalidOperation:
        raise InvalidSourceIdentifier("unique_no cannot be represented as numeric(13,2)") from None
    if canonical != value:
        raise InvalidSourceIdentifier("unique_no has more than two significant decimal places")
    if canonical == 0:
        canonical = abs(canonical)  # normalise Decimal("-0.00") to "0.00"
    return format(canonical, ".2f")


def assert_unique_source_ids(values: Iterable[object]) -> tuple[str, ...]:
    """Canonicalise values and fail without logging the duplicated identifier."""
    canonical: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = canonical_unique_no(value)
        if item in seen:
            raise DuplicateSourceIdentifier(
                "duplicate unique_no after numeric(13,2) canonicalisation"
            )
        seen.add(item)
        canonical.append(item)
    return tuple(canonical)

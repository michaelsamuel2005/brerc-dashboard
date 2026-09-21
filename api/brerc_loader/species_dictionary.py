"""Strict parsing for the digest-bound BRERC species dictionary artifact."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from etl.species import SpeciesDictionary

from .config import MAX_SPECIES_DICTIONARY_BYTES
from .errors import LoaderPolicyInvalid

MAX_SPECIES_DICTIONARY_ROWS = 1_000_000
REQUIRED_SPECIES_DICTIONARY_HEADERS = (
    "SPECIES_NO",
    "SCIENTIFIC",
    "COMMON_NAM",
    "SENSITIVE",
)


def _invalid() -> LoaderPolicyInvalid:
    """Return a content-free error safe for the ordinary operator log."""
    return LoaderPolicyInvalid()


def parse_species_dictionary_artifact(artifact: bytes) -> SpeciesDictionary:
    """Parse one already-snapshotted CSV into its semantic safety dictionary.

    The raw-byte digest is checked by :class:`SpeciesDictionaryConfig`. This
    parser supplies the separate semantic binding used by publication policy.
    Extra client columns are accepted, but the four safety/identity columns,
    unambiguous row shape, bounded row count and at least one usable taxon are
    mandatory.
    """
    if not isinstance(artifact, bytes) or not 1 <= len(artifact) <= MAX_SPECIES_DICTIONARY_BYTES:
        raise _invalid()
    try:
        text = artifact.decode("utf-8-sig")
    except UnicodeError:
        raise _invalid() from None
    if "\x00" in text:
        raise _invalid()

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        header = reader.fieldnames
        if (
            not isinstance(header, list)
            or not header
            or any(not isinstance(name, str) or not name or name != name.strip() for name in header)
            or len(header) != len(set(header))
            or not set(REQUIRED_SPECIES_DICTIONARY_HEADERS).issubset(header)
        ):
            raise _invalid()

        expected_header = tuple(header)

        def rows() -> Iterator[dict[str, object]]:
            for count, row in enumerate(reader, start=1):
                if count > MAX_SPECIES_DICTIONARY_ROWS:
                    raise _invalid()
                if (
                    not isinstance(row, dict)
                    or None in row
                    or tuple(row) != expected_header
                    or any(value is None for value in row.values())
                ):
                    raise _invalid()
                yield {name: row[name] for name in expected_header}

        dictionary = SpeciesDictionary.from_rows(rows())
    except LoaderPolicyInvalid:
        raise
    except (csv.Error, UnicodeError, TypeError, ValueError, OverflowError):
        raise _invalid() from None
    if len(dictionary) == 0:
        raise _invalid()
    return dictionary


__all__ = [
    "MAX_SPECIES_DICTIONARY_ROWS",
    "REQUIRED_SPECIES_DICTIONARY_HEADERS",
    "parse_species_dictionary_artifact",
]

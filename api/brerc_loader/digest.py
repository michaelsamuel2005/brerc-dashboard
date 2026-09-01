"""Deterministic, bounded-memory digests for stored release rows.

The digest is deliberately schema-bound.  A caller cannot omit a table, repeat
one, change its columns, or finish early and still obtain a release digest.
Rows must be supplied by the fixed, ordered SQL plans in the PostgreSQL loader.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from .errors import LoaderCandidateInvalid

DIGEST_PROFILE = "brerc-publication-database-sha256-v3"


@dataclass(frozen=True)
class DigestTable:
    """One exact result set in a versioned digest profile."""

    name: str
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name
            or not isinstance(self.columns, tuple)
            or not self.columns
            or any(not isinstance(column, str) or not column for column in self.columns)
            or len(self.columns) != len(set(self.columns))
        ):
            raise LoaderCandidateInvalid()


# Release/job UUIDs and timestamps are intentionally absent. Re-running the
# same source snapshot under the same approved policy must produce the same
# digest even though it receives a new candidate UUID.
PUBLIC_RELEASE_DIGEST_TABLES = (
    DigestTable(
        "public_release",
        (
            "publication_policy_version",
            "dataset_version",
            "sensitive_record_action",
            "suppression_mode",
            "min_records_per_cell",
            "verification_available",
            "individual_records_available",
            "record_verification_available",
            "place_available",
            "abundance_available",
            "record_type_available",
            "public_source_label",
        ),
    ),
    DigestTable(
        "public_species",
        (
            "species_id",
            "scientific_name",
            "common_name",
            "taxon_group",
            "total_records",
            "first_year",
            "last_year",
        ),
    ),
    DigestTable(
        "public_distribution_cell",
        (
            "species_id",
            "record_year",
            "cell_id",
            "precision_metres",
            "record_count",
            "verified_count",
            "min_easting",
            "min_northing",
            "max_easting",
            "max_northing",
        ),
    ),
    DigestTable(
        "public_species_year",
        ("species_id", "record_year", "record_count", "verified_count"),
    ),
    DigestTable(
        "public_record",
        (
            "public_record_id",
            "species_id",
            "scientific_name",
            "common_name",
            "grid_ref",
            "precision_metres",
            "place",
            "record_year",
            "abundance",
            "record_type",
            "verified_status",
            "source_label",
        ),
    ),
)

SOURCE_RESULT_DIGEST_TABLES = (
    DigestTable(
        "source_disposition",
        (
            "source_key_token",
            "input_fingerprint",
            "disposition",
            "withheld_reason",
            "species_id",
            "scientific_name",
            "common_name",
            "record_grid_ref",
            "record_precision_metres",
            "cell_id",
            "cell_precision_metres",
            "min_easting",
            "min_northing",
            "max_easting",
            "max_northing",
            "record_year",
            "public_record_id",
            "place",
            "abundance",
            "record_type",
            "verified_status",
            "source_label",
        ),
    ),
    DigestTable("withheld_summary", ("reason_code", "row_count")),
)


def _canonical(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, time):
        return {"time": value.isoformat(timespec="microseconds")}
    if isinstance(value, bytes):
        return {"bytesHex": value.hex()}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    raise LoaderCandidateInvalid()


class ReleaseDigest:
    """Hash every table in one exact profile, once and in profile order."""

    def __init__(self, tables: Sequence[DigestTable]) -> None:
        if (
            not isinstance(tables, Sequence)
            or isinstance(tables, str | bytes)
            or not tables
            or any(not isinstance(table, DigestTable) for table in tables)
        ):
            raise LoaderCandidateInvalid()
        frozen = tuple(tables)
        if len({table.name for table in frozen}) != len(frozen):
            raise LoaderCandidateInvalid()
        self._tables = frozen
        self._digest = hashlib.sha256()
        profile_document = json.dumps(
            {
                "profile": DIGEST_PROFILE,
                "tables": [
                    {"table": table.name, "columns": list(table.columns)} for table in frozen
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        self._digest.update((profile_document + "\n").encode("ascii"))
        self._next_table = 0
        self._open_table: DigestTable | None = None
        self._row_count = 0

    def begin(self, table: str, columns: Sequence[str]) -> None:
        if self._open_table is not None or self._next_table >= len(self._tables):
            raise LoaderCandidateInvalid()
        expected = self._tables[self._next_table]
        if table != expected.name or tuple(columns) != expected.columns:
            raise LoaderCandidateInvalid()
        self._open_table = expected
        self._row_count = 0
        self._digest.update(f"begin={expected.name}\n".encode("ascii"))

    def rows(self, rows: Iterable[Sequence[object]]) -> None:
        if self._open_table is None:
            raise LoaderCandidateInvalid()
        width = len(self._open_table.columns)
        for row in rows:
            if not isinstance(row, Sequence) or isinstance(row, str | bytes) or len(row) != width:
                raise LoaderCandidateInvalid()
            document = json.dumps(
                [_canonical(value) for value in row],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            self._digest.update((document + "\n").encode("utf-8"))
            self._row_count += 1

    def end(self) -> int:
        if self._open_table is None:
            raise LoaderCandidateInvalid()
        count = self._row_count
        self._digest.update(f"rows={count}\n".encode("ascii"))
        self._open_table = None
        self._row_count = 0
        self._next_table += 1
        return count

    def hexdigest(self) -> str:
        if self._open_table is not None or self._next_table != len(self._tables):
            raise LoaderCandidateInvalid()
        return self._digest.hexdigest()

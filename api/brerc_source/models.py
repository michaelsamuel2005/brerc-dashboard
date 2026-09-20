"""Driver protocols and safe structural reports for the source connector."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class CursorDescription(Protocol):
    """The part of a DB-API description item the connector consumes."""

    name: str


class PostgreSQLCursor(Protocol):
    """Small driver-independent cursor surface used by the connector."""

    description: Sequence[CursorDescription | Sequence[object]] | None

    def execute(
        self,
        query: object,
        params: Sequence[object] | None = None,
    ) -> PostgreSQLCursor: ...

    def fetchone(self) -> object: ...

    def fetchmany(self, size: int = 0) -> Sequence[object]: ...

    def close(self) -> None: ...


class PostgreSQLConnection(Protocol):
    """Small driver-independent connection surface used by the connector."""

    def cursor(self, name: str | None = None, **kwargs: object) -> PostgreSQLCursor: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...

    def cancel_safe(self, *, timeout: float = 30.0) -> None: ...


class CancellationToken(Protocol):
    """Cooperative cancellation checked before and between database operations."""

    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True)
class SourcePreflightReport:
    """Safe structural evidence from one closed read-only snapshot.

    The report intentionally excludes the view SQL, catalogue rows, database and
    role names, host details, credentials and source data. ``release_ready`` is
    the contract's readiness state; it is not permission to publish.
    """

    contract_version: str
    contract_sha256: str
    observed_definition_sha256: str
    observed_identity_sha256: str
    confirmed_columns: int
    result_columns: tuple[str, ...]
    release_ready: bool


@dataclass(frozen=True)
class SafeSourceSnapshotEvidence:
    """Non-reversible evidence for one completely consumed source snapshot."""

    captured_at_utc: str
    contract_version: str
    contract_sha256: str
    policy_version: str
    policy_approval_digest: str
    sensitive_record_action: str
    observed_species_dictionary_sha256: str
    observed_definition_sha256: str
    observed_identity_sha256: str
    result_columns: tuple[str, ...]
    rows_seen: int
    records_eligible_before_suppression: int
    withheld_by_reason: tuple[tuple[str, int], ...]
    sensitivity_buckets: tuple[tuple[str, int], ...]


def cursor_column_names(description: object) -> tuple[str, ...]:
    """Return a DB-API cursor header without accepting an ambiguous item."""
    if not isinstance(description, Sequence) or isinstance(description, str | bytes):
        raise ValueError("cursor description is not a sequence")
    names: list[str] = []
    for item in description:
        name = getattr(item, "name", None)
        if name is None and isinstance(item, Sequence) and not isinstance(item, str | bytes):
            name = item[0] if item else None
        if not isinstance(name, str) or not name:
            raise ValueError("cursor description has an invalid column")
        names.append(name)
    return tuple(names)


def mapping_row(row: object, header: Sequence[str]) -> dict[str, object]:
    """Copy one adapter row into a plain mapping without leaking it elsewhere."""
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    if not isinstance(row, Sequence) or isinstance(row, str | bytes) or len(row) != len(header):
        raise ValueError("database row shape differs from its cursor header")
    return dict(zip(header, row, strict=True))

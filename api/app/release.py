"""Select the one active release and expose its publication capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from fastapi import HTTPException

from app.db import assert_serving_relation


@dataclass(frozen=True)
class ActiveRelease:
    release_id: str
    published_at: str | None
    source_data_as_of: str | None
    publication_policy_version: str | None
    dataset_version: str | None
    source_label: str | None
    verification_available: bool
    individual_records_available: bool
    record_verification_available: bool
    place_available: bool
    abundance_available: bool
    record_type_available: bool
    sensitive_record_action: Literal["generalise", "withhold"]

    @property
    def mode(self) -> str:
        return "individual-records" if self.individual_records_available else "aggregates-only"


_RELEASE_SQL = f"""
SELECT release_id, published_at, source_data_as_of, publication_policy_version,
       dataset_version, public_source_label, verification_available,
       individual_records_available, record_verification_available,
       place_available, abundance_available, record_type_available,
       sensitive_record_action
FROM {assert_serving_relation("serve.public_release")}
"""  # noqa: S608 - the relation is an allow-listed constant


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _as_database_bool(value: object) -> bool:
    if type(value) is not bool:
        raise HTTPException(status_code=503, detail="Publication capability state is invalid")
    return value


def _as_sensitive_record_action(value: object) -> Literal["generalise", "withhold"]:
    if value not in {"generalise", "withhold"}:
        raise HTTPException(status_code=503, detail="Sensitive-record publication state is invalid")
    return cast(Literal["generalise", "withhold"], value)


def load_active_release(connection) -> ActiveRelease:
    """Return exactly one active release, otherwise fail as unavailable."""
    with connection.cursor() as cursor:
        cursor.execute(_RELEASE_SQL)
        rows = cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=503, detail="No active publication release")
    if len(rows) != 1:
        raise HTTPException(status_code=503, detail="Publication release state is ambiguous")
    row = rows[0]
    release_id = _as_text(row["release_id"])
    if not release_id:
        raise HTTPException(status_code=503, detail="Publication release identity is invalid")
    return ActiveRelease(
        release_id=release_id,
        published_at=_as_text(row["published_at"]),
        source_data_as_of=_as_text(row["source_data_as_of"]),
        publication_policy_version=_as_text(row["publication_policy_version"]),
        dataset_version=_as_text(row["dataset_version"]),
        source_label=_as_text(row["public_source_label"]),
        verification_available=_as_database_bool(row["verification_available"]),
        individual_records_available=_as_database_bool(row["individual_records_available"]),
        record_verification_available=_as_database_bool(row["record_verification_available"]),
        place_available=_as_database_bool(row["place_available"]),
        abundance_available=_as_database_bool(row["abundance_available"]),
        record_type_available=_as_database_bool(row["record_type_available"]),
        sensitive_record_action=_as_sensitive_record_action(row["sensitive_record_action"]),
    )

"""The active release and its publication capabilities.

Every endpoint needs the same two things: is there an active release at all, and
what did it authorise for publication?  Reading it once, here, means no router
invents a default.  ``serve.public_release`` returns exactly one row when a
release is active and none otherwise, so "no release yet" is a distinguishable
state rather than an empty dashboard that looks like a data problem.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def mode(self) -> str:
        return "individual-records" if self.individual_records_available else "aggregates-only"


_RELEASE_SQL = f"""
SELECT release_id, published_at, source_data_as_of, publication_policy_version,
       dataset_version, public_source_label, verification_available,
       individual_records_available, record_verification_available,
       place_available, abundance_available, record_type_available
FROM {assert_serving_relation("serve.public_release")}
"""  # noqa: S608 - relation name is a checked constant, not caller input


def load_active_release(connection) -> ActiveRelease:
    """Return the active release, or refuse the request if there is not one."""
    with connection.cursor() as cursor:
        cursor.execute(_RELEASE_SQL)
        rows = cursor.fetchall()
    if not rows:
        # 503, not 404: the endpoint exists and will work once a release is
        # activated.  A 404 would tell a caller the resource does not exist.
        raise HTTPException(status_code=503, detail="No active publication release")
    if len(rows) > 1:
        raise HTTPException(status_code=503, detail="Publication release state is ambiguous")
    row = rows[0]

    def as_text(value: object) -> str | None:
        """Dates and timestamps as ISO-8601, never ``str()``.

        ``str()`` on a timestamp yields "2026-08-14 12:00:00+00:00" — a space
        where ISO-8601 requires a "T".  The front end's schema accepts any
        string, so this would pass validation and then be handed to
        ``new Date()``, whose parsing of a non-ISO string is
        implementation-defined.  It works in V8 and is not guaranteed anywhere.
        """
        if value is None:
            return None
        isoformat = getattr(value, "isoformat", None)
        return isoformat() if callable(isoformat) else str(value)

    return ActiveRelease(
        release_id=str(row["release_id"]),
        published_at=as_text(row["published_at"]),
        source_data_as_of=as_text(row["source_data_as_of"]),
        publication_policy_version=as_text(row["publication_policy_version"]),
        dataset_version=as_text(row["dataset_version"]),
        source_label=as_text(row["public_source_label"]),
        verification_available=bool(row["verification_available"]),
        individual_records_available=bool(row["individual_records_available"]),
        record_verification_available=bool(row["record_verification_available"]),
        place_available=bool(row["place_available"]),
        abundance_available=bool(row["abundance_available"]),
        record_type_available=bool(row["record_type_available"]),
    )

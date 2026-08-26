"""GET /api/records — scoped, paginated rows from the active release.

An unscoped request returns an empty page: this is a lookup endpoint, not a
bulk-download path. Aggregate-only releases are independently forced empty even
if an incorrectly configured view were ever to return a row.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import PublicationFields, RecordPage, RecordPublication, RecordRow
from app.release import ActiveRelease, load_active_release

router = APIRouter(prefix="/api", tags=["records"])

_RECORDS = assert_serving_relation("serve.public_record")

_ROWS_SQL = f"""
SELECT public_record_id, scientific_name, common_name, grid_ref,
       precision_metres, place, record_year, abundance, record_type,
       verified_status, source_label
FROM {_RECORDS}
WHERE species_id = %s
  AND (%s::integer IS NULL OR record_year = %s)
ORDER BY record_year DESC, public_record_id
LIMIT %s OFFSET %s
"""  # noqa: S608 - checked relation; every request value is bound

_COUNT_SQL = f"""
SELECT COUNT(*) AS total
FROM {_RECORDS}
WHERE species_id = %s
  AND (%s::integer IS NULL OR record_year = %s)
"""  # noqa: S608 - checked relation; every request value is bound


def _publication(release: ActiveRelease) -> RecordPublication:
    return RecordPublication(
        mode=release.mode,
        fields=PublicationFields(
            abundance=release.abundance_available,
            place=release.place_available,
            recordType=release.record_type_available,
            verification=release.record_verification_available,
        ),
    )


def _row(record: dict, release: ActiveRelease) -> RecordRow:
    fields: dict[str, object] = {
        "id": str(record["public_record_id"]),
        "scientificName": record["scientific_name"],
        "commonName": record["common_name"],
        "gridRef": record["grid_ref"],
        "precisionMetres": int(record["precision_metres"]),
        "place": record["place"],
        "year": int(record["record_year"]),
        "source": record["source_label"],
    }
    if release.abundance_available:
        fields["abundance"] = record["abundance"]
    if release.record_type_available:
        fields["recordType"] = record["record_type"]
    if release.record_verification_available:
        fields["verified"] = record["verified_status"]
    return RecordRow(**fields)


@router.get("/records", response_model=RecordPage, response_model_exclude_unset=True)
def list_records(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=config.MAX_PAGE_SIZE),
    species: str | None = Query(None, max_length=120),
    year: int | None = Query(None, ge=1500, le=2200),
) -> RecordPage:
    page_size = min(pageSize, config.MAX_PAGE_SIZE)
    publication: RecordPublication
    with serving_connection() as connection:
        release = load_active_release(connection)
        publication = _publication(release)
        if species is None or not release.individual_records_available:
            return RecordPage(
                publication=publication,
                items=[],
                page=page,
                pageSize=page_size,
                total=0,
            )

        parameters: list[object] = [species, year, year]
        with connection.cursor() as cursor:
            cursor.execute(
                _ROWS_SQL,
                [*parameters, page_size, (page - 1) * page_size],
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_SQL, parameters)
            total = int(cursor.fetchone()["total"])

    return RecordPage(
        publication=publication,
        items=[_row(row, release) for row in rows],
        page=page,
        pageSize=page_size,
        total=total,
    )

"""GET /api/records — one page of published records, newest first.

Two properties are structural rather than conventional:

* When the release does not publish individual records, ``serve.public_record``
  returns no rows at all — the capability is part of its join, not a filter this
  code applies.  The endpoint then reports ``aggregates-only`` with an empty
  page, which is what the front end's schema requires.
* ``abundance``, ``recordType`` and ``verified`` are omitted from a row unless
  the release publishes them.  The view already nulls them, so this is the
  second of two independent gates rather than the only one.

Ordering is reverse-chronological with a stable tie-break, and never "top" or
"most interesting": a ranked list would quietly point attention at particular
species and places.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import PublicationFields, RecordPage, RecordPublication, RecordRow
from app.release import ActiveRelease, load_active_release

router = APIRouter(prefix="/api", tags=["records"])

_RECORD_RELATION = assert_serving_relation("serve.public_record")

_ROWS_SQL = f"""
SELECT public_record_id, species_id, scientific_name, common_name, grid_ref,
       precision_metres, place, record_year, abundance, record_type,
       verified_status, source_label
FROM {_RECORD_RELATION}
{{where}}
ORDER BY record_year DESC, public_record_id
LIMIT %s OFFSET %s
"""  # noqa: S608 - relation is a checked constant; the filter is a fixed clause

_COUNT_SQL = f"SELECT COUNT(*) AS total FROM {_RECORD_RELATION} {{where}}"  # noqa: S608


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
    """Build a row, omitting every field this release does not publish."""
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
    speciesId: str | None = Query(None),
) -> RecordPage:
    # The query cap is re-applied here so the bound survives any future
    # loosening of the request validation above.
    page_size = min(pageSize, config.MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    where = ""
    filter_params: list[object] = []
    if speciesId is not None:
        where = "WHERE species_id = %s"
        filter_params.append(speciesId)

    with serving_connection() as connection:
        release = load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(_ROWS_SQL.format(where=where), [*filter_params, page_size, offset])
            rows = cursor.fetchall()
            cursor.execute(_COUNT_SQL.format(where=where), filter_params)
            total = int(cursor.fetchone()["total"])

    return RecordPage(
        publication=_publication(release),
        items=[_row(row, release) for row in rows],
        page=page,
        pageSize=page_size,
        total=total,
    )

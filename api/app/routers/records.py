"""
GET /api/records — paginated records — NOW READS REAL DATA (B8) from public_records.

Reads ONLY from the public_records view, so recorder names, precise coordinates,
and free-text are impossible to reach from here by construction. gridRef precision
matches precisionMetres; place is a COARSE locality only (never a precise site).

FOR THE MAINTAINER — two things about this endpoint are deliberate:

  * Newest first, always. There is no "most interesting" or "top 10" ordering,
    and there should never be one. A ranked list invites the question "ranked by
    what?", and any honest answer (most sightings, rarest, most recently seen)
    quietly points attention at particular species and places. A plain reverse-
    chronological list makes no such suggestion.

  * You get one page at a time, and the page size is capped on the server. Ask
    for 10,000 records and you will get MAX_PAGE_SIZE of them (app/config.py).
    Paging through is possible but slow and obvious — which is the intent. This
    is a lookup tool, not a download.
"""

from fastapi import APIRouter, Query

from app import config
from app.db import get_connection
from app.models import RecordList, RecordItem

router = APIRouter(prefix="/api", tags=["records"])


@router.get("/records", response_model=RecordList)
def list_records(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=config.MAX_PAGE_SIZE),
    speciesId: int | None = Query(None),
) -> RecordList:
    # Belt-and-braces: Query(le=...) already refuses a bigger page, but this
    # guarantees the cap even if that validation is ever loosened by mistake.
    pageSize = min(pageSize, config.MAX_PAGE_SIZE)
    offset = (page - 1) * pageSize

    # Optional "filter by species" — the WHERE text is a fixed constant (safe),
    # and the value is passed as a parameter (%s), never glued into the string.
    where_sql = ""
    filter_params: list = []
    if speciesId is not None:
        where_sql = "WHERE species_id = %s"
        filter_params.append(speciesId)

    # Ordered by date, newest first. "Date" here means the YEAR: the public data
    # holds no finer date than that, on purpose — an exact date plus a grid
    # square can identify a single visit, and often a single recorder.
    # record_id is the tie-breaker, so records within the same year keep a
    # stable order and paging never repeats or skips a row.
    rows_sql = f"""
        SELECT record_id, scientific_name, common_name, record_year,
               grid_ref, precision_metres, place, verified
        FROM public_records
        {where_sql}
        ORDER BY record_year DESC, record_id
        LIMIT %s OFFSET %s;
    """
    count_sql = f"SELECT COUNT(*) AS total FROM public_records {where_sql};"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(rows_sql, filter_params + [pageSize, offset])
            rows = cur.fetchall()

            cur.execute(count_sql, filter_params)
            total = cur.fetchone()["total"]

    items = [
        RecordItem(
            recordId=row["record_id"],
            scientificName=row["scientific_name"],
            commonName=row["common_name"],
            year=row["record_year"],
            gridRef=row["grid_ref"],
            precisionMetres=row["precision_metres"],
            place=row["place"],
            verified=row["verified"],
        )
        for row in rows
    ]

    return RecordList(items=items, total=total, page=page, pageSize=pageSize)

"""
GET /api/records — paginated records — NOW READS REAL DATA (B8) from public_records.

Reads ONLY from the public_records view, so recorder names, precise coordinates,
and free-text are impossible to reach from here by construction. gridRef precision
matches precisionMetres; place is a COARSE locality only (never a precise site).
"""

from fastapi import APIRouter, Query

from app.db import get_connection
from app.models import RecordList, RecordItem

router = APIRouter(prefix="/api", tags=["records"])


@router.get("/records", response_model=RecordList)
def list_records(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    speciesId: int | None = Query(None),
) -> RecordList:
    offset = (page - 1) * pageSize

    # Optional "filter by species" — the WHERE text is a fixed constant (safe),
    # and the value is passed as a parameter (%s), never glued into the string.
    where_sql = ""
    filter_params: list = []
    if speciesId is not None:
        where_sql = "WHERE species_id = %s"
        filter_params.append(speciesId)

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

"""
GET /api/records — paginated records, generalised.

STUB: fake data in the contract shape. Swap for real query in B8.
gridRef precision matches precisionMetres; place is a COARSE locality only
(never a precise site); Recorder1/Eastings/Northings/Comments are never here.
"""

from fastapi import APIRouter, Query

from app.models import RecordList, RecordItem

router = APIRouter(prefix="/api", tags=["records"])


@router.get("/records", response_model=RecordList)
def list_records(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    speciesId: int | None = Query(None),
) -> RecordList:
    fake = [
        RecordItem(
            recordId=100001,
            scientificName="Erithacus rubecula",
            commonName="Robin",
            year=2024,
            gridRef="ST5872",
            precisionMetres=1000,
            place="Bristol",
            verified=True,
        ),
        RecordItem(
            recordId=100002,
            scientificName="Bufo bufo",
            commonName="Common Toad",
            year=2023,
            gridRef="ST61",
            precisionMetres=10000,
            place="South Gloucestershire",
            verified=True,
        ),
    ]
    return RecordList(items=fake, total=len(fake), page=page, pageSize=pageSize)

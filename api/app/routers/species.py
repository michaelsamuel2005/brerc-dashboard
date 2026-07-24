"""
GET /api/species          — paginated species list — NOW READS REAL DATA (B0 proof).
GET /api/species/{id}     — one species' detail — still a stub for now.

This is the "one real endpoint" for the mid-review demo: it queries the
`public_occurrences` view in the UI database and shapes the result into the same
contract models the stubs used. The response SHAPE is unchanged, so the front end
needs no modification — that was the whole point of building stubs first.

The remaining endpoints stay stubbed until B8.
"""

from fastapi import APIRouter, HTTPException, Query

from app.db import get_connection
from app.models import (
    SpeciesList,
    SpeciesListItem,
    SpeciesDetail,
    SpeciesImage,
)

router = APIRouter(prefix="/api", tags=["species"])


@router.get("/species", response_model=SpeciesList)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
) -> SpeciesList:
    """
    Build one row per species by grouping the occurrence records.

    Reads ONLY from public_occurrences (the safe view), so recorder names and
    precise coordinates are impossible to reach from here by construction.
    """
    offset = (page - 1) * pageSize

    # One row per distinct species, with its record count and year span.
    # NOTE: %s placeholders are parameterised — values are passed separately,
    # never glued into the string (that is how SQL injection happens).
    sql = """
        SELECT
            scientific_name,
            MAX(common_name)   AS common_name,
            MAX(species_group) AS species_group,
            COUNT(*)           AS record_count,
            MIN(record_year)   AS first_year,
            MAX(record_year)   AS last_year
        FROM public_occurrences
        GROUP BY scientific_name
        ORDER BY record_count DESC, scientific_name
        LIMIT %s OFFSET %s;
    """

    count_sql = "SELECT COUNT(DISTINCT scientific_name) AS total FROM public_occurrences;"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (pageSize, offset))
            rows = cur.fetchall()

            cur.execute(count_sql)
            total = cur.fetchone()["total"]

    # Shape the database rows into the agreed contract models.
    #
    # speciesId: the contract expects an integer id. The sample data has no
    # species id column yet (that arrives with the real taxonomy table in B6),
    # so we derive a stable positional id here. THIS IS A KNOWN PLACEHOLDER —
    # replace it with the real SPECIES_NO once the taxonomy table exists.
    items = [
        SpeciesListItem(
            speciesId=offset + index + 1,
            scientificName=row["scientific_name"],
            commonName=row["common_name"],
            group=row["species_group"],
            recordCount=row["record_count"],
            firstYear=row["first_year"],
            lastYear=row["last_year"],
            hasImage=False,  # image sourcing is B8; fail closed for now
        )
        for index, row in enumerate(rows)
    ]

    return SpeciesList(items=items, total=total, page=page, pageSize=pageSize)


@router.get("/species/{species_id}", response_model=SpeciesDetail)
def species_detail(species_id: int) -> SpeciesDetail:
    """STILL A STUB — wired to real data in B8, once species ids exist."""
    if species_id != 1:
        raise HTTPException(status_code=404, detail="Species not found")

    return SpeciesDetail(
        speciesId=1,
        scientificName="Erithacus rubecula",
        commonName="Robin",
        group="birds",
        recordCount=3,
        firstYear=2022,
        lastYear=2024,
        image=SpeciesImage(
            url="https://example.org/placeholder.jpg",
            licence="CC BY 4.0",
            attribution="Placeholder — real licensed image sourced in B8",
        ),
        description="Placeholder description — real text cached in B8.",
    )

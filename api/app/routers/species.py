"""
GET /api/species          — paginated species list (real data from public_species).
GET /api/species/{id}     — one species' detail (real data from public_species).

Both read ONLY from the public_species view (safe by construction). speciesId is
the real SPECIES_NO, so a list item's speciesId works directly with /species/{id}
(list and detail stay consistent).

Species image + description come from a cached species-info proxy
(iNaturalist -> GBIF -> Wikipedia) — a later B8 sub-task. Until a licensed image
+ attribution is confirmed, they fail closed to None (no broken/unlicensed image).
"""

from fastapi import APIRouter, HTTPException, Query

from app.db import get_connection
from app.models import SpeciesList, SpeciesListItem, SpeciesDetail

router = APIRouter(prefix="/api", tags=["species"])


@router.get("/species", response_model=SpeciesList)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
) -> SpeciesList:
    offset = (page - 1) * pageSize

    rows_sql = """
        SELECT species_id, scientific_name, common_name, species_group,
               record_count, first_year, last_year, has_image
        FROM public_species
        ORDER BY record_count DESC, scientific_name
        LIMIT %s OFFSET %s;
    """
    count_sql = "SELECT COUNT(*) AS total FROM public_species;"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(rows_sql, (pageSize, offset))
            rows = cur.fetchall()

            cur.execute(count_sql)
            total = cur.fetchone()["total"]

    items = [
        SpeciesListItem(
            speciesId=row["species_id"],
            scientificName=row["scientific_name"],
            commonName=row["common_name"],
            group=row["species_group"],
            recordCount=row["record_count"],
            firstYear=row["first_year"],
            lastYear=row["last_year"],
            hasImage=row["has_image"],
        )
        for row in rows
    ]
    return SpeciesList(items=items, total=total, page=page, pageSize=pageSize)


@router.get("/species/{species_id}", response_model=SpeciesDetail)
def species_detail(species_id: int) -> SpeciesDetail:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT species_id, scientific_name, common_name, species_group,
                       record_count, first_year, last_year, has_image
                FROM public_species
                WHERE species_id = %s;
                """,
                (species_id,),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")

    return SpeciesDetail(
        speciesId=row["species_id"],
        scientificName=row["scientific_name"],
        commonName=row["common_name"],
        group=row["species_group"],
        recordCount=row["record_count"],
        firstYear=row["first_year"],
        lastYear=row["last_year"],
        image=None,        # fail closed — real licensed image is a later B8 sub-task
        description=None,   # cached description is a later B8 sub-task
    )

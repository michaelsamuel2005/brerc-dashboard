"""
GET /api/species          — paginated species list (real data from public_species).
GET /api/species/{id}     — one species' detail (real data from public_species).

The list can be sorted (sort_by) and filtered to one group (group). Both are
optional; leaving them out gives the old behaviour — most-recorded species first.
The page size is capped on the server, so no caller can pull the whole list at
once (see MAX_PAGE_SIZE in app/config.py).

Both read ONLY from the public_species view (safe by construction). speciesId is
the real SPECIES_NO, so a list item's speciesId works directly with /species/{id}
(list and detail stay consistent).

The image + description on the detail endpoint come from the cached species-info
proxy in app/species_info.py (iNaturalist -> GBIF -> Wikipedia). That module owns
the licence rules; this router just asks it for an answer and passes on whatever
it gets. When no reusable licence + attribution can be confirmed, both fields are
None — the front end should then show a named placeholder, never a broken image.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app import config, species_info
from app.db import get_connection
from app.models import SpeciesList, SpeciesListItem, SpeciesDetail

router = APIRouter(prefix="/api", tags=["species"])


# FOR THE MAINTAINER: this is a WHITELIST, and it is the only reason it is safe
# to put a sort column into the SQL text.
#
# The rule in this codebase is that nothing a caller types ever reaches the SQL
# string — values always travel as parameters (%s). A column name can't be a
# parameter, so instead the caller sends a LABEL ("commonName") and we look up
# the real column ourselves. Anything not in this dictionary never gets that
# far: FastAPI rejects it with a 422 before this function runs.
#
# To offer another sort option, add a line here AND to SortBy just below. Never
# build the ORDER BY from the caller's text.
_SORT_COLUMNS = {
    "commonName": "common_name",
    "scientificName": "scientific_name",
}

# The two values /api/species?sort_by=... will accept. FastAPI turns anything
# else into a 422 "Unprocessable Entity" automatically.
SortBy = Literal["commonName", "scientificName"]


@router.get("/species", response_model=SpeciesList)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=config.MAX_PAGE_SIZE),
    sort_by: SortBy | None = Query(
        None,
        description="Sort the list by 'commonName' or 'scientificName'. "
                    "Omit to sort by how many records each species has.",
    ),
    group: str | None = Query(
        None,
        description="Show only one species group, e.g. 'birds' or 'mammals'.",
    ),
) -> SpeciesList:
    # Belt-and-braces: Query(le=...) already refuses a bigger page, but this
    # guarantees the cap even if that validation is ever loosened by mistake.
    pageSize = min(pageSize, config.MAX_PAGE_SIZE)
    offset = (page - 1) * pageSize

    # Optional group filter. The WHERE text is a fixed string; the group name
    # the caller typed travels separately as a parameter, so it is data and can
    # never be executed as SQL.
    where_sql = ""
    filter_params: list = []
    if group is not None:
        where_sql = "WHERE species_group = %s"
        filter_params.append(group)

    # Chosen from the whitelist above — never from the caller's raw text.
    # Common names can be empty, so NULLS LAST keeps unnamed species at the
    # bottom instead of the top. scientific_name is the tie-breaker so the
    # order is stable and pagination doesn't repeat or skip rows.
    if sort_by is None:
        order_sql = "record_count DESC, scientific_name"
    else:
        order_sql = f"{_SORT_COLUMNS[sort_by]} ASC NULLS LAST, scientific_name"

    rows_sql = f"""
        SELECT species_id, scientific_name, common_name, species_group,
               record_count, first_year, last_year, has_image
        FROM public_species
        {where_sql}
        ORDER BY {order_sql}
        LIMIT %s OFFSET %s;
    """
    count_sql = f"SELECT COUNT(*) AS total FROM public_species {where_sql};"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(rows_sql, filter_params + [pageSize, offset])
            rows = cur.fetchall()

            cur.execute(count_sql, filter_params)
            total = cur.fetchone()["total"]

    # hasImage means "the detail endpoint can give you a picture". Two ways that
    # can be true: the database says so (a curated image), or the proxy already
    # has a licence-checked one cached. This is a CACHE-ONLY, batched lookup —
    # rendering one page of results must never trigger twenty outbound calls, so
    # a species the proxy hasn't fetched yet simply reports the database's value.
    cached_images = species_info.names_with_cached_image(
        [row["scientific_name"] for row in rows]
    )

    items = [
        SpeciesListItem(
            speciesId=row["species_id"],
            scientificName=row["scientific_name"],
            commonName=row["common_name"],
            group=row["species_group"],
            recordCount=row["record_count"],
            firstYear=row["first_year"],
            lastYear=row["last_year"],
            hasImage=row["has_image"] or row["scientific_name"] in cached_images,
        )
        for row in rows
    ]
    return SpeciesList(items=items, total=total, page=page, pageSize=pageSize)


@router.get("/species/{species_id}", response_model=SpeciesDetail)
def species_detail(species_id: str) -> SpeciesDetail:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT species_id, scientific_name, common_name, species_group,
                       record_count, first_year, last_year, has_image
                FROM public_species
                WHERE species_id = %s
                LIMIT 1;
                """,
                (species_id,),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")

    # Cached, licence-checked, and guaranteed not to raise: if the proxy is off or
    # the sources are unreachable, both fields come back None and this endpoint
    # still returns 200 with honest stats.
    info = species_info.get_species_info(row["scientific_name"])

    return SpeciesDetail(
        speciesId=row["species_id"],
        scientificName=row["scientific_name"],
        commonName=row["common_name"],
        group=row["species_group"],
        recordCount=row["record_count"],
        firstYear=row["first_year"],
        lastYear=row["last_year"],
        image=info.image,
        description=info.description,
    )

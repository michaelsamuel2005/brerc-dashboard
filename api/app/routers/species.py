"""
GET /api/species          — paginated species list (search/filter later).
GET /api/species/{id}     — one species' detail + optional licensed image.

STUB: fake data in the contract shape. Swap for real queries in B8.
Note species display convention: scientificName is the anchor; commonName may
be null. Images are fail-closed — image is null unless a licence is confirmed.
"""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    SpeciesList,
    SpeciesListItem,
    SpeciesDetail,
    SpeciesImage,
)

router = APIRouter(prefix="/api", tags=["species"])


# A tiny fake dataset so the front end has something to render.
_FAKE_SPECIES = [
    SpeciesListItem(
        speciesId=1,
        scientificName="Erithacus rubecula",
        commonName="Robin",
        group="birds",
        recordCount=13720,
        firstYear=1962,
        lastYear=2025,
        hasImage=True,
    ),
    SpeciesListItem(
        speciesId=2,
        scientificName="Bufo bufo",
        commonName="Common Toad",
        group="amphibians",
        recordCount=842,
        firstYear=1978,
        lastYear=2024,
        hasImage=True,
    ),
    SpeciesListItem(
        speciesId=3,
        scientificName="Lutra lutra",
        commonName="Otter",
        group="mammals",
        recordCount=311,
        firstYear=1990,
        lastYear=2025,
        hasImage=False,
    ),
]


@router.get("/species", response_model=SpeciesList)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
) -> SpeciesList:
    return SpeciesList(
        items=_FAKE_SPECIES,
        total=len(_FAKE_SPECIES),
        page=page,
        pageSize=pageSize,
    )


@router.get("/species/{species_id}", response_model=SpeciesDetail)
def species_detail(species_id: int) -> SpeciesDetail:
    match = next((s for s in _FAKE_SPECIES if s.speciesId == species_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Species not found")

    image = None
    if match.hasImage:
        image = SpeciesImage(
            url="https://example.org/placeholder.jpg",
            licence="CC BY 4.0",
            attribution="Placeholder — real image sourced iNat/GBIF/Wikipedia (B8)",
        )

    return SpeciesDetail(
        speciesId=match.speciesId,
        scientificName=match.scientificName,
        commonName=match.commonName,
        group=match.group,
        recordCount=match.recordCount,
        firstYear=match.firstYear,
        lastYear=match.lastYear,
        image=image,
        description="Placeholder description — real text cached in B8.",
    )

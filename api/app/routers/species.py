"""Species search + filter endpoints.  TODO (build this).

All reads must go through the `public_occurrences` gate, parameterised.
Learning Guide -> 04-the-api.md.
Answer Key: brerc-public-dashboard/api/app/routers/species.py
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/species", tags=["species"])


@router.get("/search")
async def search_species() -> dict:
    # TODO: ILIKE search over public_occurrences (parameterised, limited).
    raise HTTPException(status_code=501, detail="TODO: /species/search (Module 4)")


@router.get("/filters")
async def filter_options() -> dict:
    # TODO: distinct taxon groups, datasets, and the year range.
    raise HTTPException(status_code=501, detail="TODO: /species/filters (Module 4)")

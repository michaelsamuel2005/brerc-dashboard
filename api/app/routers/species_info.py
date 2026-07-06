"""Cached species image + description endpoint (licence fail-closed).  TODO.

Learning Guide -> 04-the-api.md (section 5).
Answer Key: brerc-public-dashboard/api/app/routers/species_info.py
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["species-info"])


@router.get("/species-info")
async def species_info() -> dict:
    # TODO: return an image ONLY with a confirmed reusable licence + attribution.
    raise HTTPException(status_code=501, detail="TODO: /species-info (Module 4)")

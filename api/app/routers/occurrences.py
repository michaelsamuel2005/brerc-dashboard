"""Aggregated occurrence endpoints — including the accessible table data.  TODO.

`/occurrences/cells` is the accessible table equivalent of the map: the SAME
generalised, counted cells the map draws, as JSON. Reads the gate; parameterised.
Learning Guide -> 04-the-api.md.
Answer Key: brerc-public-dashboard/api/app/routers/occurrences.py
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/occurrences", tags=["occurrences"])


@router.get("/summary")
async def summary() -> dict:
    # TODO: public-safe headline totals (NO recorder counts on the public tier).
    raise HTTPException(status_code=501, detail="TODO: /occurrences/summary (Module 4)")


@router.get("/cells")
async def cells() -> dict:
    # TODO: generalised, counted grid cells matching the filters (map-as-a-table).
    raise HTTPException(status_code=501, detail="TODO: /occurrences/cells (Module 4)")

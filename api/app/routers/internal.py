"""Internal data-quality endpoints (SECONDARY, access-controlled).  TODO.

Gated (HTTP Basic), off by default, localhost-only, NEVER behind the public proxy.
Learning Guide -> 07-internal-dashboard.md.
Answer Key: brerc-public-dashboard/api/app/routers/internal.py
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/summary")
async def summary() -> dict:
    # TODO: internal_summary; add auth gate + the other DQ endpoints.
    raise HTTPException(status_code=501, detail="TODO: /internal/* (Module 7)")

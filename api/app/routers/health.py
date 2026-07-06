"""Liveness / readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from .. import __version__
from ..db import Database, get_database

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response, db: Database = Depends(get_database)) -> dict:
    """Readiness check: 200 if the database is reachable, else 503."""
    try:
        ok = await db.fetchval("SELECT 1") == 1
    except Exception:  # noqa: BLE001 — health must never raise
        ok = False
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "database": ok, "version": __version__}

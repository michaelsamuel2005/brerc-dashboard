"""BRERC public dashboard — read-only publication API.

Only the active release's ``serve.*`` views are queried. The public service
does not import or call the legacy third-party species proxy; media remain
fallback-only until approved, licensed assets are supplied separately.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS, IS_PROD
from app.routers import distribution, health, provenance, records, species, summary

app = FastAPI(
    title="BRERC Public Dashboard API",
    version="0.1.0",
    description="Read-only API serving the active, generalised publication release.",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(provenance.router)
app.include_router(records.router)
app.include_router(distribution.router)
app.include_router(summary.router)
app.include_router(species.router)

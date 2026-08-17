"""BRERC public dashboard — read-only API.

Serves only what an activated publication release authorised, from the
``serve.*`` views.  The publication capabilities travel with the response so the
front end can tell "this release does not publish places" apart from "this
record has no place", which are different statements about the data.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import species_assets
from app.config import ALLOWED_ORIGINS, IS_PROD
from app.routers import distribution, health, provenance, records, species, summary

# Validate the approved species-assets file (if configured) at import time, so a
# malformed or still-unapproved file is a refused DEPLOY, not a per-request
# surprise.  Unset/absent is the ordinary state and loads the inactive registry.
species_assets.registry()

app = FastAPI(
    title="BRERC Public Dashboard API",
    version="0.1.0",
    description="Read-only API serving the active, generalised publication release.",
    # Interactive docs describe the query surface; they stay off in production.
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

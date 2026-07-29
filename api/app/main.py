"""
BRERC Public Dashboard — FastAPI (B0 scaffold).

This is the API skeleton for the public dashboard. Right now every endpoint
returns FAKE data in the exact shape of the agreed API contract (Michael's §10),
so the front end can integrate against it immediately. Later (B8), the fake data
is swapped for real queries against the public_occurrences view — the SHAPE stays
the same, so the front end needs no changes.

Run locally:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/docs to see and try every endpoint.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import IS_PROD, ALLOWED_ORIGINS
from app.routers import (
    health,
    summary,
    species,
    distribution,
    records,
    provenance,
)

# In production, hide the interactive docs and the OpenAPI schema (don't expose
# the API's internals publicly). In dev they stay on at /docs for convenience.
app = FastAPI(
    title="BRERC Public Dashboard API",
    version="0.1.0",
    description="Read-only API serving safe, generalised species-record data.",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
)

# CORS: which websites may call this API from a browser.
#   * dev:  local front-end dev servers (see app/config.py)
#   * prod: ONLY the origins listed in ALLOWED_ORIGINS (the council/BRERC site)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Register each group of endpoints.
app.include_router(health.router)
app.include_router(summary.router)
app.include_router(species.router)
app.include_router(distribution.router)
app.include_router(records.router)
app.include_router(provenance.router)

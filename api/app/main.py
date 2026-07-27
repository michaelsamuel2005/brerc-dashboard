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

from app.routers import (
    health,
    summary,
    species,
    distribution,
    records,
    provenance,
)

app = FastAPI(
    title="BRERC Public Dashboard API",
    version="0.1.0",
    description="Read-only API serving safe, generalised species-record data.",
)

# CORS: during development, allow the front-end dev server to call this API.
# In production this is tightened to the same origin (B8/B9).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # DEV ONLY — restrict in production (B9).
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

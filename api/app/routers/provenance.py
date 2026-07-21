"""
GET /api/meta/provenance — sources, caveats, last-updated, sensitivity policy.

Dataset-level only — NEVER per-record recorder or precise location info.

STUB: fake data in the contract shape. Swap for real values in B8.
"""

from fastapi import APIRouter

from app.models import Provenance

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta/provenance", response_model=Provenance)
def provenance() -> Provenance:
    return Provenance(
        sources=[
            "Bristol Regional Environmental Records Centre (BRERC)",
            "NBN Atlas partners",
        ],
        caveats=[
            "Absence of records does not mean absence of a species.",
            "Sensitive-species locations are generalised to protect them.",
            "Only accepted records are shown on the public dashboard.",
        ],
        lastUpdated="2026-07-22",
        sensitivityPolicySummary=(
            "Locations of sensitive species, badger setts and Schedule 1 bird "
            "nest sites are generalised to a coarse grid. Recorder names are "
            "not published."
        ),
    )

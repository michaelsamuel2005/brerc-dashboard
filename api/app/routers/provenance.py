"""
GET /api/meta/provenance — sources, caveats, last-updated, sensitivity policy.

NOW READS REAL DATA (B8) from the public_provenance view. Dataset-level only —
NEVER per-record recorder or precise location info.
"""

from fastapi import APIRouter, HTTPException

from app.db import get_connection
from app.models import Provenance

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta/provenance", response_model=Provenance)
def provenance() -> Provenance:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sources, caveats, last_updated, sensitivity_policy_summary
                FROM public_provenance;
                """
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Provenance not set")

    return Provenance(
        sources=row["sources"],
        caveats=row["caveats"],
        lastUpdated=row["last_updated"].isoformat(),   # date -> "2026-07-25"
        sensitivityPolicySummary=row["sensitivity_policy_summary"],
    )

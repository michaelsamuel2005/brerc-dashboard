"""
GET /api/meta/provenance — dataset-level caveats and when the data was last loaded.

Reads ONLY from the public views. Dataset-level information only — never
per-record recorder or location detail.

FOR THE MAINTAINER — what this endpoint deliberately does NOT return:

  * A list of contributing sources. Naming which dataset each batch came from
    narrows down who collected it and roughly where they were working. Removed
    on purpose.

  * Any description of how sensitive locations are generalised. Publishing the
    blurring rules tells someone trying to find a protected species exactly how
    much precision has been removed, and therefore how much to add back.

Both were removed on purpose. If someone asks for them back, please check with
BRERC first — they are a data-protection decision, not a display preference.

"lastUpdated" is MEASURED, not typed in by hand: it is the most recent load date
across the records actually being served. That means it cannot drift out of date
or be forgotten — if the daily load stops running, this date stops moving, which
is exactly the signal you want.
"""

from fastapi import APIRouter, HTTPException

from app.db import get_connection
from app.models import Provenance

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta/provenance", response_model=Provenance)
def provenance() -> Provenance:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Only the caveats are read from the provenance row now. `sources`
            # and `sensitivity_policy_summary` still exist in the table but are
            # deliberately not selected — what we never fetch, we can never leak.
            cur.execute("SELECT caveats FROM public_provenance LIMIT 1;")
            row = cur.fetchone()

            # The real "last updated": the newest load date among the records
            # currently being served.
            cur.execute("SELECT MAX(load_date) AS last_load FROM public_records;")
            last_load = cur.fetchone()["last_load"]

    if row is None:
        raise HTTPException(status_code=404, detail="Provenance not set")

    if last_load is None:
        # No records carry a load date yet (an empty database, or a pipeline run
        # that predates the load_date column). Say so honestly rather than
        # inventing a date or showing today's, which would imply fresh data.
        raise HTTPException(
            status_code=503,
            detail="Data load date is not available yet",
        )

    return Provenance(
        caveats=row["caveats"],
        lastUpdated=last_load.isoformat(),   # date -> "2026-07-25"
    )

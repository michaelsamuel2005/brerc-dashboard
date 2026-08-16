"""GET /api/meta/provenance — what was published, and what that means.

Every value here is derived from the active release rather than configured, so
the page cannot describe a dataset other than the one being served.  In
particular the generalisation tiers are the distinct precisions actually present
in the published cells, and the caveats are generated from the release's own
capability flags — a caveat can only say a field is unavailable when it truly is.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import SENSITIVITY_POLICY_NOTE
from app.db import assert_serving_relation, serving_connection
from app.models import Provenance, SensitivityPolicy
from app.release import ActiveRelease, load_active_release

router = APIRouter(prefix="/api", tags=["meta"])

_TOTAL_SQL = f"""
SELECT COALESCE(SUM(record_count), 0) AS record_total
FROM {assert_serving_relation("serve.public_species_year")}
"""  # noqa: S608 - checked constant

# Every resolution at which this release publishes a location, from BOTH
# surfaces.  Cells and records are generalised independently — a release can
# aggregate cells to 1 km while publishing records at 100 m — so reading only
# one of them would state a tier list that omits a resolution actually in use.
# When individual records are not published, serve.public_record returns nothing
# and this reduces to the cell tiers on its own.
_TIERS_SQL = f"""
SELECT DISTINCT precision_metres FROM {assert_serving_relation("serve.public_distribution_cell")}
UNION
SELECT DISTINCT precision_metres FROM {assert_serving_relation("serve.public_record")}
ORDER BY precision_metres
"""  # noqa: S608 - checked constants


def _coverage_caveats(release: ActiveRelease) -> list[str]:
    """State only what this release actually withholds."""
    caveats: list[str] = []
    if not release.individual_records_available:
        caveats.append(
            "Individual records are not published in this release; "
            "only aggregated counts are available."
        )
    if not release.verification_available:
        caveats.append("Record verification status is not available in this release.")
    if not release.place_available:
        caveats.append("Place names are not published in this release.")
    caveats.append(
        "Counts reflect records held by BRERC and are shaped by recording effort, "
        "so absence from a square does not mean absence in the field."
    )
    return caveats


@router.get("/meta/provenance", response_model=Provenance)
def provenance() -> Provenance:
    with serving_connection() as connection:
        release = load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(_TOTAL_SQL)
            record_total = int(cursor.fetchone()["record_total"])
            cursor.execute(_TIERS_SQL)
            tiers = [int(row["precision_metres"]) for row in cursor.fetchall()]

    return Provenance(
        # The data's own as-of date where the release carries one, else the
        # moment it was activated.  Never "now": that would imply freshness the
        # release cannot vouch for.
        lastUpdated=release.source_data_as_of or release.published_at or "",
        recordTotal=record_total,
        sources=[release.source_label] if release.source_label else [],
        coverageCaveats=_coverage_caveats(release),
        sensitivityPolicy=SensitivityPolicy(
            generalisationTiersMetres=tiers,
            appliesToProtectedTaxa=True,
            note=SENSITIVITY_POLICY_NOTE,
        ),
        # Attributions are supplied by BRERC per source and are not yet agreed.
        # An empty list is the honest answer; inventing one would put an
        # unverified licence claim on a public page.
        attributions=[],
    )

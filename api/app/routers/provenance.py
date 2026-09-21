"""GET /api/meta/provenance — what the active release publishes."""

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

_TIERS_SQL = f"""
SELECT DISTINCT precision_metres
FROM {assert_serving_relation("serve.public_distribution_cell")}
UNION
SELECT DISTINCT precision_metres
FROM {assert_serving_relation("serve.public_record")}
ORDER BY precision_metres
"""  # noqa: S608 - checked constants


def _coverage_caveats(release: ActiveRelease) -> list[str]:
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
        lastUpdated=release.source_data_as_of or release.published_at or "",
        recordTotal=record_total,
        sources=[release.source_label] if release.source_label else [],
        coverageCaveats=_coverage_caveats(release),
        sensitivityPolicy=SensitivityPolicy(
            generalisationTiersMetres=tiers,
            appliesToProtectedTaxa=True,
            note=SENSITIVITY_POLICY_NOTE,
        ),
        attributions=[],
    )

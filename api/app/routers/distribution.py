"""GET /api/distribution/cells — species-scoped aggregate map cells.

No geometry crosses this boundary. The client derives a polygon from the
validated cell identifier, so a precise polygon cannot be mislabeled with a
coarser public grid reference. Unscoped requests return no cells.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import CellDistribution, GridCell
from app.release import load_active_release

router = APIRouter(prefix="/api", tags=["distribution"])

_CELLS = assert_serving_relation("serve.public_distribution_cell")

_CELLS_SQL = f"""
SELECT cell_id, precision_metres,
       SUM(record_count) AS record_count,
       SUM(verified_count) AS verified_count
FROM {_CELLS}
WHERE species_id = %s
  AND (%s::integer IS NULL OR record_year = %s)
GROUP BY cell_id, precision_metres
ORDER BY cell_id, precision_metres
LIMIT %s
"""  # noqa: S608 - checked relation; every request value is bound


@router.get(
    "/distribution/cells",
    response_model=CellDistribution,
    response_model_exclude_unset=True,
)
def distribution_cells(
    species: str | None = Query(None, max_length=120),
    year: int | None = Query(None, ge=1500, le=2200),
) -> CellDistribution:
    with serving_connection() as connection:
        release = load_active_release(connection)
        if species is None:
            return CellDistribution(
                verificationAvailable=release.verification_available,
                cells=[],
            )
        with connection.cursor() as cursor:
            cursor.execute(
                _CELLS_SQL,
                [species, year, year, config.MAX_CELLS + 1],
            )
            rows = cursor.fetchall()

    if len(rows) > config.MAX_CELLS:
        raise HTTPException(
            status_code=503,
            detail="Distribution exceeds the safe response limit; no partial map was returned",
        )

    cells: list[GridCell] = []
    for row in rows:
        fields: dict[str, object] = {
            "cellId": row["cell_id"],
            "precisionMetres": int(row["precision_metres"]),
            "recordCount": int(row["record_count"]),
        }
        if release.verification_available:
            fields["verifiedCount"] = int(row["verified_count"] or 0)
        cells.append(GridCell(**fields))

    return CellDistribution(
        verificationAvailable=release.verification_available,
        cells=cells,
    )

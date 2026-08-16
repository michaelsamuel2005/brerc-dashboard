"""GET /api/distribution/cells — the map layer.

No geometry crosses this boundary.  Each cell is an identifier plus counts, and
the client derives the polygon from the identifier it validated.  That is a
safety property, not a bandwidth optimisation: if the server sent both, a
precise polygon could be labelled with a coarse cell id and the map would draw
the true location of a generalised record.  Sending only the id makes that
class of mistake unrepresentable.

Counts are summed across years and species unless the caller narrows them, so a
square shows how many records fall inside it rather than how many rows the
database happens to hold at one resolution.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import CellDistribution, GridCell
from app.release import load_active_release

router = APIRouter(prefix="/api", tags=["distribution"])

_CELL_RELATION = assert_serving_relation("serve.public_distribution_cell")

# verified_count is nulled by the view when the release withholds verification,
# so SUM() over it yields NULL for the whole cell rather than a partial total.
_CELLS_SQL = f"""
SELECT cell_id,
       precision_metres,
       SUM(record_count) AS record_count,
       SUM(verified_count) AS verified_count
FROM {_CELL_RELATION}
{{where}}
GROUP BY cell_id, precision_metres
ORDER BY cell_id, precision_metres
LIMIT %s
"""  # noqa: S608 - relation is a checked constant; filters are fixed clauses


@router.get(
    "/distribution/cells", response_model=CellDistribution, response_model_exclude_unset=True
)
def distribution_cells(
    species: str | None = Query(None),
    year: int | None = Query(None, ge=1500, le=2200),
) -> CellDistribution:
    clauses: list[str] = []
    params: list[object] = []
    if species is not None:
        clauses.append("species_id = %s")
        params.append(species)
    if year is not None:
        clauses.append("record_year = %s")
        params.append(year)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with serving_connection() as connection:
        release = load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(_CELLS_SQL.format(where=where), [*params, config.MAX_CELLS])
            rows = cursor.fetchall()

    cells: list[GridCell] = []
    for row in rows:
        fields: dict[str, object] = {
            "cellId": row["cell_id"],
            "precisionMetres": int(row["precision_metres"]),
            "recordCount": int(row["record_count"]),
        }
        # Present exactly when the release publishes verification: the contract
        # treats a present key as a claim that the number means something.
        if release.verification_available:
            fields["verifiedCount"] = int(row["verified_count"] or 0)
        cells.append(GridCell(**fields))

    return CellDistribution(
        verificationAvailable=release.verification_available,
        cells=cells,
    )

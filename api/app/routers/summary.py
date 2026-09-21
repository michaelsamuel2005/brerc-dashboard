"""GET /api/summary — global or species-scoped aggregate figures."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import Summary, YearCount, YearRange
from app.release import load_active_release

router = APIRouter(prefix="/api", tags=["summary"])

_SPECIES_YEAR = assert_serving_relation("serve.public_species_year")
_SPECIES = assert_serving_relation("serve.public_species")

_SPECIES_EXISTS_SQL = f"""
SELECT EXISTS (
    SELECT 1 FROM {_SPECIES} WHERE species_id = %s
) AS species_exists
"""  # noqa: S608 - checked relation; species id is bound

_TOTALS_SQL = f"""
SELECT COALESCE(SUM(record_count), 0) AS total_records
FROM {_SPECIES_YEAR}
WHERE (%s::text IS NULL OR species_id = %s)
"""  # noqa: S608 - checked relation; species id is bound

_SPECIES_COUNT_SQL = f"""
SELECT COUNT(*) AS total_species
FROM {_SPECIES}
WHERE (%s::text IS NULL OR species_id = %s)
"""  # noqa: S608 - checked relation; species id is bound

_BY_YEAR_SQL = f"""
SELECT record_year, SUM(record_count) AS record_count
FROM {_SPECIES_YEAR}
WHERE (%s::text IS NULL OR species_id = %s)
GROUP BY record_year
HAVING SUM(record_count) > 0
ORDER BY record_year
LIMIT %s
"""  # noqa: S608 - checked relation; species id and cap are bound

COVERAGE_CAVEAT = (
    "Counts reflect records held by BRERC and are shaped by recording effort, "
    "so absence from a square does not mean absence in the field."
)


@router.get("/summary", response_model=Summary)
def summary(species: str | None = Query(None, max_length=120)) -> Summary:
    parameters: list[object] = [species, species]
    with serving_connection() as connection:
        load_active_release(connection)
        with connection.cursor() as cursor:
            if species is not None:
                cursor.execute(_SPECIES_EXISTS_SQL, [species])
                if cursor.fetchone()["species_exists"] is not True:
                    raise HTTPException(status_code=404, detail="Species not found")
            cursor.execute(_TOTALS_SQL, parameters)
            total_records = int(cursor.fetchone()["total_records"])
            cursor.execute(_SPECIES_COUNT_SQL, parameters)
            total_species = int(cursor.fetchone()["total_species"])
            cursor.execute(_BY_YEAR_SQL, [*parameters, config.MAX_YEAR_BUCKETS])
            year_rows = cursor.fetchall()

    records_by_year = [
        YearCount(year=int(row["record_year"]), count=int(row["record_count"])) for row in year_rows
    ]
    year_range = (
        YearRange(min=records_by_year[0].year, max=records_by_year[-1].year)
        if records_by_year
        else None
    )
    return Summary(
        totalRecords=total_records,
        totalSpecies=total_species,
        yearRange=year_range,
        recordsByYear=records_by_year,
        topGroups=[],
        coverageCaveat=COVERAGE_CAVEAT,
    )

"""GET /api/summary — headline figures for the landing page.

Every number is read from the active release, so the page cannot describe a
dataset other than the one being served.  ``topGroups`` is empty by
construction: ``publication.public_species.taxon_group`` is constrained to NULL
until ``taxa_nb`` is mapped into the safe projection and approval-bound, so the
release genuinely publishes no taxonomic grouping.  An empty list is the honest
statement; inventing a grouping to fill the section would put a taxonomic claim
on a public page that no approved contract supports.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import Summary, YearCount, YearRange
from app.release import load_active_release

router = APIRouter(prefix="/api", tags=["summary"])

_SPECIES_YEAR = assert_serving_relation("serve.public_species_year")
_SPECIES = assert_serving_relation("serve.public_species")

_TOTALS_SQL = f"""
SELECT COALESCE(SUM(record_count), 0) AS total_records,
       MIN(record_year) AS first_year,
       MAX(record_year) AS last_year
FROM {_SPECIES_YEAR}
"""  # noqa: S608 - checked constant

_SPECIES_COUNT_SQL = f"SELECT COUNT(*) AS total_species FROM {_SPECIES}"  # noqa: S608

# Only years that actually carry records: the contract requires every bucket's
# count to be positive, and the first and last buckets to be the year range.
_BY_YEAR_SQL = f"""
SELECT record_year, SUM(record_count) AS record_count
FROM {_SPECIES_YEAR}
GROUP BY record_year
HAVING SUM(record_count) > 0
ORDER BY record_year
LIMIT %s
"""  # noqa: S608 - checked constant

COVERAGE_CAVEAT = (
    "Counts reflect records held by BRERC and are shaped by recording effort, "
    "so absence from a square does not mean absence in the field."
)


@router.get("/summary", response_model=Summary)
def summary() -> Summary:
    with serving_connection() as connection:
        load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(_TOTALS_SQL)
            totals = cursor.fetchone()
            cursor.execute(_SPECIES_COUNT_SQL)
            total_species = int(cursor.fetchone()["total_species"])
            cursor.execute(_BY_YEAR_SQL, [config.MAX_YEAR_BUCKETS])
            year_rows = cursor.fetchall()

    total_records = int(totals["total_records"])
    records_by_year = [
        YearCount(year=int(row["record_year"]), count=int(row["record_count"])) for row in year_rows
    ]
    # Derived from the buckets actually returned, so the range can never claim a
    # year the chart does not show — which the contract checks explicitly.
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

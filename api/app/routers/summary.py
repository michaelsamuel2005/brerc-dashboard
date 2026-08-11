"""
GET /api/summary — headline numbers for the dashboard landing view.

NOW READS REAL DATA (B8) from the public views. All counts come from the safe
public layer, so nothing sensitive is ever aggregated in.
"""

from fastapi import APIRouter

from app.db import get_connection
from app.models import Summary, YearCount, TopGroup

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/summary", response_model=Summary)
def summary() -> Summary:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM public_records;")
            total_records = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM public_species;")
            total_species = cur.fetchone()["n"]

            cur.execute(
                "SELECT MIN(record_year) AS lo, MAX(record_year) AS hi FROM public_records;"
            )
            span = cur.fetchone()
            year_range = [span["lo"], span["hi"]] if span["lo"] is not None else [0, 0]

            # Records per year (for the year chart).
            cur.execute(
                "SELECT record_year AS yr, COUNT(*) AS cnt "
                "FROM public_records GROUP BY record_year ORDER BY record_year;"
            )
            records_by_year = [
                YearCount(year=r["yr"], count=r["cnt"]) for r in cur.fetchall()
            ]

            # Biggest species groups (birds, mammals, …).
            cur.execute(
                "SELECT species_group AS grp, SUM(record_count) AS cnt "
                "FROM public_species GROUP BY species_group ORDER BY cnt DESC, species_group;"
            )
            top_groups = [
                TopGroup(group=r["grp"], count=int(r["cnt"])) for r in cur.fetchall()
            ]

    return Summary(
        totalRecords=total_records,
        totalSpecies=total_species,
        yearRange=year_range,
        recordsByYear=records_by_year,
        topGroups=top_groups,
        coverageCaveat=(
            "Absence of records does not mean absence of a species. "
            "Public totals may be lower than BRERC's full holdings because only "
            "accepted records are shown and sensitive locations are generalised."
        ),
    )

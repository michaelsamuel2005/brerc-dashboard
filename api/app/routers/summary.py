"""
GET /api/summary — headline numbers for the dashboard landing view.

STUB: returns fake data in the contract shape. Swap for a real query in B8.
"""

from fastapi import APIRouter

from app.models import Summary, YearCount, TopGroup

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/summary", response_model=Summary)
def summary() -> Summary:
    return Summary(
        totalRecords=4873120,
        totalSpecies=14830,
        yearRange=[1901, 2025],
        recordsByYear=[
            YearCount(year=2021, count=210345),
            YearCount(year=2022, count=225880),
            YearCount(year=2023, count=241002),
            YearCount(year=2024, count=256719),
            YearCount(year=2025, count=133540),
        ],
        topGroups=[
            TopGroup(group="birds", count=1520340),
            TopGroup(group="plants", count=1104558),
            TopGroup(group="insects", count=986221),
            TopGroup(group="mammals", count=412009),
        ],
        coverageCaveat=(
            "Absence of records does not mean absence of a species. "
            "Public totals may be lower than BRERC's full holdings because only "
            "accepted records are shown and sensitive locations are generalised."
        ),
    )

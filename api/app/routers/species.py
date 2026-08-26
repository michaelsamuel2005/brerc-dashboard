"""GET /api/species and /api/species/{id} — the public species directory.

Taxonomic groups remain nullable until a reviewed vocabulary is approved.
Media are fallback-only: this API never invokes the legacy outbound species
proxy and publishes no asset without an approved licence and attribution.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import (
    SpeciesDetail,
    SpeciesFacets,
    SpeciesGroupFacet,
    SpeciesListItem,
    SpeciesListPage,
    SpeciesStats,
)
from app.release import ActiveRelease, load_active_release
from app.slugs import species_slug

router = APIRouter(prefix="/api", tags=["species"])

_SPECIES = assert_serving_relation("serve.public_species")
_SPECIES_YEAR = assert_serving_relation("serve.public_species_year")

_FILTER_SQL = r"""
WHERE (%s::text IS NULL OR taxon_group = %s)
  AND (
      %s::text IS NULL
      OR scientific_name ILIKE %s ESCAPE '\'
      OR common_name ILIKE %s ESCAPE '\'
  )
"""

_LIST_PREFIX = f"""
SELECT species_id, scientific_name, common_name, taxon_group,
       total_records, first_year, last_year
FROM {_SPECIES}
{_FILTER_SQL}
"""  # noqa: S608 - checked relation; request values are bound

_LIST_SQL_BY_SORT = {
    "name-asc": (
        _LIST_PREFIX
        + 'ORDER BY common_name ASC NULLS LAST, species_id COLLATE "C" ASC LIMIT %s OFFSET %s'
    ),
    "scientific-name-asc": (
        _LIST_PREFIX + 'ORDER BY scientific_name ASC, species_id COLLATE "C" ASC LIMIT %s OFFSET %s'
    ),
    "records-desc": (
        _LIST_PREFIX + 'ORDER BY total_records DESC, species_id COLLATE "C" ASC LIMIT %s OFFSET %s'
    ),
    "latest-record-desc": (
        _LIST_PREFIX + 'ORDER BY last_year DESC, species_id COLLATE "C" ASC LIMIT %s OFFSET %s'
    ),
}

_COUNT_SQL = f"SELECT COUNT(*) AS total FROM {_SPECIES} {_FILTER_SQL}"  # noqa: S608

_AMBIGUOUS_SQL = f"""
SELECT scientific_name
FROM {_SPECIES}
GROUP BY scientific_name
HAVING COUNT(*) > 1
"""  # noqa: S608

_FACETS_SQL = f"""
SELECT taxon_group AS value, COUNT(*) AS species_count
FROM {_SPECIES}
WHERE taxon_group IS NOT NULL
GROUP BY taxon_group
ORDER BY taxon_group
"""  # noqa: S608

_DETAIL_SQL = f"""
SELECT species_id, scientific_name, common_name, taxon_group,
       total_records, first_year, last_year
FROM {_SPECIES}
WHERE species_id = %s
"""  # noqa: S608

_VERIFIED_SQL = f"""
SELECT COALESCE(SUM(verified_count), 0) AS verified_count
FROM {_SPECIES_YEAR}
WHERE species_id = %s
"""  # noqa: S608


def _filter_parameters(q: str | None, group: str | None) -> list[object]:
    group_value = group.strip() if group and group.strip() else None
    pattern: str | None = None
    if q and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
    return [group_value, group_value, pattern, pattern, pattern]


def _item(row: dict, ambiguous: set[str]) -> SpeciesListItem:
    record_count = int(row["total_records"])
    has_records = record_count > 0
    return SpeciesListItem(
        speciesId=str(row["species_id"]),
        slug=species_slug(
            row["scientific_name"],
            str(row["species_id"]),
            ambiguous=row["scientific_name"] in ambiguous,
        ),
        scientificName=row["scientific_name"],
        commonName=row["common_name"],
        group=row["taxon_group"],
        recordCount=record_count,
        firstYear=int(row["first_year"]) if has_records else None,
        lastYear=int(row["last_year"]) if has_records else None,
        hasImage=False,
    )


@router.get("/species", response_model=SpeciesListPage)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=config.MAX_PAGE_SIZE),
    sort: Literal[
        "name-asc",
        "scientific-name-asc",
        "records-desc",
        "latest-record-desc",
    ] = Query("name-asc"),
    q: str | None = Query(None, max_length=120),
    group: str | None = Query(None, max_length=120),
    sort_by: Literal["commonName", "scientificName"] | None = Query(
        None,
        deprecated=True,
        description="Deprecated compatibility alias; use sort.",
    ),
) -> SpeciesListPage:
    if sort_by is not None:
        legacy_sort = {
            "commonName": "name-asc",
            "scientificName": "scientific-name-asc",
        }[sort_by]
        if sort != "name-asc" and sort != legacy_sort:
            raise HTTPException(status_code=422, detail="Conflicting sort parameters")
        sort = legacy_sort
    if sort not in _LIST_SQL_BY_SORT:
        raise HTTPException(status_code=422, detail="Unsupported sort")
    page_size = min(pageSize, config.MAX_PAGE_SIZE)
    parameters = _filter_parameters(q, group)

    with serving_connection() as connection:
        load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                _LIST_SQL_BY_SORT[sort],
                [*parameters, page_size, (page - 1) * page_size],
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_SQL, parameters)
            total = int(cursor.fetchone()["total"])
            cursor.execute(_AMBIGUOUS_SQL)
            ambiguous = {row["scientific_name"] for row in cursor.fetchall()}
            cursor.execute(_FACETS_SQL)
            facet_rows = cursor.fetchall()

    return SpeciesListPage(
        items=[_item(row, ambiguous) for row in rows],
        page=page,
        pageSize=page_size,
        total=total,
        facets=SpeciesFacets(
            groups=[
                SpeciesGroupFacet(
                    value=row["value"],
                    label=row["value"],
                    speciesCount=int(row["species_count"]),
                )
                for row in facet_rows
            ]
        ),
    )


@router.get("/species/{species_id}", response_model=SpeciesDetail)
def species_detail(species_id: str) -> SpeciesDetail:
    with serving_connection() as connection:
        release: ActiveRelease = load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(_DETAIL_SQL, [species_id])
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Species not found")
            cursor.execute(_AMBIGUOUS_SQL)
            ambiguous = {item["scientific_name"] for item in cursor.fetchall()}
            verified_count = None
            if release.verification_available:
                cursor.execute(_VERIFIED_SQL, [species_id])
                verified_count = int(cursor.fetchone()["verified_count"])

    record_count = int(row["total_records"])
    has_records = record_count > 0
    return SpeciesDetail(
        speciesId=str(row["species_id"]),
        slug=species_slug(
            row["scientific_name"],
            str(row["species_id"]),
            ambiguous=row["scientific_name"] in ambiguous,
        ),
        scientificName=row["scientific_name"],
        commonName=row["common_name"],
        group=row["taxon_group"],
        imagePublication="fallback-only",
        stats=SpeciesStats(
            recordCount=record_count,
            yearRange=(int(row["first_year"]), int(row["last_year"])) if has_records else None,
            verificationAvailable=release.verification_available,
            verifiedCount=verified_count,
        ),
    )

"""GET /api/species and /api/species/{id} — the species directory.

``group`` is published as null.  ``publication.public_species.taxon_group`` is
CHECK-constrained to NULL until ``taxa_nb`` is mapped into the safe projection
and approval-bound, and ``taxa_nb`` is unbounded free text, which this codebase
never publishes without a reviewed vocabulary — ``public_source_label`` is
restricted to a reviewed list precisely because raw source text may carry
personal data.  Nulls here are the honest report of what the release publishes,
and the facet list is correspondingly empty.  When a reviewed vocabulary exists
this becomes additive: groups appear, and species outside the vocabulary keep
rendering as ungrouped rather than being hidden or mislabelled.

Images are ``fallback-only``: no approved image assets exist, and a species
image may only be published with a verified licence and attribution.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db import assert_serving_relation, serving_connection
from app.models import (
    SpeciesDetail,
    SpeciesFacets,
    SpeciesListItem,
    SpeciesListPage,
    SpeciesStats,
)
from app.release import ActiveRelease, load_active_release
from app.slugs import species_slug

router = APIRouter(prefix="/api", tags=["species"])

_SPECIES = assert_serving_relation("serve.public_species")
_SPECIES_YEAR = assert_serving_relation("serve.public_species_year")

#: Only these orderings are accepted; the value is never interpolated from the
#: request, it selects a fixed clause. Ties break on species_id so paging is
#: stable and a row can never be repeated or skipped between pages.
_SORTS = {
    "name-asc": 'common_name ASC NULLS LAST, species_id COLLATE "C" ASC',
    "scientific-name-asc": 'scientific_name ASC, species_id COLLATE "C" ASC',
    "records-desc": 'total_records DESC, species_id COLLATE "C" ASC',
    "latest-record-desc": 'last_year DESC, species_id COLLATE "C" ASC',
}

_LIST_SQL = """
SELECT species_id, scientific_name, common_name, taxon_group,
       total_records, first_year, last_year
FROM {relation}
{where}
ORDER BY {order}
LIMIT %s OFFSET %s
"""

_COUNT_SQL = "SELECT COUNT(*) AS total FROM {relation} {where}"

#: Names carried by more than one species in this release. Only these need the
#: id appended to keep their slugs distinct.
_AMBIGUOUS_SQL = f"""
SELECT scientific_name
FROM {_SPECIES}
GROUP BY scientific_name
HAVING COUNT(*) > 1
"""  # noqa: S608 - checked constant

_FACETS_SQL = f"""
SELECT taxon_group AS value, COUNT(*) AS species_count
FROM {_SPECIES}
WHERE taxon_group IS NOT NULL
GROUP BY taxon_group
ORDER BY taxon_group
"""  # noqa: S608 - checked constant

_DETAIL_SQL = f"""
SELECT species_id, scientific_name, common_name, taxon_group,
       total_records, first_year, last_year
FROM {_SPECIES}
WHERE species_id = %s
"""  # noqa: S608 - checked constant

_VERIFIED_SQL = f"""
SELECT COALESCE(SUM(verified_count), 0) AS verified_count
FROM {_SPECIES_YEAR}
WHERE species_id = %s
"""  # noqa: S608 - checked constant


def _search_clause(search: str | None) -> tuple[str, list[object]]:
    if not search or not search.strip():
        return "", []
    # Matched as a parameter, never interpolated. ILIKE with escaped wildcards so
    # a caller cannot turn a search box into a full-table scan pattern.
    term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return (
        "WHERE (scientific_name ILIKE %s ESCAPE '\\' OR common_name ILIKE %s ESCAPE '\\')",
        [f"%{term}%", f"%{term}%"],
    )


def _item(row: dict, ambiguous: set[str]) -> SpeciesListItem:
    record_count = int(row["total_records"])
    # The contract ties these together: a species with no records must carry no
    # year range, and one with records must carry both years.
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
        # No approved image assets exist; a species image needs a verified
        # licence and attribution before it may be shown.
        hasImage=False,
    )


@router.get("/species", response_model=SpeciesListPage)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=config.MAX_PAGE_SIZE),
    sort: str = Query("name-asc"),
    search: str | None = Query(None, max_length=120),
) -> SpeciesListPage:
    if sort not in _SORTS:
        raise HTTPException(status_code=422, detail="Unsupported sort")
    page_size = min(pageSize, config.MAX_PAGE_SIZE)
    where, params = _search_clause(search)

    with serving_connection() as connection:
        load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                _LIST_SQL.format(relation=_SPECIES, where=where, order=_SORTS[sort]),
                [*params, page_size, (page - 1) * page_size],
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_SQL.format(relation=_SPECIES, where=where), params)
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
                {
                    "value": row["value"],
                    "label": row["value"],
                    "speciesCount": int(row["species_count"]),
                }
                for row in facet_rows
            ]
        ),
    )


@router.get("/species/{species_id}", response_model=SpeciesDetail)
def species_detail(species_id: str) -> SpeciesDetail:
    with serving_connection() as connection:
        release: ActiveRelease = load_active_release(connection)
        with connection.cursor() as cursor:
            cursor.execute(_DETAIL_SQL, (species_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Species not found")
            cursor.execute(_AMBIGUOUS_SQL)
            ambiguous = {r["scientific_name"] for r in cursor.fetchall()}
            verified_count = None
            if release.verification_available:
                cursor.execute(_VERIFIED_SQL, (species_id,))
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
        # No approved assets: the contract forbids an image under this value.
        imagePublication="fallback-only",
        stats=SpeciesStats(
            recordCount=record_count,
            yearRange=(int(row["first_year"]), int(row["last_year"])) if has_records else None,
            verificationAvailable=release.verification_available,
            verifiedCount=verified_count,
        ),
    )

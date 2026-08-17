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

Images and descriptions come only from the APPROVED assets registry
(app/species_assets.py): media a human has signed off, each with a verified
licence, full attribution and an approval reference.  A species with an
approved image publishes as ``approved-assets``; every other species — and
every deployment without an assets file — publishes as ``fallback-only``, and
the front end shows its labelled placeholder.  This endpoint never fetches
media from a third party at request time.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import config, species_assets
from app.db import assert_serving_relation, serving_connection
from app.models import (
    DescriptionSource,
    SpeciesDetail,
    SpeciesFacets,
    SpeciesImage,
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


def _filter_clause(q: str | None, group: str | None) -> tuple[str, list[object]]:
    """Build the WHERE clause from the client's `q` and `group` parameters.

    Both are bound as parameters. The search term additionally has its LIKE
    wildcards escaped, so a search box cannot be turned into a pattern that
    scans the whole table.
    """
    clauses: list[str] = []
    params: list[object] = []
    if group is not None and group.strip():
        clauses.append("taxon_group = %s")
        params.append(group.strip())
    search = q
    if search and search.strip():
        term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(scientific_name ILIKE %s ESCAPE '\\' OR common_name ILIKE %s ESCAPE '\\')")
        params.extend([f"%{term}%", f"%{term}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


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
        # True only when the approved-assets registry holds a signed-off,
        # licence-verified image for this species.
        hasImage=species_assets.registry().has_image(row["scientific_name"]),
    )


@router.get("/species", response_model=SpeciesListPage)
def list_species(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=config.MAX_PAGE_SIZE),
    sort: str = Query("name-asc"),
    # Named for what the client sends: `q` is the search box, `group` the facet.
    q: str | None = Query(None, max_length=120),
    group: str | None = Query(None, max_length=120),
) -> SpeciesListPage:
    if sort not in _SORTS:
        raise HTTPException(status_code=422, detail="Unsupported sort")
    page_size = min(pageSize, config.MAX_PAGE_SIZE)
    where, params = _filter_clause(q, group)

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


@router.get(
    "/species/{species_id}",
    response_model=SpeciesDetail,
    # Optional media keys are OMITTED when unset, never sent as null — the web
    # schema marks them .optional(), not nullable.  Same mechanism as /records.
    response_model_exclude_unset=True,
)
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

    # Media come only from the approved-assets registry.  The publication mode
    # is per-response: approved-assets exactly when THIS species has an approved
    # image (the contract then requires the image), fallback-only otherwise (the
    # contract then forbids one).  Optional keys are added to `media` only when
    # present, so response_model_exclude_unset omits them entirely.
    assets = species_assets.registry().for_name(row["scientific_name"])
    media: dict[str, object] = {}
    if assets is not None and assets.image is not None:
        approved = assets.image
        media["image"] = SpeciesImage(
            url=approved.url,
            attributionText=approved.attributionText,
            licence=approved.licence,
            licenceUrl=approved.licenceUrl,
            sourceUrl=approved.sourceUrl,
            approvalReference=approved.approvalReference,
            alt=approved.alt,
        )
    if assets is not None and assets.description is not None:
        source = assets.descriptionSource
        source_fields: dict[str, object] = {
            "label": source.label,
            "approvalReference": source.approvalReference,
        }
        if source.sourceUrl is not None:
            source_fields["sourceUrl"] = source.sourceUrl
        if source.licence is not None:
            source_fields["licence"] = source.licence
        if source.licenceUrl is not None:
            source_fields["licenceUrl"] = source.licenceUrl
        media["description"] = assets.description
        media["descriptionSource"] = DescriptionSource(**source_fields)

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
        imagePublication="approved-assets" if "image" in media else "fallback-only",
        stats=SpeciesStats(
            recordCount=record_count,
            yearRange=(int(row["first_year"]), int(row["last_year"])) if has_records else None,
            verificationAvailable=release.verification_available,
            verifiedCount=verified_count,
        ),
        **media,
    )

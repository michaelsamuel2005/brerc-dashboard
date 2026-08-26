"""Live contract checks against an active publication-store release.

Run with ``BRERC_API_INTEGRATION=1`` and ``DATABASE_URL`` set to the
``brerc_api`` read-only role. The default skip keeps ordinary unit CI
independent of a database while retaining a production-shaped acceptance test.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BRERC_API_INTEGRATION") != "1",
    reason="requires the publication database and read-only API role",
)

PROVENANCE_KEYS = {
    "lastUpdated",
    "recordTotal",
    "sources",
    "coverageCaveats",
    "sensitivityPolicy",
    "attributions",
}
SPECIES_PAGE_KEYS = {"items", "page", "pageSize", "total", "facets"}
SPECIES_ITEM_KEYS = {
    "speciesId",
    "slug",
    "scientificName",
    "commonName",
    "group",
    "recordCount",
    "firstYear",
    "lastYear",
    "hasImage",
}
SPECIES_DETAIL_KEYS = {
    "speciesId",
    "slug",
    "scientificName",
    "commonName",
    "group",
    "imagePublication",
    "stats",
}
SUMMARY_KEYS = {
    "totalRecords",
    "totalSpecies",
    "yearRange",
    "recordsByYear",
    "topGroups",
    "coverageCaveat",
}
RECORD_PAGE_KEYS = {"publication", "items", "page", "pageSize", "total"}
CELL_KEYS = {"cellId", "precisionMetres", "recordCount"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def listed_species(client) -> dict:
    response = client.get("/api/species", params={"pageSize": 100})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items, "the acceptance release must contain at least one species"
    return items[0]


def test_health_is_database_independent_and_exact(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "version"}
    assert response.json()["status"] == "ok"


def test_provenance_describes_the_active_release_exactly(client) -> None:
    response = client.get("/api/meta/provenance")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == PROVENANCE_KEYS
    assert body["recordTotal"] >= 0
    assert body["coverageCaveats"]
    assert body["sensitivityPolicy"]["appliesToProtectedTaxa"] is True
    tiers = body["sensitivityPolicy"]["generalisationTiersMetres"]
    assert tiers == sorted(set(tiers))
    assert all(tier in {100, 1000, 10000} for tier in tiers)
    assert body["lastUpdated"]
    assert " " not in body["lastUpdated"]
    datetime.fromisoformat(body["lastUpdated"])

    from app.db import serving_connection

    with serving_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(SUM(record_count), 0) AS total FROM serve.public_species_year"
        )
        observed_total = int(cursor.fetchone()["total"])
        cursor.execute(
            "SELECT DISTINCT precision_metres FROM serve.public_distribution_cell "
            "UNION SELECT DISTINCT precision_metres FROM serve.public_record "
            "ORDER BY precision_metres"
        )
        observed_tiers = [int(row["precision_metres"]) for row in cursor.fetchall()]
    assert body["recordTotal"] == observed_total
    assert tiers == observed_tiers


def test_species_listing_and_detail_match_the_strict_browser_contract(
    client, listed_species: dict
) -> None:
    listing = client.get("/api/species", params={"pageSize": 100}).json()
    assert set(listing) == SPECIES_PAGE_KEYS
    assert set(listing["facets"]) == {"groups"}
    assert len(listing["items"]) <= listing["pageSize"]
    assert len(listing["items"]) <= listing["total"]
    assert len({item["speciesId"] for item in listing["items"]}) == len(listing["items"])
    assert len({item["slug"] for item in listing["items"]}) == len(listing["items"])
    for item in listing["items"]:
        assert set(item) == SPECIES_ITEM_KEYS
        assert SLUG_PATTERN.fullmatch(item["slug"])
        assert item["recordCount"] > 0
        assert item["firstYear"] <= item["lastYear"]

    response = client.get(f"/api/species/{listed_species['speciesId']}")
    assert response.status_code == 200
    detail = response.json()
    assert set(detail) == SPECIES_DETAIL_KEYS
    assert detail["speciesId"] == listed_species["speciesId"]
    assert detail["slug"] == listed_species["slug"]
    assert detail["imagePublication"] == "fallback-only"
    assert "image" not in detail
    assert set(detail["stats"]) == {
        "recordCount",
        "yearRange",
        "verificationAvailable",
        "verifiedCount",
    }
    assert detail["stats"]["recordCount"] == listed_species["recordCount"]
    assert detail["stats"]["verificationAvailable"] == (
        detail["stats"]["verifiedCount"] is not None
    )


def test_species_search_escapes_wildcards_and_sort_is_allow_listed(client) -> None:
    for pattern in ("%", "_", "%%", "\\"):
        response = client.get("/api/species", params={"q": pattern})
        assert response.status_code == 200
        assert response.json()["total"] == 0

    for order in (
        "name-asc",
        "scientific-name-asc",
        "records-desc",
        "latest-record-desc",
    ):
        assert client.get("/api/species", params={"sort": order}).status_code == 200
    assert (
        client.get(
            "/api/species",
            params={"sort": "total_records; DROP TABLE publication.public_species"},
        ).status_code
        == 422
    )


def test_summary_supports_real_species_scope_and_404s_unknown(client, listed_species: dict) -> None:
    global_response = client.get("/api/summary")
    assert global_response.status_code == 200
    global_body = global_response.json()
    assert set(global_body) == SUMMARY_KEYS
    assert sum(row["count"] for row in global_body["recordsByYear"]) == global_body["totalRecords"]
    assert global_body["topGroups"] == []

    scoped_response = client.get("/api/summary", params={"species": listed_species["speciesId"]})
    assert scoped_response.status_code == 200
    scoped = scoped_response.json()
    assert set(scoped) == SUMMARY_KEYS
    assert scoped["totalSpecies"] == 1
    assert scoped["totalRecords"] == listed_species["recordCount"]
    assert sum(row["count"] for row in scoped["recordsByYear"]) == scoped["totalRecords"]
    assert client.get("/api/summary", params={"species": "NO-SUCH-SPECIES"}).status_code == 404


def test_distribution_is_empty_unscoped_and_safe_when_scoped(client, listed_species: dict) -> None:
    unscoped = client.get("/api/distribution/cells")
    assert unscoped.status_code == 200
    assert unscoped.json()["cells"] == []
    assert (
        client.get("/api/distribution/cells", params={"species": "NO-SUCH-SPECIES"}).json()["cells"]
        == []
    )

    response = client.get(
        "/api/distribution/cells", params={"species": listed_species["speciesId"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"verificationAvailable", "cells"}
    assert body["cells"], "a listed species must have aggregate distribution cells"
    forbidden = {
        "geom",
        "geometry",
        "coordinates",
        "polygon",
        "latitude",
        "longitude",
        "easting",
        "northing",
    }
    for cell in body["cells"]:
        assert set(cell) - {"verifiedCount"} == CELL_KEYS
        assert not (set(cell) & forbidden)
        assert cell["precisionMetres"] in {100, 1000, 10000}
        assert cell["recordCount"] > 0
        assert ("verifiedCount" in cell) == body["verificationAvailable"]


def test_records_are_empty_unscoped_and_honour_the_year_filter(
    client, listed_species: dict
) -> None:
    unscoped = client.get("/api/records")
    assert unscoped.status_code == 200
    body = unscoped.json()
    assert set(body) == RECORD_PAGE_KEYS
    assert body["items"] == []
    assert body["total"] == 0

    scoped = client.get(
        "/api/records", params={"species": listed_species["speciesId"], "pageSize": 100}
    ).json()
    assert set(scoped) == RECORD_PAGE_KEYS
    assert set(scoped["publication"]) == {"mode", "fields"}
    assert set(scoped["publication"]["fields"]) == {
        "abundance",
        "place",
        "recordType",
        "verification",
    }
    if scoped["publication"]["mode"] == "aggregates-only":
        assert scoped["items"] == []
        assert scoped["total"] == 0
        return

    assert scoped["items"], "individual-record mode must expose scoped records"
    selected_year = scoped["items"][0]["year"]
    by_year = client.get(
        "/api/records",
        params={
            "species": listed_species["speciesId"],
            "year": selected_year,
            "pageSize": 100,
        },
    )
    assert by_year.status_code == 200
    assert by_year.json()["items"]
    assert {row["year"] for row in by_year.json()["items"]} == {selected_year}
    assert client.get("/api/records", params={"species": "NO-SUCH-SPECIES"}).json()["items"] == []


def test_api_role_cannot_write_and_guard_rejects_base_tables() -> None:
    import psycopg

    from app.db import ServingRelationError, assert_serving_relation, serving_connection

    with (
        serving_connection() as connection,
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        cursor.execute("CREATE TEMP TABLE api_should_not_write (id integer)")

    for relation in (
        "publication.public_record",
        "loader_control.source_disposition",
        "serve.etl_job_status",
    ):
        with pytest.raises(ServingRelationError):
            assert_serving_relation(relation)

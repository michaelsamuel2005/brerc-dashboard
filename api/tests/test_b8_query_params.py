"""
Tests for the species sort/filter parameters, the row caps, and what
/api/meta/provenance is allowed to say.

WHAT THESE ARE PROTECTING — three separate promises:

  1. A caller can only sort by a column we chose in advance. Sort parameters are
     a classic way into SQL injection, because a column name can't be passed to
     the database as a parameter the way a value can. Our defence is a
     whitelist, and these tests prove anything outside it is rejected outright.

  2. No request can ever pull out more than a fixed number of rows. That is what
     keeps the dashboard a lookup tool rather than a bulk download.

  3. /api/meta/provenance does not name the contributing sources or explain how
     sensitive locations are blurred. Both were removed deliberately, and it
     would be easy to add either back without realising why they went.

Tests that need a database skip themselves when there isn't one, so the suite
stays green on a machine (or CI runner) without PostgreSQL.
"""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from conftest import needs_b6_schema, needs_load_date

client = TestClient(app)


# =============================================================================
# 1. sort_by — only the two values we allow
# =============================================================================

@needs_b6_schema
@pytest.mark.parametrize("sort_by, field", [
    ("commonName", "commonName"),
    ("scientificName", "scientificName"),
])
def test_sort_by_accepts_the_whitelisted_values(sort_by, field):
    response = client.get("/api/species", params={"sort_by": sort_by})

    assert response.status_code == 200
    values = [item[field] for item in response.json()["items"] if item[field]]
    assert values == sorted(values), f"{sort_by} did not come back in order"


@pytest.mark.parametrize("bad_value", [
    "recordCount",              # a real column, but not one we offer
    "record_count",             # the database's own name for it
    "speciesId",
    "",                         # empty
    "commonname",               # right word, wrong case — still refused
    "commonName; DROP TABLE species",
    "common_name DESC",         # trying to smuggle in SQL
    "1",
])
def test_sort_by_rejects_everything_else_with_422(bad_value):
    """
    Anything outside the whitelist must be refused BEFORE any SQL runs — 422,
    not a 500 and not a silent fallback to some default ordering. This test
    needs no database, because the rejection happens first.
    """
    response = client.get("/api/species", params={"sort_by": bad_value})
    assert response.status_code == 422, (
        f"'{bad_value}' was not rejected — check the SortBy whitelist in "
        "app/routers/species.py"
    )


@needs_b6_schema
def test_omitting_sort_by_keeps_the_original_ordering():
    """Leaving sort_by out must behave exactly as it did before it existed."""
    body = client.get("/api/species").json()
    counts = [item["recordCount"] for item in body["items"]]
    assert counts == sorted(counts, reverse=True), "default is most-recorded first"


# =============================================================================
# 2. group — the filter
# =============================================================================

@needs_b6_schema
def test_group_filter_returns_only_that_group():
    everything = client.get("/api/species").json()
    a_group = everything["items"][0]["group"]

    response = client.get("/api/species", params={"group": a_group})

    assert response.status_code == 200
    body = response.json()
    assert body["items"], "the filter removed everything"
    assert {item["group"] for item in body["items"]} == {a_group}
    assert body["total"] <= everything["total"]


@needs_b6_schema
def test_group_filter_with_no_matches_is_empty_not_an_error():
    response = client.get("/api/species", params={"group": "no-such-group"})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


@needs_b6_schema
def test_group_filter_is_not_vulnerable_to_injection():
    """
    The group name is caller-supplied text. It travels as a parameter, so even a
    value shaped like SQL is treated as an ordinary string that simply matches
    nothing.
    """
    response = client.get("/api/species", params={"group": "birds'; DROP TABLE species;--"})

    assert response.status_code == 200
    assert response.json()["items"] == []

    # And the table is still there afterwards.
    assert client.get("/api/species").json()["total"] > 0


@needs_b6_schema
def test_sort_and_filter_work_together_with_pagination():
    body = client.get(
        "/api/species",
        params={"sort_by": "scientificName", "pageSize": 2, "page": 1},
    ).json()

    assert len(body["items"]) <= 2
    assert body["pageSize"] == 2
    assert body["page"] == 1


# =============================================================================
# 3. Row caps — no request may ever pull out everything
# =============================================================================

@pytest.mark.parametrize("path", ["/api/species", "/api/records"])
def test_asking_for_more_than_the_cap_is_refused(path):
    over = config.MAX_PAGE_SIZE + 1
    assert client.get(path, params={"pageSize": over}).status_code == 422
    assert client.get(path, params={"pageSize": 100000}).status_code == 422


@needs_b6_schema
@pytest.mark.parametrize("path", ["/api/species", "/api/records"])
def test_the_cap_itself_is_allowed(path):
    response = client.get(path, params={"pageSize": config.MAX_PAGE_SIZE})
    assert response.status_code == 200
    assert len(response.json()["items"]) <= config.MAX_PAGE_SIZE


@needs_b6_schema
def test_distribution_cells_is_capped(monkeypatch):
    """
    The map-data endpoint has no pageSize, so its cap is the only thing standing
    between a caller and the entire grid. Shrink it and check it actually bites.
    """
    monkeypatch.setattr(config, "MAX_CELLS", 1)

    body = client.get("/api/distribution/cells").json()

    assert len(body["features"]) <= 1


@needs_b6_schema
def test_summary_lists_are_capped(monkeypatch):
    monkeypatch.setattr(config, "MAX_YEAR_BUCKETS", 1)
    monkeypatch.setattr(config, "MAX_GROUPS", 1)

    body = client.get("/api/summary").json()

    assert len(body["recordsByYear"]) <= 1
    assert len(body["topGroups"]) <= 1
    # The headline totals are counts, not lists — they must stay truthful.
    assert body["totalRecords"] > 0


# =============================================================================
# 4. /api/records — newest first, and no ranking
# =============================================================================

@needs_b6_schema
def test_records_come_back_newest_first():
    body = client.get("/api/records", params={"pageSize": 50}).json()
    years = [item["year"] for item in body["items"]]
    assert years == sorted(years, reverse=True)


@needs_b6_schema
def test_records_response_has_no_ranking_or_top_n_shape():
    """
    A record list must be a plain page of records. No rank, score, position or
    "top" wrapper — those imply an editorial judgement about which sightings
    matter, which is not something a records centre should publish.
    """
    body = client.get("/api/records").json()

    assert set(body) == {"items", "total", "page", "pageSize"}

    banned = {"rank", "score", "position", "top", "topN", "ranking", "featured"}
    for item in body["items"]:
        leaked = banned & set(item)
        assert not leaked, f"ranking-style fields appeared in a record: {leaked}"


@needs_b6_schema
def test_precision_metres_field_name_is_unchanged():
    """The front end depends on this exact spelling — it must not drift."""
    body = client.get("/api/records").json()
    if body["items"]:
        assert "precisionMetres" in body["items"][0]


# =============================================================================
# 5. /api/meta/provenance — what it must NOT say
# =============================================================================

@needs_b6_schema
@needs_load_date
def test_provenance_no_longer_lists_sources_or_explains_generalisation():
    body = client.get("/api/meta/provenance").json()

    assert "sources" not in body, (
        "the per-source list is back — naming contributing datasets narrows down "
        "who recorded what, and where"
    )
    assert "sensitivityPolicySummary" not in body, (
        "the generalisation description is back — publishing the blurring rules "
        "tells someone how much precision to add back"
    )

    assert set(body) == {"caveats", "lastUpdated"}


@needs_b6_schema
@needs_load_date
def test_provenance_last_updated_is_the_newest_load_date():
    """
    lastUpdated is measured from the data, not typed in by hand — so it can't
    silently go stale.
    """
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(load_date) AS newest FROM public_records;")
            newest = cur.fetchone()["newest"]

    body = client.get("/api/meta/provenance").json()

    assert body["lastUpdated"] == newest.isoformat()
    assert body["caveats"], "caveats should still be published"


# =============================================================================
# 6. There is no bulk export, anywhere
# =============================================================================

def test_no_route_offers_a_bulk_export_or_download():
    """
    Checks every route the app actually registers, so a new one can't quietly
    add a CSV endpoint. The public dashboard answers questions about the data;
    it does not hand over the dataset.
    """
    suspicious = ("csv", "export", "download", "dump", "bulk", "xlsx", "raw")

    for route in app.routes:
        path = getattr(route, "path", "")
        assert not any(word in path.lower() for word in suspicious), (
            f"route {path} looks like a bulk export — the public API must not "
            "offer one"
        )

        # Read-only: nothing may accept a write method either.
        methods = getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD", "OPTIONS"}, (
            f"route {path} allows {methods - {'GET', 'HEAD', 'OPTIONS'}} — this "
            "API is read-only"
        )


def test_every_list_endpoint_declares_a_cap():
    """
    A structural check: the caps exist and are sane. If someone sets one to zero
    or removes it, this fails loudly rather than the API quietly serving
    everything.
    """
    for name in ("MAX_PAGE_SIZE", "MAX_CELLS", "MAX_YEAR_BUCKETS", "MAX_GROUPS"):
        value = getattr(config, name, None)
        assert isinstance(value, int) and value > 0, f"{name} is not a positive cap"

"""
Integration test — proves the API reads REAL data through the b6 schema and
the fail-closed public views hold.

Requires: db/b6_schema.sql AND db/b6_seed_sample.sql applied, with
DATABASE_URL pointing at that database. Skipped automatically (via
@needs_b6_schema) if the b6 schema isn't loaded, so it never breaks a plain
CI run without a database.

Why this test exists: it is easy to *think* an endpoint is wired to the database
when it is silently still returning hardcoded values. These assertions check the
counts that only the real sample data produces.
"""

from fastapi.testclient import TestClient

from app.main import app 
from conftest import needs_b6_schema  # shared skip marker

client = TestClient(app)


@needs_b6_schema
def test_species_returns_real_counts_not_stub_values():
    """/api/species reads public_species — sample data has 3 species, counts 3, 2, 2."""
    r = client.get("/api/species")
    assert r.status_code == 200
    body = r.json()

    assert body["total"] == 3, "Expected 3 species from the sample data"

    counts = sorted(item["recordCount"] for item in body["items"])
    assert counts == [2, 2, 3], (
        f"Got {counts} — if these are large numbers, the endpoint is still "
        "returning hardcoded stub data instead of querying the database."
    )
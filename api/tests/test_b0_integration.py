"""
B0 integration test — proves the API reads REAL data and the safe view holds.

Requires: the brerc_ui database set up via db/b0_staging_setup.sql, and
DATABASE_URL pointing at it. Skipped automatically if no database is reachable,
so it never breaks CI on a machine without PostgreSQL.

Why this test exists: it is easy to *think* an endpoint is wired to the database
when it is silently still returning hardcoded values. These assertions check the
counts that only the real sample data produces.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_connection

client = TestClient(app)


def _database_available() -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok;")
                cur.fetchone()
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _database_available(),
    reason="No database reachable — set DATABASE_URL and run db/b0_staging_setup.sql",
)


@needs_db
def test_species_returns_real_counts_not_stub_values():
    """The sample data has exactly 3 species with counts 3, 2, 2."""
    r = client.get("/api/species")
    assert r.status_code == 200
    body = r.json()

    assert body["total"] == 3, "Expected 3 species from the sample data"

    counts = sorted(item["recordCount"] for item in body["items"])
    assert counts == [2, 2, 3], (
        f"Got {counts} — if these are large numbers, the endpoint is still "
        "returning hardcoded stub data instead of querying the database."
    )


@needs_db
def test_safe_view_excludes_personal_and_precise_columns():
    """
    The public view must not expose recorder names, free-text place, or precise
    coordinates. This is the safety boundary — assert it directly.
    """
    forbidden = {"recorder1", "place", "eastings", "northings"}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM public_occurrences LIMIT 1;")
            cur.fetchone()
            columns = {desc.name.lower() for desc in cur.description}

    leaked = forbidden & columns
    assert not leaked, f"Safe view leaks forbidden columns: {leaked}"


@needs_db
def test_sensitive_records_are_blurred_more_coarsely():
    """Sensitive rows must carry a coarser precision than ordinary rows."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT precision_metres
                FROM public_occurrences
                WHERE scientific_name = %s;
                """,
                ("Lutra lutra",),
            )
            precisions = [row["precision_metres"] for row in cur.fetchall()]

    assert precisions == [10000], (
        f"Sensitive species precision was {precisions}, expected [10000] — "
        "the generalisation is not being applied."
    )

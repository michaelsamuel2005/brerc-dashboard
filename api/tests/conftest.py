"""
Shared test helpers (pytest loads this file automatically — no import needed
for fixtures, but we also expose `needs_db` for tests to import directly).

The important piece is `database_available()`. A few tests only make sense when a
PostgreSQL UI database is reachable (they check real counts and the safe view).
On a machine — or a CI runner — without one, those tests SKIP instead of FAIL,
so the suite stays green everywhere while still running fully once you've set up
db/b0_staging_setup.sql and pointed DATABASE_URL at it.
"""

import pytest

from app.db import get_connection


def database_available() -> bool:
    """True if we can open a connection and run a trivial query, else False."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True
    except Exception:
        return False


# Reusable decorator: skip the marked test when no database is reachable.
needs_db = pytest.mark.skipif(
    not database_available(),
    reason="No database reachable — set DATABASE_URL and run db/b0_staging_setup.sql",
)


def _relation_exists(name: str) -> bool:
    """True if a table/view called `name` exists in the connected database."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present;", (name,))
                return bool(cur.fetchone()["present"])
    except Exception:
        return False


# Reusable decorator: skip when the B6 schema (db/b6_schema.sql) isn't loaded, so
# these tests run once you've applied it but never break a plain B0 CI run.
needs_b6_schema = pytest.mark.skipif(
    not _relation_exists("public_records"),
    reason="B6 schema not loaded — run db/b6_schema.sql against DATABASE_URL",
)

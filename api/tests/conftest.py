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

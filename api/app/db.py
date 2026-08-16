"""Read-only access to the published serving views.

Three properties are enforced here rather than trusted:

1. Every statement runs in a read-only transaction with a statement timeout.
2. The connection must belong to a role that cannot write.  A deployment that
   accidentally points the API at a writable role fails at startup instead of
   quietly running with more privilege than it needs.
3. Only ``serve.*`` relations may be named.  Those views apply the release's own
   publication capabilities in SQL, so the API cannot reach a base table or
   return a field the release did not authorise.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress

import psycopg
from psycopg.rows import dict_row

from app.config import DB_STATEMENT_TIMEOUT_MS, require_database_url

#: The only relations this service may read.  Base tables in loader_control,
#: loader_stage and publication are deliberately absent.
SERVING_RELATIONS = frozenset(
    {
        "serve.public_release",
        "serve.public_species",
        "serve.public_distribution_cell",
        "serve.public_species_year",
        "serve.public_record",
    }
)


class ServingRelationError(RuntimeError):
    """A query named a relation outside the published serving surface."""


def assert_serving_relation(relation: str) -> str:
    """Guard for query builders; returns the relation so it reads inline."""
    if relation not in SERVING_RELATIONS:
        raise ServingRelationError(f"not a published serving relation: {relation!r}")
    return relation


@contextmanager
def serving_connection() -> Iterator[psycopg.Connection]:
    """Open one read-only, time-bounded connection to the publication database."""
    connection = psycopg.connect(
        require_database_url(),
        row_factory=dict_row,
        autocommit=False,
        options=f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}",
    )
    try:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_read_only') AS read_only, "
                "pg_catalog.pg_has_role(current_user, 'pg_write_all_data', 'USAGE') AS can_write_all"
            )
            session = cursor.fetchone()
            if session is None or session["read_only"] != "on" or session["can_write_all"]:
                raise RuntimeError("publication database session is not read-only")
        yield connection
    finally:
        with_suppressed_close(connection)


def with_suppressed_close(connection: psycopg.Connection) -> None:
    """Close without masking an exception already propagating from the caller.

    A failure while tidying up must not replace the error the caller is already
    handling — that turns a clear fault into a confusing one.
    """
    with suppress(Exception):
        connection.rollback()
    with suppress(Exception):
        connection.close()

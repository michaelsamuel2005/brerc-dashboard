"""
Database connection for the API (B0).

Keeps the connection details in ONE place: all connection fields (host,
port, dbname, user, password) are read from safety.yaml's `destination:`
block, so environments can differ (local / staging / prod) just by
editing config. NOTE: this means safety.yaml holds a real password when
filled in for a real environment — keep that file out of version control
(or restrict its permissions) in any environment where it holds real
credentials.

If DATABASE_URL is set directly in the environment, it takes priority
over the assembled safety.yaml URL, so deployments that already inject a
full connection string keep working unchanged.

The API opens a connection per request and closes it. That is simple and
correct for B0; connection pooling comes later if it is needed.

SAFETY RULES enforced here and in every query:

- queries read ONLY from the public_* views (public_species, public_records,
  public_cells, public_provenance), never the base tables
- all SQL is parameterised (%s placeholders) — never string-formatted, which is
  how SQL injection happens
- this connection is READ-ONLY (connects as brerc_api_ro). Schema-mutating
  operations (drop/create/reload) do NOT live here — see
  etl/load/admin.py::force_full_reload, which uses a separate connection
  with actual DDL privileges. Keeping admin operations out of the
  serving layer means a bug or bad request here can never touch schema.
"""

import os
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.rows import dict_row

from etl.load.loader import load_safety_config


# Load api/.env (if it exists) so credentials can live in a git-ignored file
# instead of being typed into the shell every time. We point at the .env next
# to the api/ folder explicitly, so it is found no matter which folder you run from.

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# CONFIG and _DESTINATION are loaded lazily (not at import time) because
# safety.yaml may not exist on a fresh clone — importing this module must
# not require the file to be present. lru_cache means the file is still
# only read once per process, just on first use instead of at import.

@lru_cache(maxsize=1)
def get_config() -> dict:
    return load_safety_config()


def _get_destination() -> dict:
    return get_config().get("destination", {})


# How long (ms) a single query may run before Postgres cancels it.
# Guards against one runaway/badly-indexed query hanging the whole API.
# Since each request holds its own connection, a stuck query would otherwise
# tie that connection up indefinitely.

STATEMENT_TIMEOUT_MS = 10_000  # 10s — generous for this dataset's scale


# Only these public views may be accessed by the API.
# The API should never query the underlying B6 base tables directly.

B6_PUBLIC_RELATIONS = {
    "public_species",
    "public_records",
    "public_cells",
    "public_provenance",
}


def _build_database_url() -> str:
    """
    Assemble the UI database connection string entirely from
    safety.yaml's `destination:` block (host, port, dbname, user,
    password).

    DATABASE_URL, if set directly in the environment, overrides all of
    this — useful for deployments that inject a full connection string
    as one secret.
    """

    explicit_url = os.getenv("DATABASE_URL")

    if explicit_url:
        return explicit_url

    # Local development defaults so this still runs before safety.yaml
    # is filled in for a real environment — contain no real secret.

    destination = _get_destination()

    host = destination.get("dbhostname") or "localhost"
    port = destination.get("port") or 5432
    dbname = destination.get("dbname") or "brerc_ui"
    user = destination.get("user") or "postgres"
    password = destination.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


# Built lazily too, since it transitively depends on safety.yaml via
# _get_destination(). Cached so the URL is only assembled once.

@lru_cache(maxsize=1)
def get_database_url() -> str:
    return _build_database_url()


def get_connection() -> psycopg.Connection:
    """
    Open a read-only connection to the UI database.

    `row_factory=dict_row` makes each returned row behave like a dictionary
    ({"scientific_name": "...", ...}) instead of a plain tuple, which makes
    the endpoint code much easier to read.

    `statement_timeout` caps how long any single query may run
    (see STATEMENT_TIMEOUT_MS above).
    """

    return psycopg.connect(
        get_database_url(),
        row_factory=dict_row,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


def _validate_public_relation(table_name: str) -> None:
    """
    Ensure the requested relation is one of the approved public views.

    The API must never query the underlying B6 base tables.
    """

    if table_name not in B6_PUBLIC_RELATIONS:
        raise ValueError(
            f"Unsupported public relation: {table_name}"
        )


def check_table_exists(connection, table_name: str) -> bool:
    """
    Return True if `table_name` exists.

    Only approved public views may be checked.
    """

    _validate_public_relation(table_name)

    with connection.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS exists;",
            (table_name,),
        )

        return bool(cur.fetchone()["exists"])


def check_table_has_rows(connection, table_name: str) -> bool:
    """
    Return True if `table_name` has at least one row.

    Only approved public views may be queried.
    """

    _validate_public_relation(table_name)

    query = sql.SQL(
        "SELECT EXISTS (SELECT 1 FROM {} LIMIT 1) AS has_rows;"
    ).format(
        sql.Identifier(table_name)
    )

    with connection.cursor() as cur:
        cur.execute(query)

        return bool(cur.fetchone()["has_rows"])
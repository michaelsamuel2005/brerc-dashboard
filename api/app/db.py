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

The API opens a connection per request and closes it. That is simple and correct
for B0; connection pooling comes later if it is needed.

SAFETY RULES enforced here and in every query:
  * queries read ONLY from the public_* views (public_species, public_records,
    public_cells, public_provenance), never the base tables
  * all SQL is parameterised (%s placeholders) — never string-formatted, which is
    how SQL injection happens
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from etl.load.loader import load_safety_config

# Load api/.env (if it exists) so credentials can live in a git-ignored file
# instead of being typed into the shell every time. We point at the .env next to
# the api/ folder explicitly, so it is found no matter which folder you run from.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CONFIG = load_safety_config()
_DESTINATION = CONFIG.get("destination", {})


def _build_database_url() -> str:
    """
    Assembles the UI database connection string entirely from
    safety.yaml's `destination:` block (host, port, dbname, user,
    password).

    DATABASE_URL, if set directly in the environment, overrides all of
    this - useful for deployments that inject a full connection string
    as one secret.
    """
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    # Local development defaults so this still runs before safety.yaml
    # is filled in for a real environment - contain no real secret.
    host = _DESTINATION.get("dbhostname") or "localhost"
    port = _DESTINATION.get("port") or 5432
    dbname = _DESTINATION.get("dbname") or "brerc_ui"
    user = _DESTINATION.get("user") or "postgres"
    password = _DESTINATION.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


DATABASE_URL = _build_database_url()

B6_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "db"
    / "b6_schema.sql"
)

def get_connection() -> psycopg.Connection:
    """
    Open a connection to the UI database.

    `row_factory=dict_row` makes each returned row behave like a dictionary
    ({"scientific_name": "...", ...}) instead of a plain tuple, which makes the
    endpoint code much easier to read.
    """
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def check_table_exists(connection, table_name: str) -> bool:
    """True if `table_name` exists as a table/view in the connected database."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS exists;",
            (table_name,),
        )
        return bool(cur.fetchone()["exists"])

def check_table_has_rows(connection, table_name: str) -> bool:
    """True if `table_name` has at least one row. Assumes the table exists."""
    with connection.cursor() as cur:
        cur.execute(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1) AS has_rows;")
        return bool(cur.fetchone()["has_rows"])

def force_full_reload(connection, schema_path: Path = B6_SCHEMA_PATH):
    """
    Drops and recreates the full B6 schema (species, occurrence_public,
    distribution_cell, provenance + views + indexes + role grants) by
    replaying db/b6_schema.sql. Used when safety.yaml's incremental_check
    is false, or when a table is missing/empty - i.e. the "someone
    corrupted the destination, force a clean rebuild" lever.

    Runs the whole file (not per-table) because occurrence_public has a
    FK into species - reloading one without the other breaks the FK.
    """
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    with connection.cursor() as cur:
        cur.execute(schema_sql)
    connection.commit()
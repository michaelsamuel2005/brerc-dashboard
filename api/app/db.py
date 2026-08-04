"""
Database connection for the API (B0).

Keeps the connection details in ONE place, read from an environment variable,
so that moving from your laptop to a real server is a credentials change only
(no code change) — that is decision D-005.

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

# Load api/.env (if it exists) so DATABASE_URL can live in a git-ignored file
# instead of being typed into the shell every time. We point at the .env next to
# the api/ folder explicitly, so it is found no matter which folder you run from.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Read the connection string from the environment. The fallback is a local
# development default — it contains no real secret.
#
# Format: postgresql://USER:PASSWORD@HOST:PORT/DATABASE
# Put your real one in a git-ignored .env file, never in this file.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/brerc_ui",
)

B6_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "b6_schema.sql"


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
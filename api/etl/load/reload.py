"""
Admin and ops database operations for B6 schema rebuilds.

Why this is separate from api/app/db.py:
That module serves the public API using a read-only user (brerc_api_ro).
rebuilding or dropping schemas requires admin privileges (DDL rights) and 
has no business being near API request handlers where a bug could wipe data.
This module uses a separate admin connection via DATABASE_URL_ADMIN or safety.yaml.
"""

import os
from functools import lru_cache
from pathlib import Path

import psycopg

from etl.load.loader import load_safety_config


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Lazily loads and caches safety configuration once per process."""
    return load_safety_config()


def _get_admin() -> dict:
    """Extracts the admin configuration block."""
    return get_config().get("admin", {})


B6_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "db" / "b6_schema.sql"


def _build_admin_database_url() -> str:
    """
    Builds the admin connection string, preferring the DATABASE_URL_ADMIN 
    environment variable if available, otherwise falling back to safety.yaml.
    """
    explicit_url = os.getenv("DATABASE_URL_ADMIN")

    if explicit_url:
        return explicit_url

    admin = _get_admin()

    host = admin.get("dbhostname") or "localhost"
    port = admin.get("port") or 5432
    dbname = admin.get("dbname") or "brerc_ui"
    user = admin.get("user") or "postgres"
    password = admin.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_admin_connection() -> psycopg.Connection:
    """Opens a database connection with DDL privileges for schema changes."""
    return psycopg.connect(_build_admin_database_url())


def force_full_reload(
    connection=None,
    schema_path: Path = B6_SCHEMA_PATH,
):
    """
    Drops and recreates the entire B6 database schema by running the b6_schema.sql file.
    Used for full resets when tables are missing, empty, or incremental checks fail.
    """
    # Track whether we opened our own connection so we know to close it later
    owns_connection = connection is None

    if owns_connection:
        connection = get_admin_connection()

    try:
        # Read the SQL schema setup file
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        # Execute the entire script to reset tables, views, and constraints
        with connection.cursor() as cur:
            cur.execute(schema_sql)

        connection.commit()

    finally:
        # Clean up the connection if we opened it locally
        if owns_connection:
            connection.close()

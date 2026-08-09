"""
Admin/ops database operations for B6 (schema rebuild).

Deliberately kept OUT of api/app/db.py: that module serves the public API
and connects as brerc_api_ro (read-only). force_full_reload drops and
recreates the schema, which has no business being reachable from the
read-only serving layer — a stray call, a bug, or an under-authenticated
route in the API package is exactly the kind of thing an adversarial
audit flags if this lives next to the request handlers.

This connection uses a role with actual DDL privileges. Set
DATABASE_URL_ADMIN in the environment (or extend safety.yaml with an
`admin:` block) — do NOT reuse the api's read-only DATABASE_URL here.
"""

import os
from pathlib import Path

import psycopg

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()
_ADMIN = CONFIG.get("admin", {})

B6_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "db"
    / "b6_schema.sql"
)


def _build_admin_database_url() -> str:
    """
    Connection string for schema-mutating operations. Prefers
    DATABASE_URL_ADMIN if set; otherwise uses the `admin:` block
    in safety.yaml.
    """
    explicit_url = os.getenv("DATABASE_URL_ADMIN")

    if explicit_url:
        return explicit_url

    host = _ADMIN.get("dbhostname") or "localhost"
    port = _ADMIN.get("port") or 5432
    dbname = _ADMIN.get("dbname") or "brerc_ui"
    user = _ADMIN.get("user") or "postgres"
    password = _ADMIN.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_admin_connection() -> psycopg.Connection:
    """Open a connection with DDL privileges, for schema rebuild only."""
    return psycopg.connect(_build_admin_database_url())


def force_full_reload(
    connection=None,
    schema_path: Path = B6_SCHEMA_PATH,
):
    """
    Drops and recreates the full B6 schema (species, occurrence_public,
    distribution_cell, provenance + views + indexes + role grants) by
    replaying db/b6_schema.sql. Used when safety.yaml's incremental_check
    is false, or when a table is missing/empty - i.e. the "someone
    corrupted the destination, force a clean rebuild" lever.

    Runs the whole file (not per-table) because occurrence_public has a
    FK into species - reloading one without the other breaks the FK.

    Pass an existing connection if you already have one open with DDL
    rights; otherwise one is opened via get_admin_connection().
    """
    owns_connection = connection is None

    if owns_connection:
        connection = get_admin_connection()

    try:
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        with connection.cursor() as cur:
            cur.execute(schema_sql)

        connection.commit()

    finally:
        if owns_connection:
            connection.close()

